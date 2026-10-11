"""Synthetic OpenAI-compatible upstream for the isolated T00-G Compose test."""

from __future__ import annotations

import hashlib
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


LOCK = threading.Lock()
EXPECTATIONS: dict[str, str] = {}
PROJECT_KEY_HASHES: set[str] = set()
PROJECT_KEY_HASH_VALUES: set[str] = set()
PROVIDER_KEY_HASH_VALUES: dict[str, str] = {}
MASTER_KEY_HASH = ""
MASTER_KEY_HASH_VALUE = ""
RECORDS: list[dict] = []


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class Handler(BaseHTTPRequestHandler):
    server_version = "T00G-Synthetic-Upstream"

    def log_message(self, _format: str, *_args) -> None:
        return

    def _json(self, status: int, body: dict) -> None:
        encoded = json.dumps(body, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self) -> None:
        if self.path == "/healthz":
            self._json(200, {"status": "ok"})
            return
        if self.path == "/test/records":
            with LOCK:
                rows = list(RECORDS)
            self._json(200, {"records": rows})
            return
        self._json(404, {"error": "not_found"})

    def do_POST(self) -> None:
        try:
            length = int(self.headers.get("content-length", "0"))
        except ValueError:
            self._json(400, {"error": "invalid_length"})
            return
        if length < 0 or length > 1_048_576:
            self._json(413, {"error": "request_too_large"})
            return
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._json(400, {"error": "invalid_json"})
            return

        if self.path == "/test/expectations":
            provider_hashes = payload.get("provider_key_hashes")
            project_hashes = payload.get("project_key_hashes")
            master_hash = payload.get("master_key_hash")
            # The harness sends SHA-256 fingerprints, never raw provider keys.
            # Use those fingerprints directly for exact bearer matching; hash
            # them once more only to detect accidental forwarding of the hash.
            provider_hash_lookup = {value: label for label, value in provider_hashes.items()} if isinstance(provider_hashes, dict) else {}
            provider_key_hash_values = {
                digest(value): label for label, value in provider_hashes.items()
            } if isinstance(provider_hashes, dict) else {}
            if (
                not isinstance(provider_hashes, dict)
                or not isinstance(project_hashes, list)
                or not isinstance(master_hash, str)
                or any(not isinstance(value, str) or len(value) != 64 for value in provider_hashes.values())
                or any(not isinstance(value, str) or len(value) != 64 for value in project_hashes)
                or len(master_hash) != 64
            ):
                self._json(400, {"error": "invalid_expectations"})
                return
            with LOCK:
                EXPECTATIONS.clear()
                EXPECTATIONS.update(provider_hash_lookup)
                PROJECT_KEY_HASHES.clear()
                PROJECT_KEY_HASHES.update(project_hashes)
                PROJECT_KEY_HASH_VALUES.clear()
                PROJECT_KEY_HASH_VALUES.update(digest(value) for value in project_hashes)
                PROVIDER_KEY_HASH_VALUES.clear()
                PROVIDER_KEY_HASH_VALUES.update(provider_key_hash_values)
                global MASTER_KEY_HASH, MASTER_KEY_HASH_VALUE
                MASTER_KEY_HASH = master_hash
                MASTER_KEY_HASH_VALUE = digest(master_hash)
                RECORDS.clear()
            self._json(200, {"registered": len(provider_hashes) + len(project_hashes) + 1})
            return

        if self.path not in {"/v1/chat/completions", "/chat/completions"}:
            self._json(404, {"error": "not_found"})
            return

        authorization_values = self.headers.get_all("authorization", [])
        bearer_values = [
            value[7:]
            for value in authorization_values
            if value.lower().startswith("bearer ")
        ]
        bearer = bearer_values[0] if bearer_values else ""
        credential_hash = digest(bearer) if bearer else ""
        with LOCK:
            authorization_provider_labels = [
                EXPECTATIONS.get(digest(value), "") for value in bearer_values
            ]
            authorization_provider_label = next((label for label in authorization_provider_labels if label), "")
            provider_label = authorization_provider_label or EXPECTATIONS.get(credential_hash, "")
            provider_hash_label = PROVIDER_KEY_HASH_VALUES.get(credential_hash, "")
            alternate_provider_headers = {
                header_name: EXPECTATIONS.get(digest(self.headers.get(header_name, "")), "")
                for header_name in ("api-key", "x-api-key", "x-litellm-api-key", "anthropic-api-key", "x-goog-api-key")
                if self.headers.get(header_name)
            }
            alternate_provider_label = next((label for label in alternate_provider_headers.values() if label), "")
            is_project_key = credential_hash in PROJECT_KEY_HASHES
            is_project_key_hash = credential_hash in PROJECT_KEY_HASH_VALUES
            is_master_key = credential_hash == MASTER_KEY_HASH
            is_master_key_hash = credential_hash == MASTER_KEY_HASH_VALUE
            request_provider_key = payload.get("api_key")
            request_provider_label = (
                EXPECTATIONS.get(digest(request_provider_key), "")
                if isinstance(request_provider_key, str) and request_provider_key
                else ""
            )
            message_values = [
                item.get("content")
                for item in payload.get("messages", [])
                if isinstance(item, dict)
            ]
            record = {
                "ordinal": len(RECORDS) + 1,
                "model": payload.get("model"),
                "provider_label": provider_label or alternate_provider_label or "unknown",
                "authorization_class": (
                    "provider_key" if provider_label else
                    "provider_key_alternate_header" if alternate_provider_label else
                    "provider_key_hash" if provider_hash_label else
                    "project_virtual_key" if is_project_key else
                    "project_virtual_key_hash" if is_project_key_hash else
                    "master_key" if is_master_key else
                    "master_key_hash" if is_master_key_hash else
                    "other_bearer" if bearer else
                    "missing"
                ),
                "provider_key_hash_label": provider_hash_label or "none",
                "provider_auth_header": "authorization" if provider_label else next(
                    (name for name, label in alternate_provider_headers.items() if label), "unmatched"
                ),
                "authorization_header_count": len(authorization_values),
                "authorization_provider_labels": [label for label in authorization_provider_labels if label],
                "alternate_provider_header_names": sorted(alternate_provider_headers),
                "alternate_provider_header_labels": {
                    name: label for name, label in alternate_provider_headers.items() if label
                },
                "request_body_provider_key_label": request_provider_label or ("unknown" if request_provider_key else "missing"),
                "provider_auth_scheme": "bearer" if bearer else "missing",
                "provider_auth_credential_shape": (
                    "nested_bearer" if bearer.lower().startswith("bearer ") else
                    "sha256_hex" if re.fullmatch(r"[0-9a-fA-F]{64}", bearer) else
                    "sk_prefixed" if bearer.startswith("sk-") else
                    "other" if bearer else
                    "missing"
                ),
                "provider_auth_credential_length": len(bearer),
                "project_key_forwarded": is_project_key,
                "project_key_hash_forwarded": is_project_key_hash,
                "master_key_forwarded": is_master_key,
                "master_key_hash_forwarded": is_master_key_hash,
                "body_api_key_present": "api_key" in payload,
                "prompt_marker_seen": any(
                    isinstance(value, str) and value.startswith("T00G_PRIVATE_PROMPT_")
                    for value in message_values
                ),
                "message_count": len(message_values),
            }
            RECORDS.append(record)

        if not provider_label and not alternate_provider_label:
            self._json(401, {"error": {"message": "synthetic provider credential rejected"}})
            return

        self._json(
            200,
            {
                "id": f"chatcmpl-t00g-{record['ordinal']}",
                "object": "chat.completion",
                "created": 1791763200,
                "model": payload.get("model", "test-model"),
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "synthetic gateway response"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10},
            },
        )


def main() -> None:
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()


if __name__ == "__main__":
    main()
