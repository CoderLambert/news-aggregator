"""Local operator API helper for the isolated test profile only."""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request


URL_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
ALLOWED_PATHS = ("/key/generate", "/spend/logs/v2", "/spend/logs", "/model/info")


def main() -> None:
    try:
        spec = json.load(sys.stdin)
        path = spec["path"]
        if not isinstance(path, str) or not path.startswith(ALLOWED_PATHS):
            raise ValueError("operation_not_allowed")
        method = spec.get("method", "GET")
        payload = spec.get("payload")
        headers = {"Accept": "application/json", "Authorization": "Bearer " + open("/run/secrets/litellm_master_key", encoding="utf-8").read().strip()}
        if payload is not None:
            data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"
        else:
            data = None
        request = urllib.request.Request("http://127.0.0.1:4000" + path, data=data, headers=headers, method=method)
        try:
            with URL_OPENER.open(request, timeout=20) as response:
                status = response.status
                raw = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as error:
            status = error.code
            raw = error.read().decode("utf-8", errors="replace")
        body = {}
        try:
            decoded = json.loads(raw)
            if isinstance(decoded, (dict, list)):
                body = decoded
        except json.JSONDecodeError:
            body = {}
        result = {"status": status, "body": body, "raw": raw}
    except Exception as error:
        result = {"status": 0, "client_error_type": type(error).__name__}
    print(json.dumps(result, separators=(",", ":"), ensure_ascii=True))


if __name__ == "__main__":
    main()
