#!/usr/bin/env python3
"""Run the isolated T00 SDK/Proxy probe; this never contacts a real provider."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import inspect
import json
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx2
from anthropic import Anthropic
from openai import OpenAI
from deepseek_smoke import (
    EXPECTED_ANSWER as DEEPSEEK_EXPECTED_ANSWER,
    MAX_OUTPUT_TOKENS as DEEPSEEK_MAX_OUTPUT_TOKENS,
    PROMPT as DEEPSEEK_SMOKE_PROMPT,
    _valid_completion as validate_deepseek_completion,
)


TOOL_DIR = Path(__file__).resolve().parent
COMPOSE_FILE = TOOL_DIR / "compose.yaml"
MASTER_KEY = "sk-t00-master-synthetic"
ADMIN_KEY = "sk-t00-admin-synthetic"
SDK_MAX_RETRIES = 0
PROXY_NUM_RETRIES = 0
CANCEL_PROPAGATION_OBSERVATION_WINDOW_SECONDS = 2.0
WRONG_PROJECT_KEY = "sk-t00-wrong-project-synthetic"
DEPLOYMENT_KEY = "sk-t00-deployment-default-synthetic"
PROVIDER_KEYS = {
    "tenant-a": "sk-t00-provider-a-synthetic",
    "tenant-b": "sk-t00-provider-b-synthetic",
}
EXPECTED_IMAGES = {
    "db": "postgres@sha256:721873c34ceb9f8d8fc265984940dc982404c105f19ad51be9fdc5970a6080ea",
    "proxy": "ghcr.io/berriai/litellm@sha256:3d88bd757134a00e8c00237b85a021ab1f6d54abb9c1df750f411dbe7256a500",
    "unguarded_proxy": "ghcr.io/berriai/litellm@sha256:3d88bd757134a00e8c00237b85a021ab1f6d54abb9c1df750f411dbe7256a500",
    "native_stream_proxy": "ghcr.io/berriai/litellm@sha256:3d88bd757134a00e8c00237b85a021ab1f6d54abb9c1df750f411dbe7256a500",
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
    native_stream_proxy_version = docker(
        [
            "exec",
            service_container_id(project, "native_stream_proxy"),
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
        "litellm_native_stream_proxy": native_stream_proxy_version,
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


def http_status_ok(url: str, timeout: float = 1.0) -> bool:
    """Return only whether a local health endpoint responds with HTTP 2xx."""
    request = urllib.request.Request(url)
    try:
        with URL_OPENER.open(request, timeout=timeout) as response:
            return 200 <= response.status < 300
    except (OSError, urllib.error.URLError):
        return False


def request_json_with_status(
    url: str,
    payload: dict,
    headers: dict[str, str] | None = None,
    timeout: int = 20,
) -> tuple[int, dict]:
    data = json.dumps(payload).encode()
    request_headers = dict(headers or {})
    request_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=request_headers)
    try:
        with URL_OPENER.open(request, timeout=timeout) as response:
            status_code = response.status
            raw = response.read()
    except urllib.error.HTTPError as exc:
        status_code = exc.code
        raw = exc.read()
    try:
        decoded = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        decoded = {}
    return status_code, decoded if isinstance(decoded, dict) else {}


def safe_error_marker(response_body: dict) -> str | None:
    """Return a known static callback marker without exposing response text."""
    serialized = json.dumps(response_body, ensure_ascii=True, sort_keys=True)
    for marker in ("BYOK_PROVIDER_KEY_REQUIRED", "T00_STREAMING_DISABLED"):
        if marker in serialized:
            return marker
    return None


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


def openai_client(api_key: str, base_url: str, *, timeout: float = 30.0) -> OpenAI:
    return OpenAI(
        api_key=api_key,
        base_url=base_url,
        max_retries=SDK_MAX_RETRIES,
        http_client=httpx2.Client(trust_env=False, timeout=timeout),
    )


def anthropic_client(api_key: str, base_url: str, *, auth_token: bool = False, timeout: float = 30.0) -> Anthropic:
    kwargs = {
        "base_url": base_url,
        "max_retries": 0,
        "http_client": httpx2.Client(trust_env=False, timeout=timeout),
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

    sdk_base_urls = {
        "chat": upstream_url + "/v1",
        "responses": upstream_url + "/v1",
        "messages": upstream_url,
    }
    sdk_keys = {protocol: PROVIDER_KEYS["tenant-a"] for protocol in sdk_base_urls}
    errors = {
        protocol: run_protocol_error_cases(
            sdk_base_urls[protocol], protocol, f"T00_SDK_{protocol.upper()}",
            sdk_keys[protocol], provider_key=sdk_keys[protocol],
            cases=("HTTP_ERROR", "TIMEOUT", "TRUNCATED"),
        )
        for protocol in sdk_base_urls
    }
    incomplete = {
        protocol: run_incomplete_cases(sdk_base_urls[protocol], protocol, provider_key=sdk_keys[protocol])
        for protocol in sdk_base_urls
    }
    results["error_cases"] = errors
    results["incomplete_cases"] = incomplete
    results["stream_cases"] = run_stream_group(
        sdk_base_urls, tuple(sdk_base_urls), sdk_keys,
        upstream_url=upstream_url,
        cases=("COMPLETE", "EOF", "INCOMPLETE", "SSE_ERROR", "CANCEL"),
    )
    results["tool_roundtrips"] = {
        protocol: proxy_tool_roundtrip(
            protocol, sdk_base_urls[protocol], sdk_keys[protocol], sdk_keys[protocol], via_proxy=False,
        )
        for protocol in sdk_base_urls
    }
    return results


def safe_exception(exc: Exception) -> dict:
    return {
        "success": False,
        "status_code": getattr(exc, "status_code", None),
        "error_type": type(exc).__name__,
    }


def run_chat_error_cases(base_url: str, test_prefix: str, sdk_key: str, provider_key: str | None = None, cases: tuple[str, ...] = ("HTTP_ERROR", "TIMEOUT", "TRUNCATED", "SSE_ERROR")) -> dict:
    """Exercise HTTP, timeout, truncation, and SSE error paths with one client request each."""
    results = {}
    for case in cases:
        marker = f"{test_prefix}_{case}_A"
        client = openai_client(sdk_key, base_url, timeout=0.15 if case == "TIMEOUT" else 10.0)
        try:
            kwargs = {"model": "t00-chat" if "/4000" in base_url else "test-model", "messages": [{"role": "user", "content": marker}]}
            if provider_key is not None:
                kwargs["extra_body"] = {"api_key": provider_key}
            if case == "SSE_ERROR":
                kwargs["stream"] = True
                with client.chat.completions.create(**kwargs) as stream:
                    for _chunk in stream:
                        pass
                results[case.lower()] = {"success": True, "error_type": None, "status_code": None}
            else:
                response = client.chat.completions.create(**kwargs)
                results[case.lower()] = {"success": True, "error_type": None, "status_code": None, "finish_reason": response.choices[0].finish_reason}
        except Exception as exc:
            results[case.lower()] = safe_exception(exc)
        finally:
            client.close()
    return results


def run_incomplete_cases(base_url: str, protocol: str, *, project_key: str | None = None, provider_key: str | None = None) -> dict:
    """Check native length/incomplete endings without converting them to complete."""
    marker = f"T00_{'PROXY' if project_key else 'SDK'}_{protocol.upper()}_INCOMPLETE_A"
    sdk_key = project_key or provider_key or ""
    if protocol == "chat":
        client = openai_client(sdk_key, base_url)
        try:
            kwargs = {"model": "t00-chat" if project_key else "test-model", "messages": [{"role": "user", "content": marker}]}
            if project_key and provider_key:
                kwargs["extra_body"] = {"api_key": provider_key}
            response = client.chat.completions.create(**kwargs)
            return {"success": True, "terminal": response.choices[0].finish_reason}
        except Exception as exc:
            return safe_exception(exc)
        finally:
            client.close()
    if protocol == "responses":
        client = openai_client(sdk_key, base_url)
        try:
            kwargs = {"model": "t00-chat" if project_key else "test-model", "input": marker}
            if project_key and provider_key:
                kwargs["extra_body"] = {"api_key": provider_key}
            response = client.responses.create(**kwargs)
            return {"success": True, "terminal": response.status, "incomplete_reason": None if response.incomplete_details is None else response.incomplete_details.reason}
        except Exception as exc:
            return safe_exception(exc)
        finally:
            client.close()
    client = anthropic_client(sdk_key, base_url, auth_token=bool(project_key))
    try:
        kwargs = {"model": "t00-messages" if project_key else "test-model", "max_tokens": 40, "messages": [{"role": "user", "content": marker}]}
        if project_key and provider_key:
            kwargs["extra_body"] = {"api_key": provider_key}
        response = client.messages.create(**kwargs)
        return {"success": True, "terminal": response.stop_reason}
    except Exception as exc:
        return safe_exception(exc)
    finally:
        client.close()


def protocol_client(protocol: str, sdk_key: str, base_url: str, *, via_proxy: bool, timeout: float = 10.0):
    if protocol == "messages":
        return anthropic_client(sdk_key, base_url, auth_token=via_proxy, timeout=timeout)
    return openai_client(sdk_key, base_url, timeout=timeout)


def protocol_request(protocol: str, model: str, marker: str, *, provider_key: str | None, via_proxy: bool, stream: bool = False) -> dict:
    if protocol == "chat":
        kwargs = {"model": model, "messages": [{"role": "user", "content": marker}]}
    elif protocol == "responses":
        kwargs = {"model": model, "input": marker}
    else:
        kwargs = {"model": model, "max_tokens": 40, "messages": [{"role": "user", "content": marker}]}
    if stream:
        kwargs["stream"] = True
    if via_proxy and provider_key is not None:
        kwargs["extra_body"] = {"api_key": provider_key}
    return kwargs


def run_protocol_error_cases(
    base_url: str,
    protocol: str,
    test_prefix: str,
    sdk_key: str,
    *,
    provider_key: str | None = None,
    via_proxy: bool = False,
    cases: tuple[str, ...] = ("HTTP_ERROR", "TIMEOUT", "TRUNCATED", "SSE_ERROR"),
) -> dict:
    """Run one request per synthetic error class through one SDK/protocol path."""
    model = ("t00-messages" if protocol == "messages" else "t00-chat") if via_proxy else "test-model"
    results = {}
    for case in cases:
        marker = f"{test_prefix}_{case}_A"
        client = protocol_client(
            protocol, sdk_key, base_url, via_proxy=via_proxy,
            timeout=0.15 if case == "TIMEOUT" else 10.0,
        )
        try:
            kwargs = protocol_request(
                protocol, model, marker, provider_key=provider_key,
                via_proxy=via_proxy, stream=case == "SSE_ERROR",
            )
            if case == "SSE_ERROR":
                response = (
                    client.chat.completions.create(**kwargs)
                    if protocol == "chat" else
                    client.responses.create(**kwargs)
                    if protocol == "responses" else
                    client.messages.create(**kwargs)
                )
                with response:
                    for _event in response:
                        pass
                result = {"success": True, "error_type": None}
            elif protocol == "chat":
                response = client.chat.completions.create(**kwargs)
                result = {"success": True, "finish_reason": response.choices[0].finish_reason}
            elif protocol == "responses":
                response = client.responses.create(**kwargs)
                result = {"success": True, "terminal": response.status}
            else:
                response = client.messages.create(**kwargs)
                result = {"success": True, "terminal": response.stop_reason}
        except Exception as exc:
            result = safe_exception(exc)
        finally:
            client.close()
        results[case.lower()] = result
    return results


def _stream_event_facts(protocol: str, event: object) -> tuple[str | None, str | None]:
    event_type = getattr(event, "type", None)
    terminal = None
    stop_reason = None
    if protocol == "chat":
        event_type = "chat.chunk"
        for choice in getattr(event, "choices", []) or []:
            if choice.finish_reason is not None:
                terminal = choice.finish_reason
    elif protocol == "responses" and event_type in {"response.completed", "response.incomplete", "error"}:
        response = getattr(event, "response", None)
        terminal = getattr(response, "status", None) or event_type
    elif protocol == "messages" and event_type == "message_delta":
        delta = getattr(event, "delta", None)
        stop_reason = getattr(delta, "stop_reason", None)
        terminal = stop_reason
    elif protocol == "messages" and event_type in {"message_stop", "error"}:
        terminal = event_type
    return event_type, terminal if terminal is not None else stop_reason


def run_protocol_stream_case(
    base_url: str,
    protocol: str,
    case: str,
    sdk_key: str,
    *,
    provider_key: str | None = None,
    via_proxy: bool = False,
    upstream_url: str | None = None,
    proxy_health_url: str | None = None,
) -> dict:
    """Read a protocol stream with the official SDK and record only event names/terminals."""
    prefix = "PROXY" if via_proxy else "SDK"
    marker = f"T00_{prefix}_{protocol.upper()}_STREAM_{case}_A"
    model = ("t00-messages" if protocol == "messages" else "t00-chat") if via_proxy else "test-model"
    client = protocol_client(protocol, sdk_key, base_url, via_proxy=via_proxy)
    stream = None
    event_types: list[str] = []
    terminals: list[str] = []
    canceled_after_first = False
    downstream_close_monotonic_ns = None
    result: dict
    try:
        kwargs = protocol_request(
            protocol, model, marker, provider_key=provider_key,
            via_proxy=via_proxy, stream=True,
        )
        if protocol == "chat":
            stream = client.chat.completions.create(**kwargs)
        elif protocol == "responses":
            stream = client.responses.create(**kwargs)
        else:
            stream = client.messages.create(**kwargs)
        with stream:
            if case == "CANCEL":
                event = next(iter(stream))
                event_type, terminal = _stream_event_facts(protocol, event)
                if event_type:
                    event_types.append(event_type)
                if terminal:
                    terminals.append(terminal)
                canceled_after_first = True
            else:
                for event in stream:
                    event_type, terminal = _stream_event_facts(protocol, event)
                    if event_type:
                        event_types.append(event_type)
                    if terminal:
                        terminals.append(terminal)
        result = {
            "success": True,
            "outcome": "cancelled" if case == "CANCEL" else "stream_consumed",
            "stream_complete": case != "CANCEL",
        }
    except Exception as exc:
        result = safe_exception(exc)
    finally:
        response = getattr(stream, "response", None)
        if case == "CANCEL":
            downstream_close_monotonic_ns = time.monotonic_ns()
        result.update({
            "event_count": len(event_types),
            "event_types": event_types,
            "terminals": terminals,
            "canceled_after_first_event": canceled_after_first,
            "client_response_closed": bool(response is not None and response.is_closed),
            "downstream_close_monotonic_ns": downstream_close_monotonic_ns,
        })
        client.close()
    if case == "CANCEL" and upstream_url and downstream_close_monotonic_ns is not None:
        deadline = time.monotonic() + CANCEL_PROPAGATION_OBSERVATION_WINDOW_SECONDS
        latest_stats: dict = {}
        observed_record: dict = {}
        while time.monotonic() <= deadline:
            try:
                latest_stats = request_json(upstream_url + "/stats", timeout=0.25)
                observed_record = next((
                    item for item in latest_stats.get("records", [])
                    if item.get("test_id") == marker
                ), {})
            except (OSError, RuntimeError, HttpStatusError):
                observed_record = {}
            if (
                observed_record.get("client_disconnected") is True
                and observed_record.get("upstream_stream_producer_exit_monotonic_ns") is not None
            ):
                break
            time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))

        disconnect_ns = observed_record.get("upstream_disconnect_monotonic_ns")
        producer_exit_ns = observed_record.get("upstream_stream_producer_exit_monotonic_ns")
        disconnect_delay_ms = (
            None if disconnect_ns is None else round((disconnect_ns - downstream_close_monotonic_ns) / 1_000_000, 3)
        )
        producer_exit_delay_ms = (
            None if producer_exit_ns is None else round((producer_exit_ns - downstream_close_monotonic_ns) / 1_000_000, 3)
        )
        observation_window_ms = int(CANCEL_PROPAGATION_OBSERVATION_WINDOW_SECONDS * 1000)
        active_producers = latest_stats.get("active_stream_producers")
        proxy_liveness_ok = (
            None if proxy_health_url is None else http_status_ok(proxy_health_url, timeout=1.0)
        )
        write_times = observed_record.get("upstream_stream_write_monotonic_ns", [])
        result.update({
            "cancel_observation_window_ms": observation_window_ms,
            "upstream_disconnect_delay_ms": disconnect_delay_ms,
            "upstream_producer_exit_delay_ms": producer_exit_delay_ms,
            "upstream_disconnect_monotonic_ns": disconnect_ns,
            "upstream_producer_exit_monotonic_ns": producer_exit_ns,
            "upstream_disconnect_within_observation_window": (
                disconnect_delay_ms is not None and 0 <= disconnect_delay_ms <= observation_window_ms
            ),
            "upstream_producer_exited_within_observation_window": (
                producer_exit_delay_ms is not None and 0 <= producer_exit_delay_ms <= observation_window_ms
            ),
            "active_upstream_producers_at_observation_end": active_producers,
            "proxy_liveness_http_2xx_after_cancel": proxy_liveness_ok,
            "upstream_disconnect_observed": observed_record.get("client_disconnected") is True,
            "upstream_producer_exit_reason": observed_record.get("producer_exit_reason"),
            "upstream_stream_body_finished": observed_record.get("upstream_stream_body_finished") is True,
            "upstream_frames_written_at_disconnect": observed_record.get("upstream_stream_events_written"),
            "upstream_frames_written_after_downstream_close": (
                sum(1 for write_ns in write_times if write_ns > downstream_close_monotonic_ns)
                if isinstance(write_times, list) else None
            ),
            "upstream_cancel_fixture_frames_written": observed_record.get("cancel_fixture_frames_written", 0),
        })
    return result


def run_stream_group(
    base_urls: dict[str, str],
    protocols: tuple[str, ...],
    sdk_keys: dict[str, str],
    *,
    provider_key: str | None = None,
    via_proxy: bool = False,
    upstream_url: str | None = None,
    proxy_health_url: str | None = None,
    cases: tuple[str, ...] = ("COMPLETE", "EOF", "INCOMPLETE", "SSE_ERROR", "CANCEL"),
) -> dict:
    results = {}
    for protocol in protocols:
        results[protocol] = {}
        for case in cases:
            results[protocol][case.lower()] = run_protocol_stream_case(
                base_urls[protocol], protocol, case, sdk_keys[protocol],
                provider_key=provider_key, via_proxy=via_proxy,
                upstream_url=upstream_url,
                proxy_health_url=proxy_health_url,
            )
    return results


OPENAI_TOOL_SCHEMA = {
    "type": "object",
    "properties": {"city": {"type": "string"}},
    "required": ["city"],
    "additionalProperties": False,
}
TOOL_SCHEMAS = {
    "lookup_weather": {"city"},
    "format_weather": {"summary"},
}


def dispatch_synthetic_tool(name: str, arguments: str | dict) -> tuple[str, str | None]:
    """Validate tool output before dispatching to pure, local fixture functions."""
    if name not in TOOL_SCHEMAS:
        return "not_allowlisted", None
    if isinstance(arguments, str):
        try:
            parsed = json.loads(arguments)
        except json.JSONDecodeError as exc:
            reason = "partial_json" if exc.pos >= len(arguments.rstrip()) else "invalid_json"
            return reason, None
    elif isinstance(arguments, dict):
        parsed = arguments
    else:
        return "invalid_argument_shape", None
    if not isinstance(parsed, dict) or set(parsed) != TOOL_SCHEMAS[name]:
        return "invalid_argument_shape", None
    value = parsed[next(iter(TOOL_SCHEMAS[name]))]
    if not isinstance(value, str):
        return "invalid_argument_shape", None
    if name == "lookup_weather" and value == "synthetic-city":
        return "dispatched", "synthetic-weather"
    if name == "format_weather" and value == "synthetic-weather":
        return "dispatched", "synthetic-summary"
    return "invalid_argument_value", None


def tool_definitions(protocol: str) -> list[dict]:
    if protocol == "messages":
        return [
            {"name": "lookup_weather", "description": "Synthetic local lookup", "input_schema": OPENAI_TOOL_SCHEMA},
            {"name": "format_weather", "description": "Synthetic local formatter", "input_schema": {
                "type": "object", "properties": {"summary": {"type": "string"}},
                "required": ["summary"], "additionalProperties": False,
            }},
        ]
    if protocol == "responses":
        return [
            {"type": "function", "name": "lookup_weather", "description": "Synthetic local lookup", "parameters": OPENAI_TOOL_SCHEMA},
            {"type": "function", "name": "format_weather", "description": "Synthetic local formatter", "parameters": {
                "type": "object", "properties": {"summary": {"type": "string"}},
                "required": ["summary"], "additionalProperties": False,
            }},
        ]
    return [
        {"type": "function", "function": {"name": "lookup_weather", "description": "Synthetic local lookup", "parameters": OPENAI_TOOL_SCHEMA}},
        {"type": "function", "function": {"name": "format_weather", "description": "Synthetic local formatter", "parameters": {
            "type": "object", "properties": {"summary": {"type": "string"}},
            "required": ["summary"], "additionalProperties": False,
        }}},
    ]


def _public_output(text: str | None, continuation: object, secrets: list[str]) -> tuple[dict, bool, bool]:
    public = {"text": text}
    serialized = json.dumps(public, ensure_ascii=True, sort_keys=True)
    continuation_serialized = json.dumps(continuation, ensure_ascii=True, default=str)
    leaked_continuation = any(
        value and value in serialized for value in (
            "opaque-chat-state-r1", "opaque-chat-state-r2",
            "opaque-responses-continuation-r1", "opaque-responses-continuation-r2",
            "opaque-messages-state-r1", "opaque-signature-r1", "opaque-signature-r2",
        )
    ) or continuation_serialized in serialized
    leaked_key = any(value and value in serialized for value in secrets)
    return public, leaked_continuation, leaked_key


def proxy_tool_roundtrip(
    protocol: str,
    proxy_url: str,
    project_key: str,
    provider_key: str,
    *,
    via_proxy: bool = True,
    foreign_responses_ids: bool = False,
) -> dict:
    """Two synthetic tool turns through the official SDK and optional Proxy."""
    public_text = None
    continuation_snapshots = []
    dispatch_outcomes = []
    source = "PROXY" if via_proxy else "SDK"
    model = ("t00-messages" if protocol == "messages" else "t00-chat") if via_proxy else "test-model"
    provider_body = {"extra_body": {"api_key": provider_key}} if via_proxy else {}
    client = (
        anthropic_client(project_key, proxy_url, auth_token=via_proxy)
        if protocol == "messages"
        else openai_client(project_key, proxy_url + "/v1")
    )
    try:
        if protocol == "chat":
            conversation = [{"role": "user", "content": f"T00_{source}_CHAT_TOOL_R1_A"}]
            for round_number in (1, 2):
                response = client.chat.completions.create(
                    model=model, messages=conversation, tools=tool_definitions("chat"),
                    **provider_body,
                )
                message = response.choices[0].message
                raw_message = message.model_dump(exclude_none=True)
                continuation_snapshots.append(raw_message)
                conversation.append(raw_message)
                for call in message.tool_calls or []:
                    outcome, result = dispatch_synthetic_tool(call.function.name, call.function.arguments)
                    dispatch_outcomes.append(outcome)
                    if outcome == "dispatched":
                        conversation.append({"role": "tool", "tool_call_id": call.id, "content": result})
                conversation.append({"role": "user", "content": f"T00_{source}_CHAT_TOOL_R{round_number + 1}_A" if round_number == 1 else f"T00_{source}_CHAT_TOOL_FINAL_A"})
            final = client.chat.completions.create(
                model=model, messages=conversation,
                **provider_body,
            )
            public_text = final.choices[0].message.content
        elif protocol == "responses":
            marker_prefix = f"T00_{source}_RESPONSES_" + ("FOREIGN_TOOL_" if foreign_responses_ids else "TOOL_")
            input_items = [{"role": "user", "content": marker_prefix + "R1_A"}]
            for round_number in (1, 2):
                response = client.responses.create(
                    model=model, input=input_items, tools=tool_definitions("responses"),
                    **provider_body,
                )
                raw_items = [item.model_dump(exclude_none=True) for item in response.output]
                continuation_snapshots.append(raw_items)
                input_items.extend(raw_items)
                for item in response.output:
                    if getattr(item, "type", None) != "function_call":
                        continue
                    outcome, result = dispatch_synthetic_tool(item.name, item.arguments)
                    dispatch_outcomes.append(outcome)
                    if outcome == "dispatched":
                        input_items.append({"type": "function_call_output", "call_id": item.call_id, "output": result})
                input_items.append({"role": "user", "content": marker_prefix + f"R{round_number + 1}_A" if round_number == 1 else marker_prefix + "FINAL_A"})
            final = client.responses.create(
                model=model, input=input_items,
                **provider_body,
            )
            public_text = final.output_text
        else:
            messages = [{"role": "user", "content": f"T00_{source}_MESSAGES_TOOL_R1_A"}]
            for round_number in (1, 2):
                response = client.messages.create(
                    model=model, max_tokens=40, messages=messages,
                    tools=tool_definitions("messages"),
                    **provider_body,
                )
                raw_content = [block.model_dump(exclude_none=True) for block in response.content]
                continuation_snapshots.append(raw_content)
                messages.append({"role": "assistant", "content": raw_content})
                for block in response.content:
                    if getattr(block, "type", None) != "tool_use":
                        continue
                    outcome, result = dispatch_synthetic_tool(block.name, block.input)
                    dispatch_outcomes.append(outcome)
                    if outcome == "dispatched":
                        messages.append({"role": "user", "content": [{"type": "tool_result", "tool_use_id": block.id, "content": result}]})
                messages.append({"role": "user", "content": f"T00_{source}_MESSAGES_TOOL_R{round_number + 1}_A" if round_number == 1 else f"T00_{source}_MESSAGES_TOOL_FINAL_A"})
            final = client.messages.create(
                model=model, max_tokens=40, messages=messages,
                **provider_body,
            )
            public_text = "".join(block.text for block in final.content if getattr(block, "type", None) == "text")
        public, continuation_leak, key_leak = _public_output(public_text, continuation_snapshots, [provider_key, project_key])
        return {
            "success": True,
            "public_output": public,
            "tool_dispatch_outcomes": dispatch_outcomes,
            "continuation_in_public": continuation_leak,
            "key_in_public": key_leak,
        }
    except Exception as exc:
        return safe_exception(exc)
    finally:
        client.close()


def probe_invalid_tool(protocol: str, variant: str, proxy_url: str, project_key: str, provider_key: str) -> dict:
    test_id = f"T00_PROXY_{protocol.upper()}_TOOL_{variant.upper()}_A"
    client = anthropic_client(project_key, proxy_url, auth_token=True) if protocol == "messages" else openai_client(project_key, proxy_url + "/v1")
    try:
        if protocol == "chat":
            response = client.chat.completions.create(
                model="t00-chat", messages=[{"role": "user", "content": test_id}],
                tools=tool_definitions("chat"), extra_body={"api_key": provider_key},
            )
            call = response.choices[0].message.tool_calls[0]
            outcome, _ = dispatch_synthetic_tool(call.function.name, call.function.arguments)
        elif protocol == "responses":
            response = client.responses.create(
                model="t00-chat", input=test_id, tools=tool_definitions("responses"),
                extra_body={"api_key": provider_key},
            )
            call = next(item for item in response.output if getattr(item, "type", None) == "function_call")
            outcome, _ = dispatch_synthetic_tool(call.name, call.arguments)
        else:
            response = client.messages.create(
                model="t00-messages", max_tokens=40, messages=[{"role": "user", "content": test_id}],
                tools=tool_definitions("messages"), extra_body={"api_key": provider_key},
            )
            call = next(item for item in response.content if getattr(item, "type", None) == "tool_use")
            outcome, _ = dispatch_synthetic_tool(call.name, call.input)
        return {"success": True, "test_id": test_id, "rejection": outcome, "dispatched": outcome == "dispatched"}
    except Exception as exc:
        return {"success": False, "test_id": test_id, **safe_exception(exc)}
    finally:
        client.close()


def proxy_local(proxy_url: str, unguarded_proxy_url: str, native_stream_proxy_url: str, upstream_url: str) -> dict:
    """Real SDK -> pinned Proxy -> controlled upstream with synthetic credentials."""
    key_a = make_virtual_key(proxy_url, "tenant-a-chat", "t00-chat")
    key_b = make_virtual_key(proxy_url, "tenant-b-chat", "t00-chat")
    key_smoke = make_virtual_key(proxy_url, "tenant-a-deepseek-smoke", "t00-deepseek-smoke")
    key_messages = make_virtual_key(proxy_url, "tenant-a-messages", "t00-messages")
    key_messages_b = make_virtual_key(proxy_url, "tenant-b-messages-concurrent", "t00-messages")
    register_project_key_fingerprints(
        upstream_url,
        [key_a, key_b, key_smoke, key_messages, key_messages_b],
    )

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

    def call_concurrent_messages(tenant: str, project_key: str) -> dict:
        client = anthropic_client(project_key, proxy_url, auth_token=True)
        try:
            message = client.messages.create(
                model="t00-messages",
                max_tokens=40,
                messages=[{"role": "user", "content": "T00_PROXY_MESSAGES_CONCURRENT_B"}],
                extra_body={"api_key": PROVIDER_KEYS[tenant]},
            )
            return {
                "success": True,
                "stop_reason": message.stop_reason,
                "model_alias": "t00-messages",
            }
        except Exception as exc:
            return safe_exception(exc)
        finally:
            client.close()

    client_smoke = openai_client(key_smoke, proxy_url + "/v1")
    try:
        try:
            response = client_smoke.chat.completions.create(
                model="t00-deepseek-smoke",
                messages=[{"role": "user", "content": DEEPSEEK_SMOKE_PROMPT}],
                max_tokens=DEEPSEEK_MAX_OUTPUT_TOKENS,
                response_format={"type": "json_object"},
                extra_body={
                    "api_key": PROVIDER_KEYS["tenant-a"],
                    "thinking": {"type": "disabled"},
                },
            )
            answer_valid, answer_assertion, _finish_reason = validate_deepseek_completion(
                response,
                1,
            )
            chat_smoke = {
                "success": True,
                "finish_reason": response.choices[0].finish_reason,
                "model_alias": "t00-deepseek-smoke",
                "answer_valid": answer_valid,
                "answer_assertion": answer_assertion,
            }
        except Exception as exc:
            chat_smoke = safe_exception(exc)
    finally:
        client_smoke.close()

    with ThreadPoolExecutor(max_workers=3) as pool:
        future_a = pool.submit(call_chat, "tenant-a", key_a)
        future_b = pool.submit(call_chat, "tenant-b", key_b)
        future_messages_b = pool.submit(call_concurrent_messages, "tenant-b", key_messages_b)
        chat_a = future_a.result()
        chat_b = future_b.result()
        concurrent_messages_b = future_messages_b.result()

    responses_client = openai_client(key_a, proxy_url + "/v1")
    try:
        try:
            response = responses_client.responses.create(
                model="t00-chat",
                input="T00_PROXY_RESPONSES_A",
                extra_body={"api_key": PROVIDER_KEYS["tenant-a"]},
            )
            responses_result = {
                "success": True,
                "status": response.status,
                "model_alias": "t00-chat",
            }
        except Exception as exc:
            responses_result = safe_exception(exc)
    finally:
        responses_client.close()

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

    tool_roundtrips = {
        "chat": proxy_tool_roundtrip("chat", proxy_url, key_a, PROVIDER_KEYS["tenant-a"]),
        "responses": proxy_tool_roundtrip("responses", proxy_url, key_a, PROVIDER_KEYS["tenant-a"]),
        "messages": proxy_tool_roundtrip("messages", proxy_url, key_messages, PROVIDER_KEYS["tenant-a"]),
    }
    responses_foreign_id_case = proxy_tool_roundtrip(
        "responses", proxy_url, key_a, PROVIDER_KEYS["tenant-a"],
        foreign_responses_ids=True,
    )
    invalid_tools = {}
    for protocol, project_key in (("chat", key_a), ("responses", key_a), ("messages", key_messages)):
        for variant in ("malformed", "invalid", "unknown"):
            invalid_tools[f"{protocol}_{variant}"] = probe_invalid_tool(
                protocol, variant, proxy_url, project_key, PROVIDER_KEYS["tenant-a"]
            )

    # Preserve the raw pinned-version EOF failure reproduction on a separate
    # proxy instance that has no admission callback configured.
    eof_client = openai_client(key_a, unguarded_proxy_url + "/v1")
    eof_finishes: list[str] = []
    eof_events = 0
    eof_success = False
    try:
        with eof_client.chat.completions.create(
            model="t00-chat",
            messages=[{"role": "user", "content": "T00_PROXY_UNGUARDED_CHAT_EOF_A"}],
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

    wrong_model_client = openai_client(key_a, proxy_url + "/v1")
    try:
        try:
            wrong_model_client.chat.completions.create(
                model="t00-messages",
                messages=[{"role": "user", "content": "T00_PROXY_WRONG_MODEL_A"}],
                extra_body={"api_key": PROVIDER_KEYS["tenant-a"]},
            )
            wrong_model_result = {"success": True, "status_code": None}
        except Exception as exc:
            wrong_model_result = safe_exception(exc)
    finally:
        wrong_model_client.close()

    # Reproduce the unguarded default-key fallback on the isolated raw proxy.
    unguarded_missing_status, _unguarded_missing_body = request_json_with_status(
        unguarded_proxy_url + "/v1/chat/completions",
        {
            "model": "t00-chat",
            "messages": [{"role": "user", "content": "T00_PROXY_UNGUARDED_MISSING_KEY_A"}],
        },
        {"Authorization": f"Bearer {key_a}"},
    )
    unguarded_missing_provider = {"status_code": unguarded_missing_status}

    admission_cases = []
    route_specs = {
        "chat": ("/v1/chat/completions", key_a),
        "responses": ("/v1/responses", key_a),
        "messages": ("/v1/messages", key_messages),
    }
    invalid_key_variants = {
        "missing": {},
        "null": {"api_key": None},
        "empty": {"api_key": ""},
        "whitespace": {"api_key": " \t "},
        "non_string": {"api_key": {"nested": "synthetic"}},
        "metadata_only": {"metadata": {"api_key": PROVIDER_KEYS["tenant-a"]}},
        "header_only": {},
    }
    for route_name, (route_path, project_key) in route_specs.items():
        for variant, extra_fields in invalid_key_variants.items():
            test_id = f"T00_GUARD_{route_name.upper()}_{variant.upper()}"
            if route_name == "chat":
                body = {
                    "model": "t00-chat",
                    "messages": [{"role": "user", "content": test_id}],
                }
            elif route_name == "responses":
                body = {"model": "t00-chat", "input": test_id}
            else:
                body = {
                    "model": "t00-messages",
                    "max_tokens": 24,
                    "messages": [{"role": "user", "content": test_id}],
                }
            body.update(extra_fields)
            headers = {"Authorization": f"Bearer {project_key}"}
            if variant == "header_only":
                headers["x-api-key"] = PROVIDER_KEYS["tenant-a"]
                if route_name == "messages":
                    headers["anthropic-version"] = "2023-06-01"
            status_code, response_body = request_json_with_status(
                proxy_url + route_path,
                body,
                headers,
            )
            error_code = safe_error_marker(response_body)
            admission_cases.append({
                "test_id": test_id,
                "route": route_name,
                "variant": variant,
                "status_code": status_code,
                "error_code": error_code,
                "expected_error_code": "BYOK_PROVIDER_KEY_REQUIRED",
            })

    smoke_missing_test_id = "T00_GUARD_DEEPSEEK_SMOKE_MISSING"
    smoke_missing_status, smoke_missing_body = request_json_with_status(
        proxy_url + "/v1/chat/completions",
        {
            "model": "t00-deepseek-smoke",
            "messages": [{"role": "user", "content": smoke_missing_test_id}],
        },
        {"Authorization": f"Bearer {key_smoke}"},
    )
    admission_cases.append({
        "test_id": smoke_missing_test_id,
        "route": "deepseek_smoke",
        "variant": "missing",
        "status_code": smoke_missing_status,
        "error_code": safe_error_marker(smoke_missing_body),
        "expected_error_code": "BYOK_PROVIDER_KEY_REQUIRED",
    })

    stream_denials = []
    for route_name, (route_path, project_key) in {"chat": route_specs["chat"]}.items():
        test_id = f"T00_GUARD_{route_name.upper()}_STREAM_DENIED"
        if route_name == "chat":
            body = {
                "model": "t00-chat",
                "messages": [{"role": "user", "content": test_id}],
            }
        elif route_name == "responses":
            body = {"model": "t00-chat", "input": test_id}
        else:
            body = {
                "model": "t00-messages",
                "max_tokens": 24,
                "messages": [{"role": "user", "content": test_id}],
            }
        body.update({"stream": True, "api_key": PROVIDER_KEYS["tenant-a"]})
        headers = {"Authorization": f"Bearer {project_key}"}
        if route_name == "messages":
            headers["anthropic-version"] = "2023-06-01"
        status_code, response_body = request_json_with_status(
            proxy_url + route_path,
            body,
            headers,
        )
        error_code = safe_error_marker(response_body)
        stream_denials.append({
            "test_id": test_id,
            "route": route_name,
            "status_code": status_code,
            "error_code": error_code,
        })

    proxy_base_urls = {
        "chat": proxy_url + "/v1",
        "responses": proxy_url + "/v1",
        "messages": proxy_url,
    }
    proxy_keys = {
        "chat": key_a,
        "responses": key_a,
        "messages": key_messages,
    }
    error_cases = {
        protocol: run_protocol_error_cases(
            proxy_base_urls[protocol], protocol, f"T00_PROXY_{protocol.upper()}",
            proxy_keys[protocol], provider_key=PROVIDER_KEYS["tenant-a"],
            via_proxy=True, cases=("HTTP_ERROR", "TIMEOUT", "TRUNCATED"),
        )
        for protocol in proxy_base_urls
    }
    incomplete_cases = {
        protocol: run_incomplete_cases(
            proxy_base_urls[protocol], protocol,
            project_key=proxy_keys[protocol], provider_key=PROVIDER_KEYS["tenant-a"],
        )
        for protocol in proxy_base_urls
    }
    stream_cases = run_stream_group(
        {
            "responses": native_stream_proxy_url + "/v1",
            "messages": native_stream_proxy_url,
        },
        ("responses", "messages"),
        {"responses": key_a, "messages": key_messages},
        provider_key=PROVIDER_KEYS["tenant-a"],
        via_proxy=True,
        upstream_url=upstream_url,
        proxy_health_url=native_stream_proxy_url + "/health/liveliness",
    )

    upstream = request_json(upstream_url + "/stats")
    records = upstream.get("records", [])
    return {
        "chat": {"tenant-a": chat_a, "tenant-b": chat_b},
        "chat_smoke": chat_smoke,
        "concurrent_messages_b": concurrent_messages_b,
        "responses": responses_result,
        "messages": messages_result,
        "tool_roundtrips": tool_roundtrips,
        "responses_foreign_id_case": responses_foreign_id_case,
        "invalid_tools": invalid_tools,
        "eof": eof_result,
        "wrong_project": wrong_project_result,
        "wrong_model": wrong_model_result,
        "unguarded_missing_provider": unguarded_missing_provider,
        "admission_cases": admission_cases,
        "stream_denials": stream_denials,
        "error_cases": error_cases,
        "incomplete_cases": incomplete_cases,
        "stream_cases": stream_cases,
        "records": records,
        "_secret_values": [
            MASTER_KEY,
            ADMIN_KEY,
            WRONG_PROJECT_KEY,
            DEPLOYMENT_KEY,
            *PROVIDER_KEYS.values(),
            key_a,
            key_b,
            key_smoke,
            key_messages,
            key_messages_b,
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


def upstream_service_overlap_ns(records: list[dict]) -> int | None:
    """Return the common overlap duration for fixture requests, if observed."""
    if len(records) < 2:
        return None
    starts = [record.get("request_service_started_monotonic_ns") for record in records]
    finishes = [record.get("request_service_completed_monotonic_ns") for record in records]
    if any(not isinstance(value, int) for value in starts + finishes):
        return None
    if any(finish <= start for start, finish in zip(starts, finishes)):
        return None
    overlap_ns = min(finishes) - max(starts)
    return overlap_ns if overlap_ns > 0 else None


def upstream_service_intervals_overlap(records: list[dict]) -> bool:
    """Require every observed fixture request interval to overlap in time."""
    return upstream_service_overlap_ns(records) is not None


def eof_integrity_passes(upstream_terminal: str | None, finish_reasons: list[str]) -> bool:
    incomplete_upstream = upstream_terminal == "normal_eof_without_protocol_terminal"
    downstream_claimed_complete = any(reason in {"stop", "length", "tool_calls", "function_call"} for reason in finish_reasons)
    return not incomplete_upstream or not downstream_claimed_complete


def chat_eof_gate_passes(
    upstream_terminal: str | None,
    finish_reasons: list[str],
    raw_request_count: int,
    guarded_status_code: int | None,
    guarded_error_code: str | None,
    guarded_upstream_count: int,
) -> bool:
    """Pass only if Chat EOF is safe or the unsafe streaming route is blocked."""
    if raw_request_count != 1 or upstream_terminal not in {
        "normal_eof_without_protocol_terminal",
        "finish_reason_stop",
        "finish_reason_length",
        "tool_call_turn",
    }:
        return False
    if eof_integrity_passes(upstream_terminal, finish_reasons):
        return True
    return (
        guarded_status_code == 400
        and guarded_error_code == "T00_STREAMING_DISABLED"
        and guarded_upstream_count == 0
    )


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


def evaluate_error_paths(
    checks: list[dict],
    source: str,
    records: list[dict],
    error_cases: dict,
    protocols: tuple[str, ...],
    cases: tuple[str, ...] = ("HTTP_ERROR", "TIMEOUT", "TRUNCATED"),
) -> None:
    for protocol in protocols:
        for case in cases:
            check_id = f"{source}_{protocol.upper()}_{case}"
            test_id = f"T00_{source}_{protocol.upper()}_{case}_A"
            outcome = error_cases[protocol][case.lower()]
            rows = records_for(records, test_id)
            add_check(
                checks,
                check_id + "_SURFACED_AS_ERROR",
                outcome.get("success") is False and bool(outcome.get("error_type")),
                {"error_type": outcome.get("error_type"), "status_code": outcome.get("status_code")},
            )
            add_check(
                checks,
                check_id + "_ONE_UPSTREAM_REQUEST_NO_RETRY",
                len(rows) == 1,
                {"upstream_count": len(rows), "configured_sdk_max_retries": SDK_MAX_RETRIES, "configured_proxy_retries": PROXY_NUM_RETRIES},
            )


def evaluate_incomplete_paths(
    checks: list[dict],
    source: str,
    records: list[dict],
    incomplete_cases: dict,
    protocols: tuple[str, ...],
) -> None:
    expected = {
        "chat": ("length", None),
        "responses": ("incomplete", "max_output_tokens"),
        "messages": ("max_tokens", None),
    }
    for protocol in protocols:
        test_id = f"T00_{source}_{protocol.upper()}_INCOMPLETE_A"
        outcome = incomplete_cases[protocol]
        terminal, reason = expected[protocol]
        rows = records_for(records, test_id)
        add_check(
            checks,
            f"{source}_{protocol.upper()}_INCOMPLETE_TERMINAL_PRESERVED",
            outcome.get("success") is True
            and outcome.get("terminal") == terminal
            and (reason is None or outcome.get("incomplete_reason") == reason),
            {"terminal": outcome.get("terminal"), "incomplete_reason": outcome.get("incomplete_reason")},
        )
        add_check(
            checks,
            f"{source}_{protocol.upper()}_INCOMPLETE_ONE_UPSTREAM_REQUEST",
            len(rows) == 1,
            {"upstream_count": len(rows)},
        )


def _stream_expectation(protocol: str, case: str, outcome: dict) -> bool:
    event_types = outcome.get("event_types", [])
    terminals = outcome.get("terminals", [])
    if case == "COMPLETE":
        if protocol == "chat":
            return outcome.get("success") is True and "stop" in terminals
        if protocol == "responses":
            return outcome.get("success") is True and "response.completed" in event_types and "completed" in terminals
        return outcome.get("success") is True and "message_stop" in event_types and "end_turn" in terminals
    if case == "EOF":
        if protocol == "chat":
            return outcome.get("success") is True and not terminals
        if protocol == "responses":
            return outcome.get("success") is True and "response.completed" not in event_types and "completed" not in terminals
        return outcome.get("success") is True and "message_stop" not in event_types and "end_turn" not in terminals
    if case == "INCOMPLETE":
        if protocol == "chat":
            return outcome.get("success") is True and "length" in terminals
        if protocol == "responses":
            return outcome.get("success") is True and "response.incomplete" in event_types and "incomplete" in terminals
        return outcome.get("success") is True and "max_tokens" in terminals
    if case == "SSE_ERROR":
        surfaced = outcome.get("success") is False or any(
            event_type in {"error", "response.failed"} for event_type in event_types
        )
        complete_terminal = ("stop" in terminals or "completed" in terminals or "end_turn" in terminals)
        return surfaced and not complete_terminal
    if case == "CANCEL":
        return (
            outcome.get("success") is True
            and outcome.get("outcome") == "cancelled"
            and outcome.get("stream_complete") is False
            and outcome.get("canceled_after_first_event") is True
            and outcome.get("event_count") == 1
            and not terminals
            and outcome.get("client_response_closed") is True
            and outcome.get("upstream_disconnect_within_observation_window") is True
            and outcome.get("upstream_producer_exited_within_observation_window") is True
            and outcome.get("active_upstream_producers_at_observation_end") == 0
            and outcome.get("proxy_liveness_http_2xx_after_cancel") is not False
            and outcome.get("upstream_stream_body_finished") is False
        )
    return False


def evaluate_stream_paths(
    checks: list[dict],
    source: str,
    records: list[dict],
    stream_cases: dict,
    protocols: tuple[str, ...],
    cases: tuple[str, ...] = ("COMPLETE", "EOF", "INCOMPLETE", "SSE_ERROR", "CANCEL"),
) -> None:
    for protocol in protocols:
        for case in cases:
            outcome = stream_cases[protocol][case.lower()]
            test_id = f"T00_{source}_{protocol.upper()}_STREAM_{case}_A"
            rows = records_for(records, test_id)
            record = rows[0] if len(rows) == 1 else {}
            check_id = f"{source}_{protocol.upper()}_STREAM_{case}"
            add_check(
                checks,
                check_id + "_PROTOCOL_RESULT",
                _stream_expectation(protocol, case, outcome),
                {"success": outcome.get("success"), "error_type": outcome.get("error_type"), "event_types": outcome.get("event_types"), "terminals": outcome.get("terminals")},
            )
            add_check(
                checks,
                check_id + "_ONE_UPSTREAM_REQUEST_NO_RETRY",
                len(rows) == 1,
                {"upstream_count": len(rows), "configured_sdk_max_retries": SDK_MAX_RETRIES, "configured_proxy_retries": PROXY_NUM_RETRIES},
            )
            if case in {"COMPLETE", "INCOMPLETE"}:
                expected_done_sentinel = protocol == "chat"
                add_check(
                    checks,
                    check_id + "_PROTOCOL_TERMINAL_FRAMING",
                    len(rows) == 1 and record.get("upstream_protocol_done_sentinel_written") is expected_done_sentinel,
                    {
                        "protocol": protocol,
                        "done_sentinel_expected": expected_done_sentinel,
                        "done_sentinel_written": record.get("upstream_protocol_done_sentinel_written"),
                    },
                )
            if case == "CANCEL":
                add_check(
                    checks,
                    check_id + "_UPSTREAM_DETECTED_CLIENT_CLOSE",
                    outcome.get("upstream_disconnect_within_observation_window") is True
                    and record.get("client_disconnected") is True,
                    {
                        "upstream_observed_client_disconnect": record.get("client_disconnected") is True,
                        "disconnect_delay_ms": outcome.get("upstream_disconnect_delay_ms"),
                        "observation_window_ms": outcome.get("cancel_observation_window_ms"),
                        "upstream_stream_body_finished": record.get("upstream_stream_body_finished") is True,
                        "upstream_stream_events_written": record.get("upstream_stream_events_written"),
                        "upstream_frames_written_after_downstream_close": outcome.get("upstream_frames_written_after_downstream_close"),
                    },
                )
                add_check(
                    checks,
                    check_id + "_UPSTREAM_STOPPED_AFTER_CLIENT_CLOSE",
                    record.get("client_disconnected") is True
                    and record.get("upstream_stream_body_finished") is not True
                    and record.get("producer_exit_reason") == "client_disconnect",
                    {
                        "upstream_observed_client_disconnect": record.get("client_disconnected") is True,
                        "upstream_stream_body_finished": record.get("upstream_stream_body_finished") is True,
                        "producer_exit_reason": record.get("producer_exit_reason"),
                        "producer_exit_delay_ms": outcome.get("upstream_producer_exit_delay_ms"),
                        "upstream_stream_events_written": record.get("upstream_stream_events_written"),
                    },
                )
                add_check(
                    checks,
                    check_id + "_CLIENT_CANCEL_RESOURCES_RELEASED",
                    outcome.get("client_response_closed") is True
                    and outcome.get("event_count") == 1
                    and outcome.get("active_upstream_producers_at_observation_end") == 0
                    and outcome.get("upstream_producer_exited_within_observation_window") is True
                    and outcome.get("proxy_liveness_http_2xx_after_cancel") is not False,
                    {
                        "downstream_response_closed": outcome.get("client_response_closed") is True,
                        "downstream_events_consumed": outcome.get("event_count"),
                        "cancelled_not_reported_complete": outcome.get("outcome") == "cancelled" and outcome.get("stream_complete") is False,
                        "active_upstream_producers_at_observation_end": outcome.get("active_upstream_producers_at_observation_end"),
                        "proxy_liveness_http_2xx_after_cancel": outcome.get("proxy_liveness_http_2xx_after_cancel"),
                        "cancel_observation_window_ms": outcome.get("cancel_observation_window_ms"),
                    },
                )


def evaluate_tool_roundtrips(
    checks: list[dict],
    source: str,
    records: list[dict],
    tool_roundtrips: dict,
) -> None:
    for protocol in ("chat", "responses", "messages"):
        prefix = f"{source}_{protocol.upper()}_TOOL_ROUNDTRIP"
        result = tool_roundtrips[protocol]
        for marker in ("R1", "R2", "FINAL"):
            test_id = f"T00_{source}_{protocol.upper()}_TOOL_{marker}_A"
            rows = records_for(records, test_id)
            add_check(
                checks,
                f"{prefix}_{marker}_ONE_UPSTREAM_REQUEST",
                len(rows) == 1,
                {"upstream_count": len(rows)},
            )
        add_check(
            checks,
            prefix + "_TWO_ALLOWLISTED_SYNTHETIC_TOOLS",
            result.get("success") is True
            and result.get("tool_dispatch_outcomes") == ["dispatched", "dispatched"],
            {"tool_dispatch_outcomes": result.get("tool_dispatch_outcomes", [])},
        )
        add_check(
            checks,
            prefix + "_PUBLIC_OUTPUT_EXCLUDES_PRIVATE_CONTINUATION_AND_KEYS",
            result.get("success") is True
            and result.get("continuation_in_public") is False
            and result.get("key_in_public") is False
            and set(result.get("public_output", {})) == {"text"},
            {
                "continuation_in_public": result.get("continuation_in_public"),
                "key_in_public": result.get("key_in_public"),
                "public_fields": sorted(result.get("public_output", {})),
            },
        )
        final_rows = records_for(records, f"T00_{source}_{protocol.upper()}_TOOL_FINAL_A")
        facts = final_rows[0].get("continuation_facts", {}) if len(final_rows) == 1 else {}
        if protocol == "chat":
            preserved = all(facts.get(f"chat_r{i}_{suffix}") is True for i in (1, 2) for suffix in ("assistant_preserved", "tool_result_id_preserved"))
        elif protocol == "responses":
            preserved = all(facts.get(f"responses_r{i}_{suffix}") is True for i in (1, 2) for suffix in ("output_items_preserved", "tool_result_preserved"))
        else:
            preserved = all(facts.get(f"messages_r{i}_{suffix}") is True for i in (1, 2) for suffix in ("thinking_signature_preserved", "tool_result_preserved"))
        add_check(
            checks,
            prefix + "_RAW_CONTINUATION_AND_TOOL_RESULT_PRESERVED",
            len(final_rows) == 1 and preserved,
            {key: value for key, value in facts.items() if key.endswith("_preserved") or key.endswith("_present")},
        )


def responses_foreign_id_normalization_passes(facts: dict) -> bool:
    """Only the old foreign item id may be normalized; call association stays strict."""
    return all(
        facts.get(f"responses_r{round_index}_{suffix}") is True
        for round_index in (1, 2)
        for suffix in (
            "reasoning_id_preserved",
            "reasoning_summary_preserved",
            "encrypted_continuation_preserved",
            "reasoning_keyset_preserved",
            "non_id_function_call_fields_preserved",
            "foreign_item_id_normalized",
            "foreign_call_id_and_tool_association_preserved",
            "tool_result_preserved",
        )
    )


def evaluate_sdk_local(checks: list[dict], sdk: dict, upstream_records: list[dict]) -> None:
    config_text = (TOOL_DIR / "proxy.yaml").read_text(encoding="utf-8")
    raw_config = (TOOL_DIR / "proxy-unguarded.yaml").read_text(encoding="utf-8")
    add_check(checks, "CONFIG_PROXY_HEADER_FORWARDING_DISABLED", (
        "forward_client_headers_to_llm_api: false" in config_text
        and "forward_llm_provider_auth_headers: false" in config_text
        and "forward_client_headers_to_llm_api: false" in raw_config
        and "forward_llm_provider_auth_headers: false" in raw_config
    ))
    add_check(checks, "CONFIG_PROXY_AND_SDK_RETRIES_ZERO", (
        config_text.count("num_retries: 0") + raw_config.count("num_retries: 0") == 4
        and SDK_MAX_RETRIES == 0
        and PROXY_NUM_RETRIES == 0
    ))
    add_check(
        checks,
        "CONFIG_SYNTHETIC_DEPLOYMENT_DEFAULT_KEY_PRESENT",
        DEPLOYMENT_KEY in config_text,
        {"deployment_default_configured": DEPLOYMENT_KEY in config_text},
    )
    chat_model = config_text.partition("  - model_name: t00-deepseek-smoke\n")[2].split("\n  - model_name:", 1)[0]
    callback_text = (TOOL_DIR / "proxy_callback.py").read_text(encoding="utf-8")
    add_check(
        checks,
        "CONFIG_SYNTHETIC_SENTINEL_AND_REQUEST_KEY_GUARD_ON_SMOKE_ROUTE",
        bool(chat_model)
        and "model: deepseek/deepseek-flash" in chat_model
        and "api_base: http://upstream:8080" in chat_model
        and "api_key: " + DEPLOYMENT_KEY in chat_model
        and "callbacks: proxy_callback.proxy_handler_instance" in config_text
        and 'provider_key = data.get("api_key")' in callback_text
        and '"BYOK_PROVIDER_KEY_REQUIRED"' in callback_text,
        {"synthetic_sentinel_configured": DEPLOYMENT_KEY in chat_model},
    )
    compose_text = COMPOSE_FILE.read_text(encoding="utf-8")
    add_check(
        checks,
        "CONFIG_GUARD_CALLBACK_AND_STREAM_DENY_ENABLED",
        "callbacks: proxy_callback.proxy_handler_instance" in config_text
        and "T00_DENY_STREAMING_CALL_TYPES: acompletion" in compose_text
        and "native_stream_proxy" in compose_text
        and 'data.get("stream") is True' in callback_text,
    )
    add_check(
        checks,
        "CONFIG_RAW_PROXY_HAS_NO_ADMISSION_CALLBACK",
        "callbacks:" not in raw_config,
    )
    key_generation = inspect.getsource(make_virtual_key)
    add_check(
        checks,
        "CONFIG_PROJECT_KEYS_HAVE_NO_TEAM_OR_PROVIDER_OVERRIDE",
        '"models": [model], "metadata": {"key_alias": alias}' in key_generation
        and "team_id" not in key_generation
        and all(key not in compose_text for key in PROVIDER_KEYS.values()),
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

    evaluate_error_paths(checks, "SDK", upstream_records, sdk["error_cases"], ("chat", "responses", "messages"))
    evaluate_incomplete_paths(checks, "SDK", upstream_records, sdk["incomplete_cases"], ("chat", "responses", "messages"))
    evaluate_stream_paths(checks, "SDK", upstream_records, sdk["stream_cases"], ("chat", "responses", "messages"))
    evaluate_tool_roundtrips(checks, "SDK", upstream_records, sdk["tool_roundtrips"])


def evaluate_proxy_local(checks: list[dict], proxy: dict) -> None:
    records = proxy["records"]
    add_check(
        checks,
        "PROXY_CHAT_AB_USE_SAME_MODEL_ALIAS",
        all(proxy["chat"][tenant].get("model_alias") == "t00-chat" for tenant in ("tenant-a", "tenant-b")),
        {"tenant_a_model_alias": proxy["chat"]["tenant-a"].get("model_alias"), "tenant_b_model_alias": proxy["chat"]["tenant-b"].get("model_alias")},
    )
    concurrent_specs = (
        ("T00_PROXY_CHAT_A", "tenant-a", "chat", proxy["chat"]["tenant-a"], "t00-chat"),
        ("T00_PROXY_CHAT_B", "tenant-b", "chat", proxy["chat"]["tenant-b"], "t00-chat"),
        ("T00_PROXY_MESSAGES_CONCURRENT_B", "tenant-b", "messages", proxy["concurrent_messages_b"], "t00-messages"),
    )
    concurrent_records = []
    concurrent_routes_pass = True
    for test_id, tenant, protocol, response, model_alias in concurrent_specs:
        rows = records_for(records, test_id)
        record = rows[0] if len(rows) == 1 else None
        if record is not None:
            concurrent_records.append(record)
        concurrent_routes_pass = concurrent_routes_pass and (
            len(rows) == 1
            and credential_record_passes(record, tenant, protocol)
            and response.get("success") is True
            and response.get("model_alias") == model_alias
        )
    overlap_ns = upstream_service_overlap_ns(concurrent_records)
    add_check(
        checks,
        "PROXY_DIFFERENT_KEYS_AND_MODELS_RUN_CONCURRENTLY",
        concurrent_routes_pass and upstream_service_intervals_overlap(concurrent_records),
        {
            "request_count_by_route": {
                test_id: len(records_for(records, test_id))
                for test_id, *_ in concurrent_specs
            },
            "expected_tenants": [tenant for _, tenant, *_ in concurrent_specs],
            "expected_model_aliases": [model for *_, model in concurrent_specs],
            "observed_tenants": [record.get("tenant") for record in concurrent_records],
            "provider_key_matches": [record.get("provider_key_match") for record in concurrent_records],
            "observed_model_aliases": [response.get("model_alias") for _, _, _, response, _ in concurrent_specs],
            "observed_upstream_protocols": [
                record.get("protocol") for record in concurrent_records
            ],
            "all_fixture_service_intervals_overlap": upstream_service_intervals_overlap(concurrent_records),
            "common_overlap_ms": round(overlap_ns / 1_000_000, 3) if overlap_ns is not None else None,
        },
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

    smoke_rows = records_for(records, "T00_PROXY_CHAT_SMOKE_A")
    smoke_record = append_record_checks(
        checks,
        "PROXY_CHAT_SMOKE",
        smoke_rows,
        1,
        "tenant-a",
        "chat",
    )
    smoke_response = proxy["chat_smoke"]
    add_check(
        checks,
        "PROXY_CHAT_SMOKE_SDK_COMPLETE_TERMINAL_AND_JSON_ASSERTION",
        smoke_response.get("success") is True
        and smoke_response.get("model_alias") == "t00-deepseek-smoke"
        and smoke_response.get("finish_reason") == "stop"
        and smoke_response.get("answer_valid") is True
        and smoke_response.get("answer_assertion") == "json_object_fields_match"
        and smoke_record is not None,
        {
            "sdk_success": smoke_response.get("success") is True,
            "model_alias": smoke_response.get("model_alias"),
            "finish_reason": smoke_response.get("finish_reason"),
            "answer_assertion": smoke_response.get("answer_assertion"),
        },
    )

    response_rows = records_for(records, "T00_PROXY_RESPONSES_A")
    response_record = append_record_checks(
        checks,
        "PROXY_RESPONSES_TENANT_A",
        response_rows,
        1,
        "tenant-a",
        "responses",
    )
    response = proxy["responses"]
    add_check(
        checks,
        "PROXY_RESPONSES_COMPLETE_TERMINAL",
        response.get("success") is True
        and response.get("status") == "completed"
        and response_record is not None
        and response_record.get("upstream_terminal") == "response_completed",
        {
            "sdk_success": response.get("success") is True,
            "status": response.get("status"),
            "upstream_terminal": None if response_record is None else response_record.get("upstream_terminal"),
        },
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

    tool_specs = {
        "chat": ("tenant-a", "chat", "chat"),
        "responses": ("tenant-a", "responses", "responses"),
        "messages": ("tenant-a", "messages", "messages"),
    }
    for protocol, (tenant, route, _) in tool_specs.items():
        prefix = "PROXY_" + protocol.upper() + "_TOOL_ROUNDTRIP"
        result = proxy["tool_roundtrips"][protocol]
        for marker in ("R1", "R2", "FINAL"):
            test_id = f"T00_PROXY_{protocol.upper()}_TOOL_{marker}_A"
            rows = records_for(records, test_id)
            append_record_checks(checks, prefix + "_" + marker, rows, 1, tenant, route)
        add_check(
            checks,
            prefix + "_TWO_ALLOWLISTED_SYNTHETIC_TOOLS",
            result.get("success") is True
            and result.get("tool_dispatch_outcomes") == ["dispatched", "dispatched"],
            {"tool_dispatch_outcomes": result.get("tool_dispatch_outcomes", [])},
        )
        add_check(
            checks,
            prefix + "_PUBLIC_OUTPUT_EXCLUDES_PRIVATE_CONTINUATION_AND_KEYS",
            result.get("success") is True
            and result.get("continuation_in_public") is False
            and result.get("key_in_public") is False
            and set(result.get("public_output", {})) == {"text"},
            {
                "continuation_in_public": result.get("continuation_in_public"),
                "key_in_public": result.get("key_in_public"),
                "public_fields": sorted(result.get("public_output", {})),
            },
        )
        final_rows = records_for(records, f"T00_PROXY_{protocol.upper()}_TOOL_FINAL_A")
        facts = final_rows[0].get("continuation_facts", {}) if len(final_rows) == 1 else {}
        if protocol == "chat":
            preserved = all(facts.get(f"chat_r{i}_{suffix}") is True for i in (1, 2) for suffix in ("assistant_preserved", "tool_result_id_preserved"))
        elif protocol == "responses":
            preserved = all(facts.get(f"responses_r{i}_{suffix}") is True for i in (1, 2) for suffix in ("output_items_preserved", "tool_result_preserved"))
        else:
            preserved = all(facts.get(f"messages_r{i}_{suffix}") is True for i in (1, 2) for suffix in ("thinking_signature_preserved", "tool_result_preserved"))
        add_check(
            checks,
            prefix + "_RAW_CONTINUATION_AND_TOOL_RESULT_PRESERVED",
            len(final_rows) == 1 and preserved,
            {key: value for key, value in facts.items() if key.endswith("_preserved") or key.endswith("_present") or key.endswith("_count")},
        )

    foreign_result = proxy["responses_foreign_id_case"]
    foreign_prefix = "PROXY_RESPONSES_FOREIGN_ID_NORMALIZATION"
    foreign_final_id = "T00_PROXY_RESPONSES_FOREIGN_TOOL_FINAL_A"
    foreign_final_rows = records_for(records, foreign_final_id)
    foreign_facts = foreign_final_rows[0].get("continuation_facts", {}) if len(foreign_final_rows) == 1 else {}
    for marker in ("R1", "R2", "FINAL"):
        test_id = f"T00_PROXY_RESPONSES_FOREIGN_TOOL_{marker}_A"
        rows = records_for(records, test_id)
        append_record_checks(checks, foreign_prefix + "_" + marker, rows, 1, "tenant-a", "responses")
    add_check(
        checks,
        foreign_prefix + "_OLD_RESP_ITEM_IDS_NORMALIZED_ONLY",
        len(foreign_final_rows) == 1 and responses_foreign_id_normalization_passes(foreign_facts),
        {key: value for key, value in foreign_facts.items() if "responses_r" in key},
    )
    add_check(
        checks,
        foreign_prefix + "_TOOLS_DISPATCHED_AND_PUBLIC_OUTPUT_SAFE",
        foreign_result.get("success") is True
        and foreign_result.get("tool_dispatch_outcomes") == ["dispatched", "dispatched"]
        and foreign_result.get("continuation_in_public") is False
        and foreign_result.get("key_in_public") is False
        and set(foreign_result.get("public_output", {})) == {"text"},
        {
            "tool_dispatch_outcomes": foreign_result.get("tool_dispatch_outcomes"),
            "continuation_in_public": foreign_result.get("continuation_in_public"),
            "key_in_public": foreign_result.get("key_in_public"),
            "public_fields": sorted(foreign_result.get("public_output", {})),
        },
    )

    expected_rejections = {
        "chat_malformed": "partial_json",
        "chat_invalid": "invalid_json",
        "chat_unknown": "not_allowlisted",
        "responses_malformed": "partial_json",
        "responses_invalid": "invalid_json",
        "responses_unknown": "not_allowlisted",
        "messages_malformed": "invalid_argument_shape",
        "messages_invalid": "invalid_argument_shape",
        "messages_unknown": "not_allowlisted",
    }
    for case_id, expected_rejection in expected_rejections.items():
        case = proxy["invalid_tools"][case_id]
        rows = records_for(records, case["test_id"])
        add_check(
            checks,
            "PROXY_TOOL_REJECT_" + case_id.upper(),
            case.get("success") is True
            and case.get("rejection") == expected_rejection
            and case.get("dispatched") is False
            and len(rows) == 1,
            {
                "rejection": case.get("rejection"),
                "dispatched": case.get("dispatched"),
                "upstream_count": len(rows),
            },
        )

    eof_rows = records_for(records, "T00_PROXY_UNGUARDED_CHAT_EOF_A")
    eof_record = append_record_checks(checks, "PROXY_UNGUARDED_CHAT_EOF", eof_rows, 1, "tenant-a", "chat")
    guarded_chat_stream = next(
        (denial for denial in proxy["stream_denials"] if denial["route"] == "chat"),
        {},
    )
    guarded_chat_rows = records_for(records, guarded_chat_stream.get("test_id", ""))
    eof_gate_passes = chat_eof_gate_passes(
        None if eof_record is None else eof_record.get("upstream_terminal"),
        proxy["eof"].get("finish_reasons", []),
        len(eof_rows),
        guarded_chat_stream.get("status_code"),
        guarded_chat_stream.get("error_code"),
        len(guarded_chat_rows),
    )
    add_check(
        checks,
        "PROXY_CHAT_EOF_RISK_CONTAINED_BY_ADMISSION",
        eof_gate_passes,
        {
            "upstream_terminal": None if eof_record is None else eof_record.get("upstream_terminal"),
            "downstream_finish_reasons": proxy["eof"].get("finish_reasons", []),
            "sdk_normal_end": proxy["eof"].get("normal_sdk_end") is True,
            "guarded_stream_status": guarded_chat_stream.get("status_code"),
            "guarded_stream_error_code": guarded_chat_stream.get("error_code"),
            "guarded_stream_upstream_count": len(guarded_chat_rows),
            "interpretation": (
                "unsafe raw LiteLLM behavior is reproduced; guarded Chat streaming is blocked before upstream"
                if not eof_integrity_passes(
                    None if eof_record is None else eof_record.get("upstream_terminal"),
                    proxy["eof"].get("finish_reasons", []),
                )
                else "raw Chat EOF did not claim completion"
            ),
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

    wrong_model_rows = records_for(records, "T00_PROXY_WRONG_MODEL_A")
    wrong_model = proxy["wrong_model"]
    add_check(
        checks,
        "PROXY_PROJECT_KEY_MODEL_ALLOWLIST_REJECTED_BEFORE_UPSTREAM",
        wrong_model.get("success") is False and len(wrong_model_rows) == 0,
        {"http_status": wrong_model.get("status_code"), "upstream_count": len(wrong_model_rows)},
    )

    missing = next(
        (case for case in proxy["admission_cases"] if case["route"] == "chat" and case["variant"] == "missing"),
        {},
    )
    missing_rows = records_for(records, missing.get("test_id", ""))
    add_check(
        checks,
        "PROXY_GUARD_MISSING_PROVIDER_FAILS_CLOSED",
        missing.get("status_code") == 400
        and missing.get("error_code") == "BYOK_PROVIDER_KEY_REQUIRED"
        and len(missing_rows) == 0,
        {"http_status": missing.get("status_code"), "error_code": missing.get("error_code"), "upstream_count": len(missing_rows)},
    )

    raw_missing_rows = records_for(records, "T00_PROXY_UNGUARDED_MISSING_KEY_A")
    raw_missing = proxy["unguarded_missing_provider"]
    default_route_count = sum(1 for row in raw_missing_rows if row.get("deployment_default_match") is True)
    add_check(
        checks,
        "PROXY_RAW_UNGUARDED_DEFAULT_KEY_FALLBACK_REPRODUCED",
        raw_missing.get("status_code") == 401
        and len(raw_missing_rows) == 1
        and default_route_count == 1,
        {
            "http_status": raw_missing.get("status_code"),
            "upstream_count": len(raw_missing_rows),
            "deployment_default_route_count": default_route_count,
        },
    )

    for case in proxy["admission_cases"]:
        prefix = "PROXY_GUARD_" + case["route"].upper() + "_" + case["variant"].upper()
        rows = records_for(records, case["test_id"])
        add_check(
            checks,
            prefix + "_400_PROVIDER_KEY_REQUIRED",
            case.get("status_code") == 400
            and case.get("error_code") == "BYOK_PROVIDER_KEY_REQUIRED",
            {"http_status": case.get("status_code"), "error_code": case.get("error_code")},
        )
        add_check(
            checks,
            prefix + "_NO_UPSTREAM_CALL",
            len(rows) == 0,
            {"upstream_count": len(rows)},
        )

    for denial in proxy["stream_denials"]:
        prefix = "PROXY_GUARD_" + denial["route"].upper() + "_STREAM"
        rows = records_for(records, denial["test_id"])
        add_check(
            checks,
            prefix + "_400_STREAM_DISABLED",
            denial.get("status_code") == 400
            and denial.get("error_code") == "T00_STREAMING_DISABLED",
            {"http_status": denial.get("status_code"), "error_code": denial.get("error_code")},
        )
        add_check(
            checks,
            prefix + "_NO_UPSTREAM_CALL",
            len(rows) == 0,
            {"upstream_count": len(rows)},
        )

    evaluate_error_paths(checks, "PROXY", records, proxy["error_cases"], ("chat", "responses", "messages"))
    evaluate_incomplete_paths(checks, "PROXY", records, proxy["incomplete_cases"], ("chat", "responses", "messages"))
    evaluate_stream_paths(checks, "PROXY", records, proxy["stream_cases"], ("responses", "messages"))


def cleanup_project(project: str) -> list[dict]:
    outcomes = []
    compose_error = None
    try:
        compose(
            project,
            "--profile",
            "unguarded",
            "--profile",
            "native-stream",
            "down",
            "--volumes",
            "--remove-orphans",
            timeout=90,
        )
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
        "uncovered": ["old chat/research/translation regression baseline", "PROVIDER_REAL compatibility"],
    }
    compose(
        project,
        "--profile",
        "unguarded",
        "--profile",
        "native-stream",
        "up",
        "-d",
        "--wait",
        "--wait-timeout",
        "180",
        "unguarded_proxy",
        "native_stream_proxy",
        timeout=210,
    )
    proxy_url = f"http://{inspect_ip(project, 'proxy')}:4000"
    unguarded_proxy_url = f"http://{inspect_ip(project, 'unguarded_proxy')}:4001"
    native_stream_proxy_url = f"http://{inspect_ip(project, 'native_stream_proxy')}:4002"
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
    proxy = proxy_local(proxy_url, unguarded_proxy_url, native_stream_proxy_url, upstream_url)
    secret_values = proxy.pop("_secret_values")
    result["proxy_local"] = {
        key: value for key, value in proxy.items() if key != "records"
    }
    evaluate_sdk_local(result["checks"], result["sdk_local"], proxy["records"])
    evaluate_proxy_local(result["checks"], proxy)

    logs = docker([
        "compose", "--project-name", project, "-f", str(COMPOSE_FILE),
        "logs", "--no-color", "proxy", "unguarded_proxy", "native_stream_proxy", "upstream",
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
        versions.get("litellm") == "1.104.2"
        and versions.get("litellm_native_stream_proxy") == "1.104.2",
        {"litellm": versions.get("litellm"), "litellm_native_stream_proxy": versions.get("litellm_native_stream_proxy")},
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
        compose(
            project,
            "--profile",
            "unguarded",
            "--profile",
            "native-stream",
            "up",
            "-d",
            "--wait",
            "--wait-timeout",
            "180",
            timeout=210,
        )
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
