"""Independent test-only HTTP CLI client on the internal gateway network."""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request


TARGETS = {
    "proxy": "http://proxy:4000",
    "test-upstream": "http://test-upstream:8080",
}
URL_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def main() -> None:
    try:
        spec = json.load(sys.stdin)
        target = TARGETS[spec["target"]]
        method = spec.get("method", "GET")
        path = spec["path"]
        payload = spec.get("payload")
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"
        else:
            data = None
        token = spec.get("bearer")
        if isinstance(token, str):
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(target + path, data=data, headers=headers, method=method)
        try:
            with URL_OPENER.open(request, timeout=10) as response:
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
    except urllib.error.URLError as error:
        result = {"status": 0, "network_error_type": type(error.reason).__name__}
    except Exception as error:
        result = {"status": 0, "client_error_type": type(error).__name__}
    print(json.dumps(result, separators=(",", ":"), ensure_ascii=True))


if __name__ == "__main__":
    main()
