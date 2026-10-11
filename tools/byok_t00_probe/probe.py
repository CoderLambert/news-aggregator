#!/usr/bin/env python3
"""Run the isolated T00 SDK/Proxy probe; this never contacts a real provider."""

from __future__ import annotations

import importlib.metadata
import json
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import httpx2
from anthropic import Anthropic
from openai import OpenAI


TOOL_DIR = Path(__file__).resolve().parent
COMPOSE_FILE = TOOL_DIR / "compose.yaml"
MASTER_KEY = "sk-t00-master-synthetic"
PROVIDER_KEYS = {
    "tenant-a": "sk-t00-provider-a-synthetic",
    "tenant-b": "sk-t00-provider-b-synthetic",
}
OPENAI_HEADERS = {"x-probe-source": "SDK_LOCAL"}
URL_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def docker_base(project: str) -> list[str]:
    docker = shutil.which("docker")
    if docker is None:
        raise RuntimeError("docker CLI not found")
    return [docker, "--context", "default", "compose", "--project-name", project, "-f", str(COMPOSE_FILE)]


def compose(project: str, *args: str, timeout: int = 180) -> str:
    result = subprocess.run(
        [*docker_base(project), *args],
        cwd=TOOL_DIR,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"docker compose exited {result.returncode}")
    return result.stdout


def inspect_ip(project: str, service: str) -> str:
    container = f"{project}-{service}-1"
    docker = shutil.which("docker")
    if docker is None:
        raise RuntimeError("docker CLI not found")
    result = subprocess.run(
        [docker, "--context", "default", "inspect", "--format", "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}", container],
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )
    address = result.stdout.strip()
    if result.returncode != 0 or not address:
        raise RuntimeError(f"could not inspect {service} container address")
    return address


def docker_versions(project: str) -> dict[str, str]:
    docker = shutil.which("docker")
    if docker is None:
        raise RuntimeError("docker CLI not found")
    server = subprocess.run(
        [docker, "--context", "default", "version", "--format", "{{.Server.Version}}"],
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )
    compose_version = subprocess.run(
        [docker, "--context", "default", "compose", "version", "--short"],
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )
    proxy_version = subprocess.run(
        [docker, "--context", "default", "exec", f"{project}-proxy-1", "python", "-c", "import importlib.metadata as m; print(m.version('litellm'))"],
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )
    if server.returncode or compose_version.returncode or proxy_version.returncode:
        raise RuntimeError("could not read local Docker/Proxy versions")
    return {
        "docker_server": server.stdout.strip(),
        "docker_compose": compose_version.stdout.strip(),
        "litellm": proxy_version.stdout.strip(),
    }


def request_json(url: str, payload: dict | None = None, headers: dict[str, str] | None = None, timeout: int = 20) -> dict:
    data = None if payload is None else json.dumps(payload).encode()
    request_headers = dict(headers or {})
    if data is not None:
        request_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=request_headers)
    try:
        with URL_OPENER.open(request, timeout=timeout) as response:
            decoded = json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code}") from None
    if not isinstance(decoded, dict):
        raise RuntimeError("unexpected JSON response")
    return decoded


def make_virtual_key(proxy_url: str, alias: str, model: str) -> str:
    result = request_json(
        proxy_url + "/key/generate",
        {"models": [model], "metadata": {"key_alias": alias}},
        {"Authorization": f"Bearer {MASTER_KEY}"},
    )
    key = result.get("key")
    if not isinstance(key, str) or not key.startswith("sk-"):
        raise RuntimeError("unexpected virtual-key response shape")
    return key


def sdk_versions() -> dict[str, str]:
    return {
        "python": sys.version.split()[0],
        "openai": importlib.metadata.version("openai"),
        "anthropic": importlib.metadata.version("anthropic"),
        "httpx2": importlib.metadata.version("httpx2"),
    }


def sdk_local(upstream_url: str) -> dict:
    """Direct SDK -> controlled HTTP upstream; does not involve LiteLLM Proxy."""
    results: dict[str, dict] = {}
    base = upstream_url + "/v1"
    for protocol in ("chat", "responses"):
        with OpenAI(
            api_key=PROVIDER_KEYS["tenant-a"],
            base_url=base,
            default_headers={**OPENAI_HEADERS, "x-api-key": PROVIDER_KEYS["tenant-a"]},
            max_retries=0,
            http_client=httpx2.Client(trust_env=False, timeout=30.0),
        ) as client:
            if protocol == "chat":
                complete_events = 0
                finish_reasons: list[str] = []
                with client.chat.completions.create(
                    model="test-model",
                    messages=[{"role": "user", "content": "T00_NORMAL"}],
                    stream=True,
                ) as stream:
                    for chunk in stream:
                        complete_events += 1
                        finish_reasons.extend(
                            choice.finish_reason
                            for choice in chunk.choices
                            if choice.finish_reason is not None
                        )
                eof_events = 0
                eof_finishes: list[str] = []
                with client.chat.completions.create(
                    model="test-model",
                    messages=[{"role": "user", "content": "T00_EOF_NO_TERMINAL"}],
                    stream=True,
                ) as stream:
                    for chunk in stream:
                        eof_events += 1
                        eof_finishes.extend(
                            choice.finish_reason
                            for choice in chunk.choices
                            if choice.finish_reason is not None
                        )
                results[protocol] = {
                    "complete_events": complete_events,
                    "complete_finish_reasons": finish_reasons,
                    "eof_events": eof_events,
                    "eof_finish_reasons": eof_finishes,
                }
            else:
                complete_events: list[str] = []
                with client.responses.create(model="test-model", input="T00_NORMAL", stream=True) as stream:
                    complete_events = [event.type for event in stream]
                eof_events: list[str] = []
                with client.responses.create(model="test-model", input="T00_EOF_NO_TERMINAL", stream=True) as stream:
                    eof_events = [event.type for event in stream]
                results[protocol] = {
                    "complete_events": complete_events,
                    "complete_has_terminal": "response.completed" in complete_events,
                    "eof_events": eof_events,
                    "eof_has_terminal": "response.completed" in eof_events,
                }

    with Anthropic(
        api_key=PROVIDER_KEYS["tenant-a"],
        base_url=upstream_url,
        default_headers={"x-probe-source": "SDK_LOCAL"},
        max_retries=0,
        http_client=httpx2.Client(trust_env=False, timeout=30.0),
    ) as client:
        complete_events: list[str] = []
        with client.messages.stream(
            model="test-model", max_tokens=40, messages=[{"role": "user", "content": "T00_NORMAL"}]
        ) as stream:
            complete_events = [event.type for event in stream]
            complete_final = stream.get_final_message()
        eof_events: list[str] = []
        with client.messages.stream(
            model="test-model", max_tokens=40, messages=[{"role": "user", "content": "T00_EOF_NO_TERMINAL"}]
        ) as stream:
            eof_events = [event.type for event in stream]
            eof_final = stream.get_final_message()
        results["messages"] = {
            "complete_events": complete_events,
            "complete_stop_reason": complete_final.stop_reason,
            "eof_events": eof_events,
            "eof_stop_reason": None if eof_final is None else eof_final.stop_reason,
        }
    return results


def proxy_local(proxy_url: str, upstream_url: str) -> dict:
    """SDK -> pinned LiteLLM Proxy -> controlled HTTP upstream."""
    key_a = make_virtual_key(proxy_url, "tenant-a", "t00-chat-a")
    key_b = make_virtual_key(proxy_url, "tenant-b", "t00-chat-b")
    client_a = OpenAI(
        api_key=key_a,
        base_url=proxy_url + "/v1",
        default_headers={"x-api-key": PROVIDER_KEYS["tenant-a"], "x-probe-source": "PROXY_LOCAL"},
        max_retries=0,
        http_client=httpx2.Client(trust_env=False, timeout=30.0),
    )
    client_b = OpenAI(
        api_key=key_b,
        base_url=proxy_url + "/v1",
        default_headers={"x-api-key": PROVIDER_KEYS["tenant-b"], "x-probe-source": "PROXY_LOCAL"},
        max_retries=0,
        http_client=httpx2.Client(trust_env=False, timeout=30.0),
    )
    try:
        result_a = client_a.chat.completions.create(model="t00-chat-a", messages=[{"role": "user", "content": "T00_NORMAL"}])
        result_b = client_b.chat.completions.create(model="t00-chat-b", messages=[{"role": "user", "content": "T00_NORMAL"}])
        before_cross = len(request_json(upstream_url + "/stats").get("records", []))
        cross_model_status = None
        try:
            client_a.chat.completions.create(model="t00-chat-b", messages=[{"role": "user", "content": "T00_CROSS_MODEL"}])
        except Exception as exc:
            cross_model_status = getattr(exc, "status_code", None)
        after_cross = len(request_json(upstream_url + "/stats").get("records", []))

        wrong_project = OpenAI(
            api_key="sk-t00-wrong-project-key-synthetic",
            base_url=proxy_url + "/v1",
            default_headers={"x-api-key": PROVIDER_KEYS["tenant-a"], "x-probe-source": "PROXY_LOCAL"},
            max_retries=0,
            http_client=httpx2.Client(trust_env=False, timeout=30.0),
        )
        before_wrong_project = after_cross
        wrong_project_status = None
        try:
            wrong_project.chat.completions.create(model="t00-chat-a", messages=[{"role": "user", "content": "T00_WRONG_PROJECT_KEY"}])
        except Exception as exc:
            wrong_project_status = getattr(exc, "status_code", None)
        finally:
            wrong_project.close()
        after_wrong_project = len(request_json(upstream_url + "/stats").get("records", []))

        eof_count = 0
        eof_finish_reasons: list[str] = []
        with client_a.chat.completions.create(
            model="t00-chat-a",
            messages=[{"role": "user", "content": "T00_EOF_NO_TERMINAL"}],
            stream=True,
        ) as stream:
            for chunk in stream:
                eof_count += 1
                eof_finish_reasons.extend(
                    choice.finish_reason
                    for choice in chunk.choices
                    if choice.finish_reason is not None
                )

        # Missing provider credentials must fail at the synthetic upstream, with no default key.
        missing_provider = OpenAI(
            api_key=key_a,
            base_url=proxy_url + "/v1",
            default_headers={"x-probe-source": "PROXY_LOCAL"},
            max_retries=0,
            http_client=httpx2.Client(trust_env=False, timeout=30.0),
        )
        before_missing_provider = len(request_json(upstream_url + "/stats").get("records", []))
        missing_provider_status = None
        try:
            missing_provider.chat.completions.create(model="t00-chat-a", messages=[{"role": "user", "content": "T00_NO_PROVIDER_KEY"}])
        except Exception as exc:
            missing_provider_status = getattr(exc, "status_code", None)
        finally:
            missing_provider.close()

        upstream = request_json(upstream_url + "/stats")
        proxy_records = [row for row in upstream.get("records", []) if row.get("source") == "PROXY_LOCAL"]
        eof_record = next(
            (row for row in reversed(proxy_records) if row.get("scenario") == "eof-no-terminal"),
            None,
        )
        missing_key_record = next(
            (row for row in reversed(upstream.get("records", [])) if row.get("tenant") == "rejected" and row.get("scenario") == "normal"),
            None,
        )
        accepted_counts: dict[str, int] = {}
        for row in proxy_records:
            tenant = row.get("tenant")
            if tenant in PROVIDER_KEYS and row.get("scenario") == "normal":
                accepted_counts[tenant] = accepted_counts.get(tenant, 0) + 1
        cross_model_upstream_delta = after_cross - before_cross
        wrong_project_upstream_delta = after_wrong_project - before_wrong_project
        missing_provider_upstream_delta = len(upstream.get("records", [])) - before_missing_provider
        eof_attempts = sum(
            1 for row in proxy_records
            if row.get("scenario") == "eof-no-terminal"
        )

        return {
            "tenant_a_finish": result_a.choices[0].finish_reason,
            "tenant_b_finish": result_b.choices[0].finish_reason,
            "allowed_model_upstream_counts": accepted_counts,
            "cross_model_status": cross_model_status,
            "cross_model_upstream_delta": cross_model_upstream_delta,
            "wrong_project_key_status": wrong_project_status,
            "wrong_project_upstream_delta": wrong_project_upstream_delta,
            "missing_provider_status": missing_provider_status,
            "missing_provider_upstream_delta": missing_provider_upstream_delta,
            "missing_provider_upstream_tenant": None if missing_key_record is None else missing_key_record.get("tenant"),
            "missing_provider_header_present": None if missing_key_record is None else missing_key_record.get("provider_header_present"),
            "proxy_eof_upstream_terminal": None if eof_record is None else eof_record.get("upstream_terminal"),
            "proxy_eof_upstream_tenant": None if eof_record is None else eof_record.get("tenant"),
            "proxy_eof_sdk_event_count": eof_count,
            "proxy_eof_sdk_finish_reasons": eof_finish_reasons,
            "proxy_eof_upstream_attempts": eof_attempts,
        }
    finally:
        client_a.close()
        client_b.close()


def main() -> int:
    project = "byok-t00-probe-" + uuid.uuid4().hex[:8]
    result: dict = {"status": "BLOCKED", "provider_real": "NOT_RUN", "sdk_versions": sdk_versions()}
    try:
        compose(project, "up", "-d", "--wait", "--wait-timeout", "180", timeout=210)
        proxy_ip = inspect_ip(project, "proxy")
        upstream_ip = inspect_ip(project, "upstream")
        proxy_url = f"http://{proxy_ip}:4000"
        upstream_url = f"http://{upstream_ip}:8080"
        result["images"] = {
            "litellm": "ghcr.io/berriai/litellm@sha256:3d88bd757134a00e8c00237b85a021ab1f6d54abb9c1df750f411dbe7256a500",
            "postgres": "postgres@sha256:721873c34ceb9f8d8fc265984940dc982404c105f19ad51be9fdc5970a6080ea",
        }
        result["runtime_versions"] = docker_versions(project)
        result["sdk_local"] = sdk_local(upstream_url)
        result["proxy_local"] = proxy_local(proxy_url, upstream_url)
        failed_eof_check = (
            result["proxy_local"]["proxy_eof_upstream_terminal"] == "normal_eof_without_protocol_terminal"
            and "stop" in result["proxy_local"]["proxy_eof_sdk_finish_reasons"]
        )
        result["proxy_local"]["chat_eof_integrity"] = "BLOCKED" if failed_eof_check else "NOT_CONFIRMED"
        if not failed_eof_check:
            result["proxy_local"]["chat_eof_integrity"] = "REQUIRES_REVIEW"
    except Exception as exc:
        result["probe_error"] = type(exc).__name__
        return_code = 1
    else:
        # The current CLI intentionally covers only a subset of T00. Even when
        # this specific EOF regression is absent, it cannot claim the full card.
        return_code = 2
    finally:
        try:
            compose(project, "down", "--volumes", "--remove-orphans", timeout=60)
            result["temporary_containers_cleaned"] = True
        except Exception:
            result["temporary_containers_cleaned"] = False
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
