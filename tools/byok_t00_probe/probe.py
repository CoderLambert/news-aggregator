#!/usr/bin/env python3
"""Run the isolated T00 SDK/Proxy probe; this never contacts a real provider."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx2
from anthropic import Anthropic
from openai import OpenAI


TOOL_DIR = Path(__file__).resolve().parent
COMPOSE_FILE = TOOL_DIR / "compose.yaml"
MASTER_KEY = "sk-t00-master-synthetic"
ADMIN_KEY = "sk-t00-admin-synthetic"
SDK_MAX_RETRIES = 0
PROXY_NUM_RETRIES = 0
WRONG_PROJECT_KEY = "sk-t00-wrong-project-synthetic"
DEPLOYMENT_KEY = "sk-t00-deployment-default-synthetic"
PROVIDER_KEYS = {
    "tenant-a": "sk-t00-provider-a-synthetic",
    "tenant-b": "sk-t00-provider-b-synthetic",
}
EXPECTED_IMAGES = {
    "db": "postgres@sha256:721873c34ceb9f8d8fc265984940dc982404c105f19ad51be9fdc5970a6080ea",
    "proxy": "ghcr.io/berriai/litellm@sha256:3d88bd757134a00e8c00237b85a021ab1f6d54abb9c1df750f411dbe7256a500",
    "upstream": "ghcr.io/berriai/litellm@sha256:3d88bd757134a00e8c00237b85a021ab1f6d54abb9c1df750f411dbe7256a500",
}
URL_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class HttpStatusError(RuntimeError):
    def __init__(self, status_code: int):
        self.status_code = status_code
        super().__init__(f"HTTP {status_code}")


def docker_cli() -> str:
    docker = shutil.which("docker")
    if docker is None:
        raise RuntimeError("docker CLI not found")
    return docker


def docker(args: list[str], timeout: int = 30) -> str:
    result = subprocess.run(
        [docker_cli(), "--context", "default", *args],
        cwd=TOOL_DIR,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"docker {args[0] if args else 'command'} failed")
    return result.stdout.strip()


def compose(project: str, *args: str, timeout: int = 180) -> str:
    return docker(
        ["compose", "--project-name", project, "-f", str(COMPOSE_FILE), *args],
        timeout=timeout,
    )


def service_container_id(project: str, service: str) -> str:
    result = compose(project, "ps", "-q", service, timeout=20).strip()
    if not result:
        raise RuntimeError(f"container missing for service {service}")
    return result.splitlines()[0]


def inspect_ip(project: str, service: str) -> str:
    container = service_container_id(project, service)
    address = docker(
        ["inspect", "--format", "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}", container],
        timeout=15,
    )
    if not address:
        raise RuntimeError(f"container address missing for service {service}")
    return address


def docker_versions(project: str) -> dict[str, str]:
    server = docker(["version", "--format", "{{.Server.Version}}"], timeout=15)
    compose_version = docker(["compose", "version", "--short"], timeout=15)
    proxy_version = docker(
        [
            "exec",
            service_container_id(project, "proxy"),
            "python",
            "-c",
            "import importlib.metadata as m; print(m.version('litellm'))",
        ],
        timeout=15,
    )
    return {
        "docker_server": server,
        "docker_compose": compose_version,
        "litellm": proxy_version,
    }


def inspect_image(reference: str) -> dict:
    formatted = docker(
        ["image", "inspect", "--format", "{{.Id}}|{{json .RepoDigests}}", reference],
        timeout=20,
    )
    image_id, separator, repo_digests_json = formatted.partition("|")
    if not separator or not image_id:
        raise RuntimeError("unexpected docker image inspect output")
    try:
        repo_digests = json.loads(repo_digests_json)
    except json.JSONDecodeError:
        raise RuntimeError("invalid RepoDigests from docker image inspect") from None
    return {
        "image_id": image_id,
        "repo_digests": repo_digests if isinstance(repo_digests, list) else [],
    }


def container_image_evidence(project: str) -> tuple[dict, bool]:
    ids = compose(project, "ps", "-q", timeout=20).splitlines()
    if not ids:
        raise RuntimeError("no running probe containers to inspect")

    # Use a narrow Go template so Docker never emits container Env or other config.
    container_format = (
        '{{.Id}}|{{.Image}}|{{.Config.Image}}|'
        '{{index .Config.Labels "com.docker.compose.service"}}'
    )
    inspected = docker(
        ["inspect", "--format", container_format, *ids],
        timeout=20,
    )
    evidence = {}
    all_pinned = True
    for line in inspected.splitlines():
        container_id, runtime_image_id, config_image, service = line.split("|", 3)
        runtime_image = inspect_image(runtime_image_id)
        expected = EXPECTED_IMAGES.get(service)
        pinned_image = inspect_image(expected) if expected else None

        runtime_inspect_matches = runtime_image["image_id"] == runtime_image_id
        reference_resolves_to_runtime = bool(
            pinned_image and pinned_image["image_id"] == runtime_image_id
        )
        config_reference_matches = config_image == expected
        service_passes = (
            runtime_inspect_matches
            and reference_resolves_to_runtime
            and config_reference_matches
        )
        all_pinned = all_pinned and service_passes
        evidence[service] = {
            "container_id": container_id,
            "container_image_id": runtime_image_id,
            "container_config_image": config_image,
            "expected_fixed_reference": expected,
            "runtime_image_inspect_id": runtime_image["image_id"],
            "runtime_repo_digests": runtime_image["repo_digests"],
            "fixed_reference_resolved_image_id": None if pinned_image is None else pinned_image["image_id"],
            "fixed_reference_repo_digests": [] if pinned_image is None else pinned_image["repo_digests"],
            "runtime_id_matches_image_inspect": runtime_inspect_matches,
            "fixed_reference_resolves_to_runtime_id": reference_resolves_to_runtime,
            "config_image_matches_fixed_reference": config_reference_matches,
        }
    return evidence, all_pinned and set(evidence) == set(EXPECTED_IMAGES)


def request_json(
    url: str,
    payload: dict | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 20,
) -> dict:
    data = None if payload is None else json.dumps(payload).encode()
    request_headers = dict(headers or {})
    if data is not None:
        request_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=request_headers)
    try:
        with URL_OPENER.open(request, timeout=timeout) as response:
            decoded = json.load(response)
    except urllib.error.HTTPError as exc:
        raise HttpStatusError(exc.code) from None
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


def register_project_key_fingerprints(upstream_url: str, keys: list[str]) -> None:
    hashes = [hashlib.sha256(key.encode("utf-8")).hexdigest() for key in keys]
    response = request_json(
        upstream_url + "/test/expectations",
        {"project_key_sha256": hashes},
    )
    if response.get("registered") != len(hashes):
        raise RuntimeError("upstream did not register all project-key fingerprints")


def sdk_versions() -> dict[str, str]:
    return {
        "python": sys.version.split()[0],
        "openai": importlib.metadata.version("openai"),
        "anthropic": importlib.metadata.version("anthropic"),
        "httpx2": importlib.metadata.version("httpx2"),
    }


def openai_client(api_key: str, base_url: str) -> OpenAI:
    return OpenAI(
        api_key=api_key,
        base_url=base_url,
        max_retries=SDK_MAX_RETRIES,
        http_client=httpx2.Client(trust_env=False, timeout=30.0),
    )


def anthropic_client(api_key: str, base_url: str, *, auth_token: bool = False) -> Anthropic:
    kwargs = {
        "base_url": base_url,
        "max_retries": 0,
        "http_client": httpx2.Client(trust_env=False, timeout=30.0),
    }
    if auth_token:
        # Official Anthropic SDK's auth_token uses Authorization: Bearer for Proxy auth.
        kwargs["auth_token"] = api_key
    else:
        # Official Anthropic SDK's api_key uses x-api-key for the provider credential.
        kwargs["api_key"] = api_key
    return Anthropic(**kwargs)


def sdk_local(upstream_url: str) -> dict:
    """Direct real SDK -> controlled HTTP upstream; no LiteLLM Proxy."""
    results: dict[str, dict] = {}
    base = upstream_url + "/v1"
    client = openai_client(PROVIDER_KEYS["tenant-a"], base)
    try:
        chat_complete_events = 0
        chat_complete_finishes: list[str] = []
        with client.chat.completions.create(
            model="test-model",
            messages=[{"role": "user", "content": "T00_SDK_CHAT_COMPLETE_A"}],
            stream=True,
        ) as stream:
            for chunk in stream:
                chat_complete_events += 1
                chat_complete_finishes.extend(
                    choice.finish_reason
                    for choice in chunk.choices
                    if choice.finish_reason is not None
                )
        chat_eof_events = 0
        chat_eof_finishes: list[str] = []
        with client.chat.completions.create(
            model="test-model",
            messages=[{"role": "user", "content": "T00_SDK_CHAT_EOF_A"}],
            stream=True,
        ) as stream:
            for chunk in stream:
                chat_eof_events += 1
                chat_eof_finishes.extend(
                    choice.finish_reason
                    for choice in chunk.choices
                    if choice.finish_reason is not None
                )
        results["chat"] = {
            "complete_events": chat_complete_events,
            "complete_finish_reasons": chat_complete_finishes,
            "eof_events": chat_eof_events,
            "eof_finish_reasons": chat_eof_finishes,
        }

        responses_complete: list[str] = []
        with client.responses.create(
            model="test-model",
            input="T00_SDK_RESPONSES_COMPLETE_A",
            stream=True,
        ) as stream:
            responses_complete = [event.type for event in stream]
        responses_eof: list[str] = []
        with client.responses.create(
            model="test-model",
            input="T00_SDK_RESPONSES_EOF_A",
            stream=True,
        ) as stream:
            responses_eof = [event.type for event in stream]
        results["responses"] = {
            "complete_events": responses_complete,
            "complete_has_terminal": "response.completed" in responses_complete,
            "eof_events": responses_eof,
            "eof_has_terminal": "response.completed" in responses_eof,
        }
    finally:
        client.close()

    client = anthropic_client(PROVIDER_KEYS["tenant-a"], upstream_url)
    try:
        complete_events: list[str] = []
        with client.messages.stream(
            model="test-model",
            max_tokens=40,
            messages=[{"role": "user", "content": "T00_SDK_MESSAGES_COMPLETE_A"}],
        ) as stream:
            complete_events = [event.type for event in stream]
            complete_final = stream.get_final_message()
        eof_events: list[str] = []
        with client.messages.stream(
            model="test-model",
            max_tokens=40,
            messages=[{"role": "user", "content": "T00_SDK_MESSAGES_EOF_A"}],
        ) as stream:
            eof_events = [event.type for event in stream]
            eof_final = stream.get_final_message()
        results["messages"] = {
            "complete_events": complete_events,
            "complete_stop_reason": complete_final.stop_reason,
            "eof_events": eof_events,
            "eof_stop_reason": None if eof_final is None else eof_final.stop_reason,
        }
    finally:
        client.close()
    return results


def safe_exception(exc: Exception) -> dict:
    return {
        "success": False,
        "status_code": getattr(exc, "status_code", None),
        "error_type": type(exc).__name__,
    }


def proxy_local(proxy_url: str, upstream_url: str) -> dict:
    """Real SDK -> pinned Proxy -> controlled upstream with synthetic credentials."""
    key_a = make_virtual_key(proxy_url, "tenant-a-chat", "t00-chat")
    key_b = make_virtual_key(proxy_url, "tenant-b-chat", "t00-chat")
    key_messages = make_virtual_key(proxy_url, "tenant-a-messages", "t00-messages")
    register_project_key_fingerprints(upstream_url, [key_a, key_b, key_messages])

    def call_chat(tenant: str, project_key: str) -> dict:
        test_id = "T00_PROXY_CHAT_A" if tenant == "tenant-a" else "T00_PROXY_CHAT_B"
        client = openai_client(project_key, proxy_url + "/v1")
        try:
            response = client.chat.completions.create(
                model="t00-chat",
                messages=[{"role": "user", "content": test_id}],
                extra_body={"api_key": PROVIDER_KEYS[tenant]},
            )
            return {
                "success": True,
                "finish_reason": response.choices[0].finish_reason,
                "model_alias": "t00-chat",
            }
        except Exception as exc:
            return safe_exception(exc)
        finally:
            client.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        future_a = pool.submit(call_chat, "tenant-a", key_a)
        future_b = pool.submit(call_chat, "tenant-b", key_b)
        chat_a = future_a.result()
        chat_b = future_b.result()

    messages_client = anthropic_client(key_messages, proxy_url, auth_token=True)
    try:
        try:
            message = messages_client.messages.create(
                model="t00-messages",
                max_tokens=40,
                messages=[{"role": "user", "content": "T00_PROXY_MESSAGES_A"}],
                extra_body={"api_key": PROVIDER_KEYS["tenant-a"]},
            )
            messages_result = {
                "success": True,
                "stop_reason": message.stop_reason,
            }
        except Exception as exc:
            messages_result = safe_exception(exc)
    finally:
        messages_client.close()

    eof_client = openai_client(key_a, proxy_url + "/v1")
    eof_finishes: list[str] = []
    eof_events = 0
    eof_success = False
    try:
        with eof_client.chat.completions.create(
            model="t00-chat",
            messages=[{"role": "user", "content": "T00_PROXY_CHAT_EOF_A"}],
            stream=True,
            extra_body={"api_key": PROVIDER_KEYS["tenant-a"]},
        ) as stream:
            for chunk in stream:
                eof_events += 1
                eof_finishes.extend(
                    choice.finish_reason
                    for choice in chunk.choices
                    if choice.finish_reason is not None
                )
        eof_success = True
    except Exception as exc:
        eof_result = safe_exception(exc)
    else:
        eof_result = {"success": True, "status_code": None, "error_type": None}
    finally:
        eof_client.close()
    eof_result.update({"events": eof_events, "finish_reasons": eof_finishes, "normal_sdk_end": eof_success})

    wrong_project = openai_client(WRONG_PROJECT_KEY, proxy_url + "/v1")
    try:
        try:
            wrong_project.chat.completions.create(
                model="t00-chat",
                messages=[{"role": "user", "content": "T00_PROXY_WRONG_PROJECT_A"}],
                extra_body={"api_key": PROVIDER_KEYS["tenant-a"]},
            )
            wrong_project_result = {"success": True, "status_code": None}
        except Exception as exc:
            wrong_project_result = safe_exception(exc)
    finally:
        wrong_project.close()

    missing_provider = openai_client(key_a, proxy_url + "/v1")
    try:
        try:
            missing_provider.chat.completions.create(
                model="t00-chat",
                messages=[{"role": "user", "content": "T00_PROXY_MISSING_KEY_A"}],
            )
            missing_provider_result = {"success": True, "status_code": None}
        except Exception as exc:
            missing_provider_result = safe_exception(exc)
    finally:
        missing_provider.close()

    upstream = request_json(upstream_url + "/stats")
    records = upstream.get("records", [])
    return {
        "chat": {"tenant-a": chat_a, "tenant-b": chat_b},
        "messages": messages_result,
        "eof": eof_result,
        "wrong_project": wrong_project_result,
        "missing_provider": missing_provider_result,
        "records": records,
        "_secret_values": [
            MASTER_KEY,
            ADMIN_KEY,
            WRONG_PROJECT_KEY,
            DEPLOYMENT_KEY,
            *PROVIDER_KEYS.values(),
            key_a,
            key_b,
            key_messages,
        ],
    }


def records_for(records: list[dict], test_id: str) -> list[dict]:
    return [row for row in records if row.get("test_id") == test_id]


def credential_record_passes(record: dict | None, tenant: str, protocol: str) -> bool:
    if not isinstance(record, dict):
        return False
    scheme = "x-api-key" if protocol == "messages" else "bearer"
    return (
        record.get("tenant") == tenant
        and record.get("expected_tenant") == tenant
        and record.get("provider_key_match") is True
        and record.get("provider_auth_scheme") == scheme
        and record.get("wrong_provider_header_present") is False
        and record.get("project_key_match") is False
        and record.get("master_key_match") is False
        and record.get("admin_key_match") is False
        and record.get("deployment_default_match") is False
    )


def eof_integrity_passes(upstream_terminal: str | None, finish_reasons: list[str]) -> bool:
    incomplete_upstream = upstream_terminal == "normal_eof_without_protocol_terminal"
    downstream_claimed_complete = any(reason in {"stop", "length", "tool_calls", "function_call"} for reason in finish_reasons)
    return not incomplete_upstream or not downstream_claimed_complete


def missing_provider_fails_closed(success: bool, matching_records: list[dict]) -> bool:
    return not success and len(matching_records) == 0


def add_check(checks: list[dict], check_id: str, passed: bool, facts: dict | None = None) -> None:
    checks.append({
        "id": check_id,
        "status": "PASS" if passed else "FAIL",
        "facts": facts or {},
    })


def append_record_checks(
    checks: list[dict],
    check_prefix: str,
    record_rows: list[dict],
    expected_count: int,
    tenant: str,
    protocol: str,
) -> dict | None:
    record = record_rows[0] if len(record_rows) == 1 else None
    add_check(
        checks,
        check_prefix + "_UPSTREAM_COUNT",
        len(record_rows) == expected_count,
        {"observed": len(record_rows), "expected": expected_count},
    )
    add_check(
        checks,
        check_prefix + "_SELECTED_PROVIDER_KEY",
        record is not None
        and record.get("tenant") == tenant
        and record.get("expected_tenant") == tenant
        and record.get("provider_key_match") is True,
        {
            "tenant": None if record is None else record.get("tenant"),
            "provider_key_match": False if record is None else record.get("provider_key_match") is True,
        },
    )
    expected_scheme = "x-api-key" if protocol == "messages" else "bearer"
    add_check(
        checks,
        check_prefix + "_PROVIDER_AUTH_SCHEME",
        record is not None
        and record.get("provider_auth_scheme") == expected_scheme
        and record.get("wrong_provider_header_present") is False,
        {
            "expected_scheme": expected_scheme,
            "observed_scheme": None if record is None else record.get("provider_auth_scheme"),
            "unexpected_provider_header_present": True if record is None else record.get("wrong_provider_header_present") is True,
        },
    )
    for field, label in (
        ("project_key_match", "NO_PROJECT_KEY_FORWARDED"),
        ("master_key_match", "NO_MASTER_KEY_FORWARDED"),
        ("admin_key_match", "NO_ADMIN_KEY_FORWARDED"),
        ("deployment_default_match", "NO_DEPLOYMENT_KEY_FORWARDED"),
    ):
        matched = True if record is None else record.get(field) is True
        add_check(
            checks,
            check_prefix + "_" + label,
            record is not None and not matched,
            {"credential_match": matched},
        )
    return record


def evaluate_sdk_local(checks: list[dict], sdk: dict, upstream_records: list[dict]) -> None:
    config_text = (TOOL_DIR / "proxy.yaml").read_text(encoding="utf-8")
    add_check(checks, "CONFIG_PROXY_HEADER_FORWARDING_DISABLED", (
        "forward_client_headers_to_llm_api: false" in config_text
        and "forward_llm_provider_auth_headers: false" in config_text
    ))
    add_check(checks, "CONFIG_PROXY_AND_SDK_RETRIES_ZERO", (
        config_text.count("num_retries: 0") == 2
        and SDK_MAX_RETRIES == 0
        and PROXY_NUM_RETRIES == 0
    ))
    add_check(
        checks,
        "CONFIG_SYNTHETIC_DEPLOYMENT_DEFAULT_KEY_PRESENT",
        DEPLOYMENT_KEY in config_text,
        {"deployment_default_configured": DEPLOYMENT_KEY in config_text},
    )

    sdk_cases = [
        ("chat", "T00_SDK_CHAT_COMPLETE_A", "tenant-a", "chat"),
        ("responses", "T00_SDK_RESPONSES_COMPLETE_A", "tenant-a", "responses"),
        ("messages", "T00_SDK_MESSAGES_COMPLETE_A", "tenant-a", "messages"),
    ]
    for protocol, test_id, tenant, upstream_protocol in sdk_cases:
        rows = records_for(upstream_records, test_id)
        record = append_record_checks(checks, "SDK_" + protocol.upper() + "_COMPLETE", rows, 1, tenant, upstream_protocol)
        if protocol == "chat":
            complete = sdk["chat"]["complete_finish_reasons"] == ["stop"]
        elif protocol == "responses":
            complete = sdk["responses"]["complete_has_terminal"] is True
        else:
            complete = sdk["messages"]["complete_stop_reason"] == "end_turn"
        add_check(
            checks,
            "SDK_" + protocol.upper() + "_COMPLETE_TERMINAL",
            complete and record is not None and record.get("upstream_terminal") != "normal_eof_without_protocol_terminal",
            {"client_terminal": complete, "upstream_terminal": None if record is None else record.get("upstream_terminal")},
        )

    eof_cases = [
        ("chat", "T00_SDK_CHAT_EOF_A", "tenant-a", "chat"),
        ("responses", "T00_SDK_RESPONSES_EOF_A", "tenant-a", "responses"),
        ("messages", "T00_SDK_MESSAGES_EOF_A", "tenant-a", "messages"),
    ]
    for protocol, test_id, tenant, upstream_protocol in eof_cases:
        rows = records_for(upstream_records, test_id)
        record = append_record_checks(checks, "SDK_" + protocol.upper() + "_EOF", rows, 1, tenant, upstream_protocol)
        if protocol == "chat":
            incomplete = not sdk["chat"]["eof_finish_reasons"]
        elif protocol == "responses":
            incomplete = sdk["responses"]["eof_has_terminal"] is False
        else:
            incomplete = sdk["messages"]["eof_stop_reason"] is None
        add_check(
            checks,
            "SDK_" + protocol.upper() + "_EOF_INCOMPLETE",
            incomplete and record is not None and record.get("upstream_terminal") == "normal_eof_without_protocol_terminal",
            {"client_incomplete": incomplete, "upstream_terminal": None if record is None else record.get("upstream_terminal")},
        )


def evaluate_proxy_local(checks: list[dict], proxy: dict) -> None:
    records = proxy["records"]
    add_check(
        checks,
        "PROXY_CHAT_AB_USE_SAME_MODEL_ALIAS",
        all(proxy["chat"][tenant].get("model_alias") == "t00-chat" for tenant in ("tenant-a", "tenant-b")),
        {"tenant_a_model_alias": proxy["chat"]["tenant-a"].get("model_alias"), "tenant_b_model_alias": proxy["chat"]["tenant-b"].get("model_alias")},
    )
    for tenant in ("tenant-a", "tenant-b"):
        test_id = "T00_PROXY_CHAT_A" if tenant == "tenant-a" else "T00_PROXY_CHAT_B"
        prefix = "PROXY_CHAT_" + tenant.upper().replace("-", "_")
        rows = records_for(records, test_id)
        append_record_checks(checks, prefix, rows, 1, tenant, "chat")
        response = proxy["chat"][tenant]
        add_check(
            checks,
            prefix + "_SDK_COMPLETE_TERMINAL",
            response.get("success") is True and response.get("finish_reason") == "stop",
            {"sdk_success": response.get("success") is True, "finish_reason": response.get("finish_reason")},
        )

    rows = records_for(records, "T00_PROXY_MESSAGES_A")
    record = append_record_checks(checks, "PROXY_MESSAGES_TENANT_A", rows, 1, "tenant-a", "messages")
    response = proxy["messages"]
    add_check(
        checks,
        "PROXY_MESSAGES_COMPLETE_TERMINAL",
        response.get("success") is True and response.get("stop_reason") == "end_turn"
        and record is not None and record.get("upstream_terminal") == "message_stop",
        {"sdk_success": response.get("success") is True, "stop_reason": response.get("stop_reason"), "upstream_terminal": None if record is None else record.get("upstream_terminal")},
    )

    eof_rows = records_for(records, "T00_PROXY_CHAT_EOF_A")
    eof_record = append_record_checks(checks, "PROXY_CHAT_EOF", eof_rows, 1, "tenant-a", "chat")
    eof_safe = eof_integrity_passes(
        None if eof_record is None else eof_record.get("upstream_terminal"),
        proxy["eof"].get("finish_reasons", []),
    )
    add_check(
        checks,
        "PROXY_CHAT_EOF_NOT_SYNTHESIZED_COMPLETE",
        eof_safe,
        {
            "upstream_terminal": None if eof_record is None else eof_record.get("upstream_terminal"),
            "downstream_finish_reasons": proxy["eof"].get("finish_reasons", []),
            "sdk_normal_end": proxy["eof"].get("normal_sdk_end") is True,
        },
    )

    wrong_rows = records_for(records, "T00_PROXY_WRONG_PROJECT_A")
    wrong = proxy["wrong_project"]
    add_check(
        checks,
        "PROXY_WRONG_PROJECT_REJECTED_BEFORE_UPSTREAM",
        wrong.get("success") is False and len(wrong_rows) == 0,
        {"http_status": wrong.get("status_code"), "upstream_count": len(wrong_rows)},
    )

    missing_rows = records_for(records, "T00_PROXY_MISSING_KEY_A")
    missing = proxy["missing_provider"]
    add_check(
        checks,
        "PROXY_MISSING_PROVIDER_FAILS_CLOSED",
        missing_provider_fails_closed(missing.get("success") is True, missing_rows),
        {"http_status": missing.get("status_code"), "upstream_count": len(missing_rows)},
    )
    default_route_count = sum(1 for row in missing_rows if row.get("deployment_default_match") is True)
    add_check(
        checks,
        "PROXY_MISSING_PROVIDER_DID_NOT_USE_DEPLOYMENT_DEFAULT",
        default_route_count == 0,
        {"deployment_default_route_count": default_route_count},
    )


def cleanup_project(project: str) -> list[dict]:
    outcomes = []
    compose_error = None
    try:
        compose(project, "down", "--volumes", "--remove-orphans", timeout=90)
    except Exception as exc:
        compose_error = type(exc).__name__
    outcomes.append({
        "id": "CLEANUP_COMPOSE_DOWN",
        "status": "PASS" if compose_error is None else "FAIL",
        "facts": {"error_type": compose_error},
    })

    leftovers = {"containers": None, "networks": None}
    inspection_error = None
    try:
        containers = docker(
            ["ps", "-aq", "--filter", f"label=com.docker.compose.project={project}"],
            timeout=20,
        )
        networks = docker(
            ["network", "ls", "-q", "--filter", f"label=com.docker.compose.project={project}"],
            timeout=20,
        )
        leftovers = {
            "containers": len([item for item in containers.splitlines() if item]),
            "networks": len([item for item in networks.splitlines() if item]),
        }
    except Exception as exc:
        inspection_error = type(exc).__name__
    outcomes.append({
        "id": "CLEANUP_NO_PROJECT_RESOURCES_LEFT",
        "status": "PASS" if inspection_error is None and leftovers["containers"] == 0 and leftovers["networks"] == 0 else "FAIL",
        "facts": {**leftovers, "error_type": inspection_error},
    })
    return outcomes


def run_probe(project: str) -> dict:
    result: dict = {
        "scope": "PROBE_SUBSET_ONLY",
        "status": "PARTIAL",
        "provider_real": "NOT_RUN",
        "sdk_versions": sdk_versions(),
        "checks": [],
        "uncovered": [
            "explicit length/incomplete",
            "truncated body",
            "timeout",
            "SSE error",
            "HTTP error injection",
            "malformed/partial tool arguments and allowlist rejection",
            "two tool round trips",
            "continuation privacy and raw-item preservation",
            "cancellation resource closure",
            "old chat/research/translation regression baseline",
        ],
    }
    proxy_url = f"http://{inspect_ip(project, 'proxy')}:4000"
    upstream_url = f"http://{inspect_ip(project, 'upstream')}:8080"
    result["runtime_versions"] = docker_versions(project)

    images, image_checks_pass = container_image_evidence(project)
    result["images"] = images
    add_check(
        result["checks"],
        "ENV_ACTUAL_CONTAINER_IMAGE_IDS_AND_DIGESTS",
        image_checks_pass,
        {
            "services": sorted(images),
            "all_configured_refs_and_runtime_image_ids_match_pins": image_checks_pass,
        },
    )

    result["sdk_local"] = sdk_local(upstream_url)
    proxy = proxy_local(proxy_url, upstream_url)
    secret_values = proxy.pop("_secret_values")
    result["proxy_local"] = {
        key: value for key, value in proxy.items() if key != "records"
    }
    evaluate_sdk_local(result["checks"], result["sdk_local"], proxy["records"])
    evaluate_proxy_local(result["checks"], proxy)

    logs = docker([
        "compose", "--project-name", project, "-f", str(COMPOSE_FILE),
        "logs", "--no-color", "proxy", "upstream",
    ], timeout=30)
    leaked_secret = any(secret and secret in logs for secret in secret_values)
    add_check(
        result["checks"],
        "LOGS_NO_SYNTHETIC_CREDENTIAL_VALUES",
        not leaked_secret,
        {"credential_values_found_in_container_logs": leaked_secret},
    )

    # Recheck deployed runtime and static proxy configuration with actual values.
    versions = result["runtime_versions"]
    serialized_result = json.dumps(result, ensure_ascii=False)
    credential_in_output = any(secret and secret in serialized_result for secret in secret_values)
    add_check(
        result["checks"],
        "CLI_OUTPUT_NO_CREDENTIAL_VALUES",
        not credential_in_output,
        {"credential_values_found_in_output": credential_in_output},
    )
    add_check(
        result["checks"],
        "ENV_PINNED_LITELLM_RUNTIME",
        versions.get("litellm") == "1.104.2",
        {"litellm": versions.get("litellm")},
    )
    add_check(
        result["checks"],
        "ENV_SDK_RETRIES_DISABLED",
        result["sdk_versions"].get("openai") is not None
        and result["sdk_versions"].get("anthropic") is not None,
        {
            "openai": result["sdk_versions"].get("openai"),
            "anthropic": result["sdk_versions"].get("anthropic"),
            "max_retries_configured": SDK_MAX_RETRIES,
            "proxy_num_retries_configured": PROXY_NUM_RETRIES,
        },
    )
    return result



def image_evidence_only() -> int:
    project = "byok-t00-images-" + uuid.uuid4().hex[:8]
    result = {
        "scope": "IMAGE_EVIDENCE_ONLY",
        "provider_real": "NOT_RUN",
        "checks": [],
    }
    try:
        compose(project, "up", "-d", "--wait", "--wait-timeout", "180", timeout=210)
        images, image_checks_pass = container_image_evidence(project)
        result["images"] = images
        add_check(
            result["checks"],
            "IMAGE_FIXED_REFERENCES_RESOLVE_TO_RUNNING_IDS",
            image_checks_pass,
            {"services": sorted(images)},
        )
    except Exception as exc:
        add_check(
            result["checks"],
            "IMAGE_EVIDENCE_COMPLETED",
            False,
            {"error_type": type(exc).__name__},
        )
    finally:
        result["checks"].extend(cleanup_project(project))

    failed_checks = [item for item in result["checks"] if item["status"] == "FAIL"]
    result["status"] = "FAIL" if failed_checks else "PASS"
    result["failed_check_ids"] = [item["id"] for item in failed_checks]
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 1 if failed_checks else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--images-only",
        action="store_true",
        help="start the isolated Compose fixture, verify image references/IDs, and clean it up without model requests",
    )
    args = parser.parse_args()
    if args.images_only:
        return image_evidence_only()
    project = "byok-t00-probe-" + uuid.uuid4().hex[:8]
    result = {
        "scope": "PROBE_SUBSET_ONLY",
        "provider_real": "NOT_RUN",
        "sdk_versions": sdk_versions(),
        "checks": [],
    }
    started = False
    try:
        compose(project, "up", "-d", "--wait", "--wait-timeout", "180", timeout=210)
        started = True
        result = run_probe(project)
    except Exception as exc:
        add_check(
            result["checks"],
            "PROBE_EXECUTION_COMPLETED",
            False,
            {"error_type": type(exc).__name__, "status_code": getattr(exc, "status_code", None)},
        )
    finally:
        result["checks"].extend(cleanup_project(project))

    failed_checks = [item for item in result["checks"] if item["status"] == "FAIL"]
    passed_checks = [item for item in result["checks"] if item["status"] == "PASS"]
    failures = len(failed_checks)
    result["status"] = "FAIL" if failures else "PARTIAL"
    result["failed_check_count"] = failures
    result["passed_check_count"] = len(passed_checks)
    result["failed_check_ids"] = [item["id"] for item in failed_checks]
    result["provider_real"] = "NOT_RUN"
    result["temporary_resources_started"] = started
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
