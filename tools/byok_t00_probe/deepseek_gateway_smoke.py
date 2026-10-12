#!/usr/bin/env python3
"""Opt-in, one-request DeepSeek diagnostic through an ephemeral LiteLLM Proxy.

The local Proxy is created for this invocation only. A project virtual key is
generated and scoped to one model alias; the user's provider key is entered
with getpass and sent only in the single OpenAI SDK request body. No key or
prompt is written to disk or printed. This is an early non-streaming smoke,
not the T13 provider capability matrix or a production deployment test.
"""

from __future__ import annotations

import argparse
import getpass
import httpx2
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from openai import APIStatusError, OpenAI

from deepseek_smoke import (
    EXPECTED_ANSWER,
    MAX_OUTPUT_TOKENS,
    MAX_RETRIES,
    MODEL,
    PROMPT,
    TIMEOUT_SECONDS,
    _usage_fields,
    _valid_completion,
)


TOOL_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = TOOL_DIR.parents[1]
LITELLM_IMAGE = (
    "ghcr.io/berriai/litellm@"
    "sha256:3d88bd757134a00e8c00237b85a021ab1f6d54abb9c1df750f411dbe7256a500"
)
POSTGRES_IMAGE = (
    "postgres@sha256:721873c34ceb9f8d8fc265984940dc982404c105f19ad51be9fdc5970a6080ea"
)
MODEL_ALIAS = "t00-deepseek-smoke"
PROJECT_KEY_BUDGET_USD = 0.01
PROJECT_KEY_RPM_LIMIT = 1
PROJECT_KEY_TPM_LIMIT = 512
PROJECT_KEY_MAX_PARALLEL = 1
PROJECT_KEY_DURATION = "1h"
PROXY_START_TIMEOUT_SECONDS = 180
PROXY_READY_TIMEOUT_SECONDS = 30


def emit(status: str, **details: object) -> None:
    print(json.dumps({"gateway_smoke": status, **details}, sort_keys=True))


class ProxySetupError(RuntimeError):
    """Safe, static local Proxy setup failure marker."""


@dataclass
class ProxySession:
    project_name: str
    compose_file: Path
    private_dir: Path
    base_url: str
    master_key: str
    project_key: str


def _write_private_file(path: Path, content: str) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise


def _compose_yaml(private_dir: Path) -> str:
    repo = str(REPOSITORY_ROOT)
    files = {
        "postgres_password": private_dir / "postgres_password",
        "litellm_master_key": private_dir / "litellm_master_key",
        "litellm_salt_key": private_dir / "litellm_salt_key",
        "proxy_config": private_dir / "proxy.yaml",
    }
    return f"""services:
  db:
    image: {POSTGRES_IMAGE}
    environment:
      POSTGRES_DB: litellm
      POSTGRES_USER: t00_smoke
      POSTGRES_PASSWORD_FILE: /run/secrets/postgres_password
    secrets:
      - postgres_password
    tmpfs:
      - /var/lib/postgresql/data:rw,size=256m,mode=0700
    shm_size: 64m
    healthcheck:
      test: [\"CMD-SHELL\", \"pg_isready -U t00_smoke -d litellm -h 127.0.0.1\"]
      interval: 2s
      timeout: 2s
      retries: 45
    networks:
      - control
    security_opt:
      - no-new-privileges:true

  proxy:
    image: {LITELLM_IMAGE}
    user: \"1000:1000\"
    entrypoint: [\"/bin/sh\", \"/fixtures/entrypoint.sh\"]
    command: [\"--config\", \"/fixtures/proxy.yaml\", \"--port\", \"4000\"]
    environment:
      HOME: /tmp
      XDG_CACHE_HOME: /tmp/cache
      PYTHONPATH: /fixtures
      POSTGRES_HOST: db
      POSTGRES_PORT: \"5432\"
      POSTGRES_DB: litellm
      POSTGRES_USER: t00_smoke
      T00_DENY_STREAMING_CALL_TYPES: acompletion
    volumes:
      - {repo}/tools/byok_t00_probe/deepseek_smoke_entrypoint.sh:/fixtures/entrypoint.sh:ro
      - {repo}/tools/byok_t00_probe/proxy_callback.py:/fixtures/proxy_callback.py:ro
      - {files['proxy_config']}:/fixtures/proxy.yaml:ro
    secrets:
      - postgres_password
      - litellm_master_key
      - litellm_salt_key
    ports:
      - \"127.0.0.1::4000\"
    networks:
      - control
      - provider_egress
    depends_on:
      db:
        condition: service_healthy
    healthcheck:
      test: [\"CMD\", \"python\", \"-c\", \"import urllib.request; urllib.request.urlopen('http://127.0.0.1:4000/health/liveliness', timeout=3)\"]
      interval: 3s
      timeout: 4s
      retries: 60
      start_period: 45s
    read_only: true
    tmpfs:
      - /tmp:rw,size=512m,mode=1777
    cap_drop: [ALL]
    security_opt:
      - no-new-privileges:true
    mem_limit: 3g
    cpus: 2.0
    logging:
      driver: json-file
      options:
        max-size: 10m
        max-file: \"2\"

networks:
  control:
    internal: true
  provider_egress:
    driver: bridge

secrets:
  postgres_password:
    file: {files['postgres_password']}
  litellm_master_key:
    file: {files['litellm_master_key']}
  litellm_salt_key:
    file: {files['litellm_salt_key']}
"""


def _proxy_config_yaml() -> str:
    return """model_list:
  - model_name: t00-deepseek-smoke
    litellm_params:
      model: deepseek/deepseek-flash
      api_base: https://api.deepseek.com
      # LiteLLM v1.104.2 requires an initialized model api_key. This fixed,
      # nonfunctional sentinel is never a provider credential. The callback
      # rejects requests missing a request-scoped api_key before routing.
      api_key: sk-t00-deployment-default-synthetic

general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
  database_url: os.environ/DATABASE_URL
  allow_requests_on_db_unavailable: false
  store_prompts_in_spend_logs: false
  disable_master_key_return: true

router_settings:
  num_retries: 0
  fallbacks: []

litellm_settings:
  callbacks: proxy_callback.proxy_handler_instance
  num_retries: 0
  cache: false
  turn_off_message_logging: true
  redact_messages_in_exceptions: true
  global_disable_no_log_param: true
  set_verbose: false
  json_logs: true
  default_key_generate_params:
    max_budget: 0.01
    budget_duration: 1d
    rpm_limit: 1
    tpm_limit: 512
    max_parallel_requests: 1
    duration: 1h
  upperbound_key_generate_params:
    max_budget: 0.01
    budget_duration: 1d
    rpm_limit: 1
    tpm_limit: 512
    max_parallel_requests: 1
    duration: 1h
"""


def docker_command(args: list[str], *, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    docker_path = shutil.which("docker")
    if docker_path is None:
        raise ProxySetupError("docker_cli_unavailable")
    try:
        result = subprocess.run(
            [docker_path, "--context", "default", *args],
            cwd=TOOL_DIR,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise ProxySetupError("docker_command_failed") from None
    if result.returncode != 0:
        raise ProxySetupError("docker_command_failed")
    return result


def _compose(session: ProxySession, *args: str, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return docker_command(
        [
            "compose",
            "--project-name",
            session.project_name,
            "-f",
            str(session.compose_file),
            *args,
        ],
        timeout=timeout,
    )


def _local_port(binding: str) -> int:
    address, separator, port_text = binding.strip().rpartition(":")
    if not separator or address.strip("[]") != "127.0.0.1":
        raise ProxySetupError("proxy_port_not_loopback_bound")
    try:
        port = int(port_text)
    except ValueError:
        raise ProxySetupError("proxy_port_invalid") from None
    if not 1 <= port <= 65535:
        raise ProxySetupError("proxy_port_invalid")
    return port


def _wait_for_proxy(base_url: str) -> None:
    deadline = time.monotonic() + PROXY_READY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        try:
            with httpx2.Client(
                trust_env=False,
                follow_redirects=False,
                timeout=2.0,
            ) as client:
                response = client.get(base_url + "/health/liveliness")
            if response.status_code == 200:
                return
        except Exception:
            pass
        time.sleep(0.25)
    raise ProxySetupError("proxy_healthcheck_failed")


def _generate_project_key(base_url: str, master_key: str) -> str:
    key_payload = {
        "models": [MODEL_ALIAS],
        "key_alias": "t00-deepseek-user-smoke",
        "max_budget": PROJECT_KEY_BUDGET_USD,
        "budget_duration": "1d",
        "rpm_limit": PROJECT_KEY_RPM_LIMIT,
        "tpm_limit": PROJECT_KEY_TPM_LIMIT,
        "max_parallel_requests": PROJECT_KEY_MAX_PARALLEL,
        "duration": PROJECT_KEY_DURATION,
    }
    try:
        with httpx2.Client(
            trust_env=False,
            follow_redirects=False,
            timeout=10.0,
        ) as client:
            response = client.post(
                base_url + "/key/generate",
                headers={"Authorization": f"Bearer {master_key}"},
                json=key_payload,
            )
        if response.status_code != 200:
            raise ProxySetupError("project_key_generation_failed")
        payload = response.json()
    except ProxySetupError:
        raise
    except Exception:
        raise ProxySetupError("project_key_generation_failed") from None
    project_key = payload.get("key") if isinstance(payload, dict) else None
    if not isinstance(project_key, str) or not project_key.startswith("sk-"):
        raise ProxySetupError("project_key_generation_failed")
    return project_key


def start_ephemeral_proxy() -> ProxySession:
    private_dir = Path(tempfile.mkdtemp(prefix="byok-t00-deepseek-smoke-"))
    os.chmod(private_dir, 0o700)
    project_name = "t00-ds-smoke-" + uuid.uuid4().hex[:12]
    master_key = "sk-" + secrets.token_hex(32)
    _write_private_file(private_dir / "postgres_password", secrets.token_hex(32))
    _write_private_file(private_dir / "litellm_master_key", master_key)
    _write_private_file(private_dir / "litellm_salt_key", secrets.token_hex(32))
    _write_private_file(private_dir / "proxy.yaml", _proxy_config_yaml())
    compose_file = private_dir / "compose.yaml"
    _write_private_file(compose_file, _compose_yaml(private_dir))

    session = ProxySession(
        project_name=project_name,
        compose_file=compose_file,
        private_dir=private_dir,
        base_url="",
        master_key=master_key,
        project_key="",
    )
    try:
        _compose(
            session,
            "up",
            "-d",
            "--wait",
            "--wait-timeout",
            str(PROXY_START_TIMEOUT_SECONDS),
            "db",
            "proxy",
            timeout=PROXY_START_TIMEOUT_SECONDS + 30,
        )
        binding = _compose(session, "port", "proxy", "4000", timeout=15).stdout.strip()
        port = _local_port(binding)
        session.base_url = f"http://127.0.0.1:{port}"
        _wait_for_proxy(session.base_url)
        session.project_key = _generate_project_key(session.base_url, session.master_key)
        return session
    except BaseException:
        cleanup_ephemeral_proxy(session)
        raise


def cleanup_ephemeral_proxy(session: ProxySession) -> bool:
    try:
        if shutil.which("docker") is not None:
            _compose(session, "down", "--volumes", "--remove-orphans", timeout=45)
        session.master_key = ""
        session.project_key = ""
        shutil.rmtree(session.private_dir, ignore_errors=False)
        return True
    except Exception:
        return False


def run_gateway_request(
    provider_key: str,
    project_key: str,
    proxy_url: str,
    *,
    client_factory: Callable[..., Any] = OpenAI,
    http_client_factory: Callable[..., Any] = httpx2.Client,
) -> tuple[str, int, dict[str, object]]:
    request_count = 0

    def count_request(request: httpx2.Request) -> None:
        nonlocal request_count
        request_count += 1

    http_client = None
    client = None
    status = "FAIL"
    exit_code = 1
    result: dict[str, object] = {
        "model": MODEL,
        "gateway_model_alias": MODEL_ALIAS,
        "protocol": "openai_chat_completions_non_streaming",
        "path": "openai_sdk_to_local_litellm_proxy_to_deepseek",
        "proxy_version": "1.104.2",
        "request_count": 0,
        "request_count_semantics": "SDK HTTP attempts to loopback LiteLLM Proxy",
        "provider_upstream_attempt_count": "NOT_INDEPENDENTLY_OBSERVED",
        "proxy_retries": 0,
        "fallbacks": 0,
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "thinking": "disabled",
    }
    try:
        http_client = http_client_factory(
            trust_env=False,
            follow_redirects=False,
            timeout=TIMEOUT_SECONDS,
            event_hooks={"request": [count_request]},
        )
        client = client_factory(
            api_key=project_key,
            base_url=proxy_url + "/v1",
            max_retries=MAX_RETRIES,
            http_client=http_client,
        )
        response = client.chat.completions.create(
            model=MODEL_ALIAS,
            messages=[{"role": "user", "content": PROMPT}],
            max_tokens=MAX_OUTPUT_TOKENS,
            response_format={"type": "json_object"},
            extra_body={
                "api_key": provider_key,
                "thinking": {"type": "disabled"},
            },
        )
        valid, assertion, finish_reason = _valid_completion(response, request_count)
        result.update(_usage_fields(response))
        result["request_count"] = request_count
        result["finish_reason"] = finish_reason
        result["answer_assertion"] = assertion
        if valid:
            status = "PASS"
            exit_code = 0
        else:
            result["failure_reason"] = assertion
    except APIStatusError as exc:
        result.update({
            "request_count": request_count,
            "failure_reason": "gateway_or_provider_http_error",
            "http_status": exc.status_code,
        })
    except KeyboardInterrupt:
        result.update({
            "request_count": request_count,
            "failure_reason": "request_interrupted",
        })
        exit_code = 130
    except Exception as exc:
        result.update({
            "request_count": request_count,
            "failure_reason": type(exc).__name__,
        })
    finally:
        close_failed = False
        try:
            if client is not None:
                client.close()
            elif http_client is not None:
                http_client.close()
        except Exception:
            close_failed = True
        provider_key = ""

    if close_failed:
        status = "FAIL"
        exit_code = 1
        result["failure_reason"] = "resource_close_failed"
    result["request_count"] = request_count
    return status, exit_code, result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--send-one-request",
        action="store_true",
        help="start an ephemeral local Proxy, then send one bounded DeepSeek request",
    )
    args = parser.parse_args(argv)
    if not args.send_one_request:
        emit("NOT_RUN", request_count=0, requires="--send-one-request")
        return 0
    if not sys.stdin.isatty():
        emit("BLOCKED", request_count=0, reason="interactive_terminal_required")
        return 2

    try:
        session = start_ephemeral_proxy()
    except KeyboardInterrupt:
        emit("NOT_RUN", request_count=0, reason="proxy_start_interrupted")
        return 130
    except Exception as exc:
        emit("BLOCKED", request_count=0, reason=type(exc).__name__)
        return 2

    status = "NOT_RUN"
    exit_code = 1
    provider_key = ""
    result: dict[str, object] = {
        "model": MODEL,
        "gateway_model_alias": MODEL_ALIAS,
        "protocol": "openai_chat_completions_non_streaming",
        "path": "openai_sdk_to_local_litellm_proxy_to_deepseek",
        "proxy_version": "1.104.2",
        "request_count": 0,
        "request_count_semantics": "SDK HTTP attempts to loopback LiteLLM Proxy",
        "provider_upstream_attempt_count": "NOT_INDEPENDENTLY_OBSERVED",
        "proxy_retries": 0,
        "fallbacks": 0,
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "thinking": "disabled",
    }
    try:
        try:
            entered_key = getpass.getpass(
                "DeepSeek API key (hidden; used for one gateway request only): "
            )
        except (EOFError, KeyboardInterrupt):
            status = "NOT_RUN"
            exit_code = 130
            result["reason"] = "key_input_cancelled"
        else:
            provider_key = entered_key.strip()
            entered_key = ""
            if not provider_key:
                status = "BLOCKED"
                exit_code = 2
                result["reason"] = "empty_key"
            else:
                status, exit_code, result = run_gateway_request(
                    provider_key,
                    session.project_key,
                    session.base_url,
                )
    finally:
        provider_key = ""
        if not cleanup_ephemeral_proxy(session):
            status = "FAIL"
            exit_code = 1
            result["failure_reason"] = "ephemeral_proxy_cleanup_failed"
            result["cleanup_project"] = session.project_name
            result["cleanup_config"] = str(session.compose_file)
    emit(status, **result)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
