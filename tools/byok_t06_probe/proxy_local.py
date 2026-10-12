#!/usr/bin/env python3
"""Exercise T06 through the pinned T00 LiteLLM proxy and synthetic upstream.

This probe uses generated/synthetic credentials only. It writes no prompt,
provider key, generated virtual key, or response content to stdout or disk.
The caller starts and removes its own T00 Compose project.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import urllib.request
from pathlib import Path
from types import SimpleNamespace

from django import setup

MASTER_KEY = "sk-t00-master-synthetic"
PROVIDER_KEY = "sk-t00-provider-a-synthetic"
MODEL_ALIAS = "t00-chat"
CHUNK_BYTES = 512


def _docker(args: list[str]) -> str:
    return subprocess.check_output(["docker", *args], text=True, stderr=subprocess.DEVNULL).strip()


def _container_ip(project: str, compose_file: Path, service: str) -> str:
    container_id = _docker([
        "compose", "--project-name", project, "-f", str(compose_file),
        "ps", "-q", service,
    ]).splitlines()[0]
    address = _docker([
        "inspect", "--format",
        "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}", container_id,
    ])
    if not address:
        raise RuntimeError(f"container address is unavailable: {service}")
    return address


def _request_json(url: str, payload: dict, headers: dict[str, str] | None = None) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=10) as response:
        body = json.load(response)
    if not isinstance(body, dict):
        raise RuntimeError("unexpected local fixture response")
    return body


def _get_json(url: str) -> dict:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=10) as response:
        body = json.load(response)
    if not isinstance(body, dict):
        raise RuntimeError("unexpected local fixture response")
    return body


def _records(upstream_url: str) -> list[dict]:
    records = _get_json(upstream_url + "/stats").get("records", [])
    if not isinstance(records, list):
        raise RuntimeError("unexpected local fixture record shape")
    return records


def _execution(proxy_url: str, project_key: str):
    from api.services.ai_translation import BYOKTranslationExecution

    return BYOKTranslationExecution(
        snapshot=SimpleNamespace(),
        gateway_url=proxy_url,
        project_key=project_key,
        provider_key=PROVIDER_KEY,
        model_alias=MODEL_ALIAS,
        model_source={"provider": "T00 synthetic", "model": MODEL_ALIAS},
        context_window_tokens=1_048_576,
        model_max_output_tokens=4_096,
    )


def run(compose_project: str, compose_file: Path) -> dict:
    from api.services import ai_translation
    from api.services.ai_translation import BYOKTranslationError, stream_byok_translation

    compose_file = compose_file.resolve()
    proxy_url = f"http://{_container_ip(compose_project, compose_file, 'proxy')}:4000"
    upstream_url = f"http://{_container_ip(compose_project, compose_file, 'upstream')}:8080"

    generated_key = _request_json(
        proxy_url + "/key/generate",
        {"models": [MODEL_ALIAS], "metadata": {"key_alias": "t06-proxy-local"}},
        {"Authorization": f"Bearer {MASTER_KEY}"},
    ).get("key")
    if not isinstance(generated_key, str) or not generated_key.startswith("sk-"):
        raise RuntimeError("synthetic virtual-key generation failed")
    _request_json(upstream_url + "/test/expectations", {
        "project_key_sha256": [hashlib.sha256(generated_key.encode("utf-8")).hexdigest()],
    })

    ai_translation.MAX_TRANSLATION_CHUNK_SOURCE_BYTES = CHUNK_BYTES
    execution = _execution(proxy_url, generated_key)
    code_block = "```python\nprint('sentinel')\n```"
    source = (
        "T00_T06_PROXY_LOCAL_A: This synthetic article paragraph crosses the chunk boundary safely. "
        * 72
    ) + "\n\n" + code_block + "\n\nT00_T06_PROXY_LOCAL_A: Final synthetic paragraph."

    before = len(_records(upstream_url))
    progress: list[str] = []
    result = stream_byok_translation(
        execution,
        source,
        on_delta=progress.append,
        execution_guard=lambda: None,
    )
    complete_records = _records(upstream_url)[before:]
    if len(complete_records) < 2:
        raise AssertionError("T06 did not dispatch multiple chunks")
    if any(
        record.get("protocol") != "responses"
        or record.get("upstream_terminal") != "response_completed"
        for record in complete_records
    ):
        raise AssertionError("a chunk lacked a completed Responses API terminal")
    if any(
        record.get("tenant") != "tenant-a" or record.get("project_key_match")
        for record in complete_records
    ):
        raise AssertionError("provider/project credential separation failed")
    if result.count(code_block) != 1 or "".join(progress) != result:
        raise AssertionError("code-fence preservation or merged progress failed")

    before_incomplete = len(_records(upstream_url))
    incomplete_error = None
    try:
        stream_byok_translation(
            execution,
            "T00_T06_PROXY_LOCAL_INCOMPLETE_A: synthetic incomplete response",
            on_delta=lambda _part: None,
            execution_guard=lambda: None,
        )
    except BYOKTranslationError as exc:
        incomplete_error = exc.code
    incomplete_records = _records(upstream_url)[before_incomplete:]
    if (
        incomplete_error != "incomplete_response"
        or len(incomplete_records) != 1
        or incomplete_records[0].get("upstream_terminal") != "response_incomplete"
    ):
        raise AssertionError("an incomplete provider terminal was not rejected without retry")
    if (
        incomplete_records[0].get("tenant") != "tenant-a"
        or incomplete_records[0].get("project_key_match")
    ):
        raise AssertionError("incomplete-path credential separation failed")

    return {
        "classification": "PROXY_LOCAL",
        "synthetic_upstream": True,
        "provider_real_requests": 0,
        "protocol": "openai_responses_streaming",
        "completed_chunks": len(complete_records),
        "provider_key_tenant": "tenant-a",
        "project_key_leak_upstream": False,
        "code_fence_passed_through_exactly": True,
        "progress_equals_merged_result": True,
        "incomplete_path_requests": len(incomplete_records),
        "incomplete_path_error": incomplete_error,
        "incomplete_retries": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compose-project", required=True)
    parser.add_argument("--compose-file", required=True, type=Path)
    args = parser.parse_args()
    setup()
    evidence = run(args.compose_project, args.compose_file)
    print(json.dumps(evidence, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
