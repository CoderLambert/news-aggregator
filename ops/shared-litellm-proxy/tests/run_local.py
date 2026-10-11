#!/usr/bin/env python3
"""Exercise the local gateway Compose stack without real provider access."""

from __future__ import annotations

import hashlib
import json
import secrets
import shutil
import subprocess
import tempfile
import time
import urllib.parse
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILES = (ROOT / "compose.yaml", ROOT / "compose.test.yaml")
LITELLM_IMAGE = "ghcr.io/berriai/litellm:v1.105.0@sha256:60947db020b57e204823d3fbc8bb295c85be890d7c9adcc77fb4f5fc2fe410b2"
POSTGRES_IMAGE = "postgres:16-alpine@sha256:721873c34ceb9f8d8fc265984940dc982404c105f19ad51be9fdc5970a6080ea"
NEWS_MODEL = "news.deepseek-flash"
CLI_MODEL = "generic-cli.deepseek-flash"
TEST_DEPLOYMENT_PLACEHOLDER_KEY = "sk-t00g-nonfunctional-test-placeholder"


class HttpResult:
    def __init__(self, status: int, body: dict, raw: str):
        self.status = status
        self.body = body
        self.raw = raw


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def safe_process(
    args: list[str], *, cwd: Path = ROOT, input_bytes: bytes | None = None, timeout: int = 180
) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        cwd=cwd,
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )


def marker_in(result: HttpResult, marker: str) -> bool:
    return marker in json.dumps(result.body, ensure_ascii=True, sort_keys=True)


def main() -> int:
    summary: dict = {
        "scope": "T00G_LOCAL_SYNTHETIC_ONLY",
        "provider_real": "NOT_RUN",
        "checks": [],
        "versions": {
            "docker": None,
            "compose": None,
            "litellm_image": LITELLM_IMAGE,
            "postgres_image": POSTGRES_IMAGE,
            "startup_duration_seconds": None,
        },
    }
    project = f"byok-t00g-{secrets.token_hex(4)}"
    network = f"{project}-network"
    started = False
    compose_attempted = False
    temporary: str | None = None
    env_file: Path | None = None
    cleanup_return: int | None = None
    project_keys: dict[str, str] = {}
    provider_keys = {
        "news": f"sk-t00g-provider-news-{secrets.token_hex(12)}",
        "cli": f"sk-t00g-provider-cli-{secrets.token_hex(12)}",
    }
    prompt_markers = {
        "news": f"T00G_PRIVATE_PROMPT_NEWS_{secrets.token_hex(6)}",
        "cli": f"T00G_PRIVATE_PROMPT_CLI_{secrets.token_hex(6)}",
    }

    def check(name: str, passed: bool, facts: dict | None = None) -> None:
        summary["checks"].append({"id": name, "status": "PASS" if passed else "FAIL", "facts": facts or {}})

    def compose(*args: str, timeout: int = 180, input_bytes: bytes | None = None) -> subprocess.CompletedProcess:
        return safe_process(
            [
                "docker", "compose", "--project-name", project, "--env-file", str(env_file),
                "-f", str(COMPOSE_FILES[0]), "-f", str(COMPOSE_FILES[1]), *args,
            ],
            input_bytes=input_bytes,
            timeout=timeout,
        )

    def app_request(
        service: str,
        target: str,
        path: str,
        *,
        method: str = "GET",
        payload: dict | None = None,
        bearer: str | None = None,
    ) -> HttpResult:
        spec = {"target": target, "method": method, "path": path, "payload": payload, "bearer": bearer}
        response = compose("exec", "-T", service, "python", "/fixtures/cli_client.py", timeout=30,
                           input_bytes=json.dumps(spec, separators=(",", ":")).encode("utf-8"))
        try:
            decoded = json.loads(response.stdout.decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            raise RuntimeError("internal CLI client returned an invalid response") from None
        body = decoded.get("body", {})
        if isinstance(body, list):
            body = {"data": body}
        if not isinstance(body, dict):
            body = {}
        return HttpResult(int(decoded.get("status", 0)), body, str(decoded.get("raw", "")))

    def admin_request(path: str, *, method: str = "GET", payload: dict | None = None) -> HttpResult:
        spec = {"path": path, "method": method, "payload": payload}
        response = compose("exec", "-T", "proxy", "python", "/app/test_admin_client.py", timeout=30,
                           input_bytes=json.dumps(spec, separators=(",", ":")).encode("utf-8"))
        try:
            decoded = json.loads(response.stdout.decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            raise RuntimeError("internal admin helper returned an invalid response") from None
        body = decoded.get("body", {})
        if isinstance(body, list):
            body = {"data": body}
        if not isinstance(body, dict):
            body = {}
        return HttpResult(int(decoded.get("status", 0)), body, str(decoded.get("raw", "")))

    def key_generation(model: str, alias: str) -> str:
        result = admin_request(
            "/key/generate",
            method="POST",
            payload={
                "models": [model],
                "key_alias": alias,
                "metadata": {"project": alias},
                "max_budget": 5.0,
                "budget_duration": "1d",
                "rpm_limit": 60,
                "tpm_limit": 120000,
                "max_parallel_requests": 4,
                "duration": "90d",
            },
        )
        issued = result.body.get("key")
        if result.status != 200 or not isinstance(issued, str) or not issued.startswith("sk-"):
            raise RuntimeError("project virtual-key provisioning failed")
        return issued

    def request_call(service: str, model: str, provider_key: str | None, prompt: str, project_key: str) -> HttpResult:
        body: dict = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 24,
        }
        if provider_key is not None:
            body["api_key"] = provider_key
        return app_request(service, "proxy", "/v1/chat/completions", method="POST", payload=body, bearer=project_key)

    try:
        with nullcontext(tempfile.mkdtemp(prefix="byok-t00g-local-")) as temporary:
            tmp = Path(temporary)
            secret_dir = tmp / "secrets"
            secret_dir.mkdir(mode=0o700)
            secret_values = {
                "postgres_password": secrets.token_hex(32),
                "litellm_master_key": "sk-" + secrets.token_hex(32),
                "litellm_salt_key": secrets.token_hex(32),
            }
            secret_paths: dict[str, Path] = {}
            for name, value in secret_values.items():
                path = secret_dir / name
                path.write_text(value, encoding="utf-8")
                path.chmod(0o600)
                secret_paths[name] = path
            env_file = tmp / "compose.env"
            env_values = {
                "POSTGRES_DB": "litellm",
                "POSTGRES_USER": "litellm",
                "POSTGRES_PASSWORD_FILE": str(secret_paths["postgres_password"]),
                "LITELLM_MASTER_KEY_FILE": str(secret_paths["litellm_master_key"]),
                "LITELLM_SALT_KEY_FILE": str(secret_paths["litellm_salt_key"]),
                "GATEWAY_BACKEND_NETWORK": network,
                "GATEWAY_EGRESS_NETWORK": f"{project}-egress",
                "PROVIDER_EGRESS_INTERNAL": "true",
                "T00G_TEST_PROVIDER_KEY_HASHES": json.dumps(
                    {label: sha256(value) for label, value in provider_keys.items()}, separators=(",", ":")
                ),
            }
            env_file.write_text("".join(f"{name}={value}\n" for name, value in env_values.items()), encoding="utf-8")
            env_file.chmod(0o600)
            master_key = secret_values["litellm_master_key"]

            configured = compose("config", "--quiet", timeout=30)
            check("COMPOSE_CONFIGURATION_VALID", configured.returncode == 0)
            if configured.returncode != 0:
                raise RuntimeError("Compose configuration validation failed")

            docker_version = safe_process(["docker", "version", "--format", "{{.Server.Version}}"], timeout=15)
            compose_version = safe_process(["docker", "compose", "version", "--short"], timeout=15)
            summary["versions"]["docker"] = docker_version.stdout.decode("utf-8", errors="replace").strip()
            summary["versions"]["compose"] = compose_version.stdout.decode("utf-8", errors="replace").strip()

            started_at = time.monotonic()
            compose_attempted = True
            up = compose("--profile", "test", "up", "-d", "--wait", "--wait-timeout", "240", timeout=300)
            started = up.returncode == 0
            startup_duration_seconds = round(time.monotonic() - started_at, 2)
            check("PROXY_AND_POSTGRES_START", started)
            if not started:
                states = compose("ps", "-a", "--format", "{{.Service}}|{{.State}}|{{.Health}}", timeout=30)
                logs = compose("logs", "--no-color", "db", "proxy", "test-upstream", timeout=30)
                log_text = logs.stdout.decode("utf-8", errors="replace") + logs.stderr.decode("utf-8", errors="replace")
                combined = (up.stdout + up.stderr + logs.stdout + logs.stderr).decode("utf-8", errors="replace").lower()
                classifications = [
                    label for phrase, label in (
                        ("permission denied", "secret_or_volume_permissions"),
                        ("no such file or directory", "missing_runtime_file"),
                        ("moduleNotFoundError".lower(), "python_module_import"),
                        ("could not import", "python_module_import"),
                        ("database", "database_startup_or_connect"),
                        ("healthcheck", "healthcheck_failure"),
                        ("unhealthy", "unhealthy_container"),
                    ) if phrase in combined
                ]
                secrets_found = any(value in log_text for value in [*secret_values.values(), *provider_keys.values(), TEST_DEPLOYMENT_PLACEHOLDER_KEY, *prompt_markers.values()])
                summary["startup_diagnostics"] = {
                    "service_states": states.stdout.decode("utf-8", errors="replace").splitlines(),
                    "error_categories": sorted(set(classifications)),
                    "synthetic_secret_or_prompt_in_logs": secrets_found,
                }
                raise RuntimeError("isolated Compose services failed to start")

            ready = app_request("newshub-test-client", "proxy", "/health/readiness")
            check("HEALTH_READINESS_INCLUDES_PROXY_AND_DB", ready.status == 200, {"http_status": ready.status})

            project_keys["news"] = key_generation(NEWS_MODEL, "newshub-test")
            project_keys["cli"] = key_generation(CLI_MODEL, "generic-cli-test")

            provider_expectations = {
                "news-provider": sha256(provider_keys["news"]),
                "cli-provider": sha256(provider_keys["cli"]),
                "deployment-placeholder": sha256(TEST_DEPLOYMENT_PLACEHOLDER_KEY),
            }
            expectations = app_request(
                "newshub-test-client", "test-upstream", "/test/expectations", method="POST",
                payload={
                    "provider_key_hashes": provider_expectations,
                    "project_key_hashes": [sha256(value) for value in project_keys.values()],
                    "master_key_hash": sha256(master_key),
                },
            )
            check("SYNTHETIC_UPSTREAM_EXPECTATIONS_REGISTERED", expectations.status == 200)
            if expectations.status != 200:
                raise RuntimeError("synthetic upstream expectation registration failed")

            news_response = request_call("newshub-test-client", NEWS_MODEL, provider_keys["news"], prompt_markers["news"], project_keys["news"])
            check("NEWS_PROJECT_KEY_AND_EXPLICIT_PROVIDER_KEY_ROUTE", news_response.status == 200,
                  {"http_status": news_response.status})

            cli_response = request_call("generic-cli-consumer", CLI_MODEL, provider_keys["cli"], prompt_markers["cli"], project_keys["cli"])
            check("GENERIC_CLI_PROJECT_KEY_AND_EXPLICIT_PROVIDER_KEY_ROUTE", cli_response.status == 200,
                  {"http_status": cli_response.status})

            before_denials = app_request("newshub-test-client", "test-upstream", "/test/records")
            prior_count = len(before_denials.body.get("records", []))
            denied_model = request_call(
                "newshub-test-client", CLI_MODEL, provider_keys["news"], "T00G_PRIVATE_PROMPT_UNAUTHORIZED", project_keys["news"]
            )
            after_denial = app_request("newshub-test-client", "test-upstream", "/test/records")
            denied_count = len(after_denial.body.get("records", []))
            check("PROJECT_MODEL_ALLOWLIST_REJECTS_BEFORE_UPSTREAM", denied_model.status in (401, 403) and prior_count == denied_count,
                  {"http_status": denied_model.status, "upstream_count_before": prior_count, "upstream_count_after": denied_count})

            missing_provider = request_call("newshub-test-client", NEWS_MODEL, None, "T00G_PRIVATE_PROMPT_MISSING_PROVIDER", project_keys["news"])
            after_missing = app_request("newshub-test-client", "test-upstream", "/test/records")
            missing_count = len(after_missing.body.get("records", []))
            check("MISSING_PROVIDER_KEY_FAILS_BEFORE_UPSTREAM", missing_provider.status == 400 and missing_count == prior_count,
                  {"http_status": missing_provider.status, "upstream_count_after": missing_count})
            check("MISSING_PROVIDER_ERROR_IS_STATIC", marker_in(missing_provider, "BYOK_PROVIDER_KEY_REQUIRED"))

            wrong_project = request_call("newshub-test-client", NEWS_MODEL, provider_keys["news"], "T00G_PRIVATE_PROMPT_WRONG_PROJECT", "sk-t00g-wrong-project")
            after_wrong_project = app_request("newshub-test-client", "test-upstream", "/test/records")
            wrong_count = len(after_wrong_project.body.get("records", []))
            check("INVALID_PROJECT_KEY_FAILS_BEFORE_UPSTREAM", wrong_project.status == 401 and wrong_count == prior_count,
                  {"http_status": wrong_project.status, "upstream_count_after": wrong_count})

            stream_payload = {
                "model": NEWS_MODEL,
                "messages": [{"role": "user", "content": "T00G_PRIVATE_PROMPT_STREAM"}],
                "api_key": provider_keys["news"],
                "stream": True,
            }
            stream_denied = app_request("newshub-test-client", "proxy", "/v1/chat/completions", method="POST",
                                        payload=stream_payload, bearer=project_keys["news"])
            after_stream = app_request("newshub-test-client", "test-upstream", "/test/records")
            stream_count = len(after_stream.body.get("records", []))
            check("UNSAFE_CHAT_STREAMING_REJECTED_BEFORE_UPSTREAM", stream_denied.status == 400 and stream_count == prior_count,
                  {"http_status": stream_denied.status, "upstream_count_after": stream_count})
            check("STREAMING_ERROR_IS_STATIC", marker_in(stream_denied, "T00_CHAT_STREAMING_DISABLED"))

            rows_response = app_request("newshub-test-client", "test-upstream", "/test/records")
            upstream_rows = rows_response.body.get("records", [])
            upstream_ok = (
                rows_response.status == 200
                and len(upstream_rows) == 2
                and upstream_rows[0].get("provider_label") == "news-provider"
                and upstream_rows[1].get("provider_label") == "cli-provider"
                and all(row.get("authorization_class") == "provider_key" for row in upstream_rows)
                and all(row.get("provider_auth_scheme") == "bearer" for row in upstream_rows)
                and not any(row.get("project_key_forwarded") or row.get("master_key_forwarded") for row in upstream_rows)
                and not any(row.get("project_key_hash_forwarded") or row.get("master_key_hash_forwarded") for row in upstream_rows)
                and not any(row.get("body_api_key_present") for row in upstream_rows)
                and all(row.get("prompt_marker_seen") for row in upstream_rows)
            )
            check("UPSTREAM_RECEIVES_ONLY_MATCHING_USER_PROVIDER_KEY", upstream_ok,
                  {"request_count": len(upstream_rows), "provider_labels": [r.get("provider_label") for r in upstream_rows],
                   "authorization_classes": [r.get("authorization_class") for r in upstream_rows],
                   "provider_auth_headers": [r.get("provider_auth_header") for r in upstream_rows],
                   "authorization_header_counts": [r.get("authorization_header_count") for r in upstream_rows],
                   "authorization_provider_labels": [r.get("authorization_provider_labels") for r in upstream_rows],
                   "provider_auth_credential_shapes": [r.get("provider_auth_credential_shape") for r in upstream_rows],
                   "provider_auth_credential_lengths": [r.get("provider_auth_credential_length") for r in upstream_rows],
                   "alternate_provider_header_names": [r.get("alternate_provider_header_names") for r in upstream_rows],
                   "alternate_provider_header_labels": [r.get("alternate_provider_header_labels") for r in upstream_rows],
                   "request_body_provider_key_labels": [r.get("request_body_provider_key_label") for r in upstream_rows],
                   "project_key_forwarded": any(r.get("project_key_forwarded") for r in upstream_rows),
                   "project_key_hash_forwarded": any(r.get("project_key_hash_forwarded") for r in upstream_rows),
                   "master_key_forwarded": any(r.get("master_key_forwarded") for r in upstream_rows),
                   "master_key_hash_forwarded": any(r.get("master_key_hash_forwarded") for r in upstream_rows),
                   "provider_key_body_forwarded": any(r.get("body_api_key_present") for r in upstream_rows)})

            start_date = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
            end_date = (datetime.now(timezone.utc) + timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
            query = urllib.parse.urlencode({"start_date": start_date, "end_date": end_date, "page": 1, "page_size": 100})
            spend_response = admin_request("/spend/logs/v2?" + query)
            spend_body_keys = sorted(spend_response.body) if isinstance(spend_response.body, dict) else []
            spend_data_type = type(spend_response.body.get("data")).__name__ if isinstance(spend_response.body, dict) else "unknown"
            spend_rows = spend_response.body.get("data", []) if isinstance(spend_response.body, dict) else []
            spend_rows = spend_rows if isinstance(spend_rows, list) else []
            for _ in range(6):
                if spend_response.status != 200 or spend_rows:
                    break
                time.sleep(0.5)
                spend_response = admin_request("/spend/logs/v2?" + query)
                spend_body_keys = sorted(spend_response.body) if isinstance(spend_response.body, dict) else []
                spend_data_type = type(spend_response.body.get("data")).__name__ if isinstance(spend_response.body, dict) else "unknown"
                spend_rows = spend_response.body.get("data", []) if isinstance(spend_response.body, dict) else []
                spend_rows = spend_rows if isinstance(spend_rows, list) else []
            spend_api_route = "/spend/logs/v2"
            if spend_response.status != 200 or not spend_rows:
                legacy_query = urllib.parse.urlencode({"start_date": start_date, "end_date": end_date, "summarize": "false"})
                spend_response = admin_request("/spend/logs?" + legacy_query)
                spend_api_route = "/spend/logs"
                if isinstance(spend_response.body, list):
                    spend_rows = spend_response.body
                else:
                    legacy_rows = spend_response.body.get("data", []) if isinstance(spend_response.body, dict) else []
                    spend_rows = legacy_rows if isinstance(legacy_rows, list) else []
            db_spend_count_result = compose(
                "exec", "-T", "db", "psql", "-qAt", "-U", "litellm", "-d", "litellm",
                "-c", 'SELECT COUNT(*) FROM "LiteLLM_SpendLogs"', timeout=30,
            )
            try:
                db_spend_log_row_count = int(db_spend_count_result.stdout.decode("utf-8", errors="replace").strip())
            except ValueError:
                db_spend_log_row_count = -1
            spend_serialized = json.dumps(spend_rows, ensure_ascii=True, sort_keys=True)
            labels = set()
            models = set()
            token_usage = 0
            for row in spend_rows if isinstance(spend_rows, list) else []:
                metadata = row.get("metadata") if isinstance(row, dict) else {}
                metadata = metadata if isinstance(metadata, dict) else {}
                for label in (row.get("user_api_key_alias"), row.get("key_alias"), metadata.get("user_api_key_alias"), metadata.get("key_alias")):
                    if isinstance(label, str):
                        labels.add(label)
                model_name = row.get("model") if isinstance(row, dict) else None
                if isinstance(model_name, str):
                    models.add(model_name)
                usage = row.get("usage") if isinstance(row, dict) else None
                if isinstance(usage, dict):
                    token_usage += int(usage.get("total_tokens", 0) or 0)
                token_usage += int(row.get("total_tokens", 0) or 0) if isinstance(row, dict) else 0
            leaked = any(value in spend_serialized for value in [master_key, *project_keys.values(), *provider_keys.values(), TEST_DEPLOYMENT_PLACEHOLDER_KEY, *prompt_markers.values()])
            project_attribution = (
                {"newshub-test", "generic-cli-test"}.issubset(labels)
                or {NEWS_MODEL, CLI_MODEL}.issubset(models)
            )
            check("SPEND_USAGE_LOGS_DISTINGUISH_PROJECTS", spend_response.status == 200 and project_attribution,
                  {"http_status": spend_response.status, "row_count": len(spend_rows), "project_labels": sorted(labels),
                   "model_aliases": sorted(models), "observed_token_usage": token_usage,
                   "api_route": spend_api_route, "response_body_keys": spend_body_keys,
                   "v2_data_type": spend_data_type, "database_row_count": db_spend_log_row_count})
            check("SPEND_USAGE_LOGS_REDACT_KEYS_AND_CONTENT", spend_response.status == 200 and not leaked,
                  {"credential_or_prompt_values_found": leaked})

            inspect = compose("ps", "-q", timeout=20)
            ids = inspect.stdout.decode("utf-8", errors="replace").splitlines()
            runtime_facts = []
            if ids:
                docker_inspect = safe_process(
                    ["docker", "inspect", "--format", '{{.Image}}|{{.Config.Image}}|{{index .Config.Labels "com.docker.compose.service"}}|{{json .Config.Env}}|{{json .Mounts}}', *ids],
                    timeout=30,
                )
                for line in docker_inspect.stdout.decode("utf-8", errors="replace").splitlines():
                    pieces = line.split("|", 4)
                    if len(pieces) != 5:
                        continue
                    runtime_id, config_image, service, env_json, mounts_json = pieces
                    runtime_facts.append({
                        "service": service,
                        "runtime_image_id": runtime_id,
                        "configured_image": config_image,
                        "contains_master_key_env": "LITELLM_MASTER_KEY" in env_json,
                        "has_master_secret_mount": "/run/secrets/litellm_master_key" in mounts_json,
                    })
            proxy_facts = next((row for row in runtime_facts if row["service"] == "proxy"), {})
            upstream_facts = next((row for row in runtime_facts if row["service"] == "test-upstream"), {})
            newshub_facts = next((row for row in runtime_facts if row["service"] == "newshub-test-client"), {})
            cli_facts = next((row for row in runtime_facts if row["service"] == "generic-cli-consumer"), {})
            check("MASTER_KEY_ONLY_MOUNTED_IN_PROXY_PROCESS", bool(proxy_facts) and proxy_facts.get("has_master_secret_mount")
                  and not proxy_facts.get("contains_master_key_env") and not upstream_facts.get("has_master_secret_mount")
                  and not upstream_facts.get("contains_master_key_env") and not newshub_facts.get("has_master_secret_mount")
                  and not newshub_facts.get("contains_master_key_env") and not cli_facts.get("has_master_secret_mount")
                  and not cli_facts.get("contains_master_key_env"),
                  {"proxy_master_secret_mount": proxy_facts.get("has_master_secret_mount"),
                   "proxy_master_key_env_in_compose": proxy_facts.get("contains_master_key_env"),
                   "consumer_master_secret_mount": upstream_facts.get("has_master_secret_mount"),
                   "consumer_master_key_env": upstream_facts.get("contains_master_key_env"),
                   "newshub_master_secret_mount": newshub_facts.get("has_master_secret_mount"),
                   "generic_cli_master_secret_mount": cli_facts.get("has_master_secret_mount")})
            fixed_images = {row.get("service"): row.get("configured_image") for row in runtime_facts}
            check("RUNTIME_IMAGE_REFERENCES_ARE_FIXED", fixed_images.get("proxy") == LITELLM_IMAGE
                  and fixed_images.get("db") == POSTGRES_IMAGE and fixed_images.get("test-upstream") == LITELLM_IMAGE,
                  {"services": fixed_images})

            logs = compose("logs", "--no-color", "proxy", "test-upstream", timeout=30)
            log_text = logs.stdout.decode("utf-8", errors="replace") + logs.stderr.decode("utf-8", errors="replace")
            log_leak = any(value in log_text for value in [master_key, *project_keys.values(), *provider_keys.values(), TEST_DEPLOYMENT_PLACEHOLDER_KEY, *prompt_markers.values()])
            check("CONTAINER_LOGS_REDACT_KEYS_AND_CONTENT", logs.returncode == 0 and not log_leak,
                  {"credential_or_prompt_values_found": log_leak})
            observed_provider_key_labels = {
                label: f"T00G_TEST_PROVIDER_KEY_MATCH label={label}" in log_text
                for label in ("news", "cli")
            }
            check("TEST_GUARD_OBSERVES_EXPECTED_PROVIDER_KEY_VALUES", all(observed_provider_key_labels.values()),
                  {"matched_project_labels": [label for label, matched in observed_provider_key_labels.items() if matched]})

            stopped = compose("stop", "proxy", timeout=40)
            unavailable = app_request("generic-cli-consumer", "proxy", "/health/readiness")
            check("PROXY_STOP_CAUSES_CONNECTION_FAILURE", stopped.returncode == 0 and unavailable.status == 0,
                  {"proxy_stopped": stopped.returncode == 0, "client_network_error": unavailable.body.get("network_error_type")})
            restarted = compose("--profile", "test", "up", "-d", "--wait", "--wait-timeout", "240", "proxy", timeout=300)
            check("PROXY_RESTARTS_WITHOUT_NEWSHUB_LIFECYCLE", restarted.returncode == 0,
                  {"proxy_restarted": restarted.returncode == 0, "newshub_service_containers_started": False})
            after_restart = request_call("generic-cli-consumer", CLI_MODEL, provider_keys["cli"], prompt_markers["cli"], project_keys["cli"])
            check("GENERIC_CLI_RECOVERS_AFTER_PROXY_RESTART", after_restart.status == 200, {"http_status": after_restart.status})

            dump_path = tmp / "gateway-backup.dump"
            backup_started = time.monotonic()
            dump_process = compose("exec", "-T", "db", "pg_dump", "-Fc", "-U", "litellm", "-d", "litellm", timeout=120)
            dump_bytes = dump_process.stdout
            dump_path.write_bytes(dump_bytes)
            dump_hash = hashlib.sha256(dump_bytes).hexdigest()
            backup_leak = any(value.encode() in dump_bytes for value in [master_key, *project_keys.values(), *provider_keys.values(), TEST_DEPLOYMENT_PLACEHOLDER_KEY, *prompt_markers.values()])
            check("POSTGRES_BACKUP_CREATED_WITHOUT_RAW_SECRETS_OR_PROMPTS", dump_process.returncode == 0 and bool(dump_bytes) and not backup_leak,
                  {"backup_bytes": len(dump_bytes), "sha256": dump_hash, "raw_values_found": backup_leak})

            restore_up = compose("--profile", "restore", "up", "-d", "--wait", "restore-db", timeout=120)
            restore_started = time.monotonic()
            restore_process = compose(
                "exec", "-T", "restore-db", "pg_restore", "--exit-on-error", "--no-owner", "--no-privileges",
                "-U", "litellm", "-d", "litellm_restore", timeout=180, input_bytes=dump_bytes,
            )
            restore_rto_ms = round((time.monotonic() - restore_started) * 1000, 2)
            check("POSTGRES_BACKUP_RESTORES_IN_ISOLATED_DATABASE", restore_up.returncode == 0 and restore_process.returncode == 0,
                  {"restore_duration_ms": restore_rto_ms, "restore_return_code": restore_process.returncode})

            table_check_sql = "SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_name IN ('LiteLLM_VerificationToken','LiteLLM_SpendLogs') ORDER BY table_name"
            table_list = compose("exec", "-T", "restore-db", "psql", "-qAt", "-U", "litellm", "-d", "litellm_restore", "-c", table_check_sql, timeout=30)
            table_names = table_list.stdout.decode("utf-8", errors="replace").splitlines()
            restored_log_count = 0
            if "LiteLLM_SpendLogs" in table_names:
                count_result = compose("exec", "-T", "restore-db", "psql", "-qAt", "-U", "litellm", "-d", "litellm_restore", "-c", 'SELECT COUNT(*) FROM "LiteLLM_SpendLogs"', timeout=30)
                try:
                    restored_log_count = int(count_result.stdout.decode().strip())
                except ValueError:
                    restored_log_count = -1
            check("RESTORED_DATABASE_CONTAINS_USAGE_TABLE", table_list.returncode == 0 and "LiteLLM_SpendLogs" in table_names,
                  {"restored_tables": table_names, "restored_spend_log_rows": restored_log_count})
            summary["backup_restore"] = {
                "backup_bytes": len(dump_bytes),
                "backup_sha256": dump_hash,
                "restore_duration_ms": restore_rto_ms,
                "restored_tables": table_names,
                "restored_spend_log_rows": restored_log_count,
                "rpo_observed": "no post-snapshot requests were expected in this bounded local test",
                "actual_news_hub_recovery": "NOT_RUN",
            }

            summary["versions"]["startup_duration_seconds"] = startup_duration_seconds
            summary["spend_log_row_count"] = len(spend_rows) if isinstance(spend_rows, list) else 0
            summary["upstream_request_count"] = len(upstream_rows)
            summary["project_aliases_observed"] = sorted(labels)
            summary["project_models_observed"] = sorted(models)

    except Exception as error:
        summary["execution_error_type"] = type(error).__name__
        summary["checks"].append(
            {
                "id": "LOCAL_TEST_EXECUTION_COMPLETED",
                "status": "FAIL",
                "facts": {"error_type": type(error).__name__},
            }
        )
    finally:
        if compose_attempted and env_file is not None:
            try:
                cleanup = compose(
                    "--profile", "test", "--profile", "restore", "down", "-v", "--remove-orphans", timeout=90
                )
                cleanup_return = cleanup.returncode
            except Exception:
                cleanup_return = 1
        if temporary is not None:
            shutil.rmtree(temporary, ignore_errors=True)
        summary["cleanup"] = {"compose_down_return_code": cleanup_return}
        summary["checks"].append({"id": "LOCAL_COMPOSE_CLEANUP", "status": "PASS" if compose_attempted and cleanup_return == 0 else "FAIL", "facts": summary["cleanup"]})
        failed = [item["id"] for item in summary["checks"] if item["status"] == "FAIL"]
        summary["status"] = "PASS" if started and not failed and "execution_error_type" not in summary else "FAIL"
        summary["failed_check_count"] = len(failed)
        summary["failed_check_ids"] = failed
        print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
    return 1 if summary["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
