"""Run isolated T00 official-SDK protocol checks; never call a real provider."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
from http.server import ThreadingHTTPServer
import importlib.metadata
import json
import os
from pathlib import Path
import secrets
import signal
import sys
import threading
import time

from local_runtime import LocalProxy, isolated_env


class QuietServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, _request, _client_address):
        # Expected timeout/cancel fixtures can close while a write is in flight.
        # Missing fixture receipts still fail the request-count checks.
        return


def _safe_terminal_guard_diagnostic(exc: Exception) -> dict | None:
    """Read only our fixed, synthetic-only guard diagnostic fields from a 502."""
    response = getattr(exc, "response", None)
    if getattr(response, "status_code", None) != 502:
        return None
    try:
        payload = response.json()
    except Exception:
        return None
    detail = payload.get("detail") if isinstance(payload, dict) else None
    if not isinstance(detail, dict) or detail.get("code") != "T00_STREAM_TERMINAL_UNVERIFIED":
        return None
    diagnostic = detail.get("diagnostic")
    if not isinstance(diagnostic, dict):
        return None
    allowed_reasons = {
        "version_unavailable",
        "version_mismatch",
        "router_provenance_patch_unavailable",
        "router_method_mismatch",
        "wrapper_types_unavailable",
        "boundary_type_mismatch",
        "router_wrapper_type_mismatch",
        "router_provenance_missing",
        "raw_source_type_mismatch",
        "source_provider_mismatch",
        "source_provider_unavailable",
        "fallback_activated",
        "internal_guard_failure",
    }
    allowed = ("reason", "litellm_version", "response_type", "source_type", "source_provider")
    safe = {}
    for key in allowed:
        value = diagnostic.get(key)
        if not isinstance(value, str) or not value or len(value) > 192:
            return None
        if not all(character.isalnum() or character in "._:<>" for character in value):
            return None
        if key == "reason" and value not in allowed_reasons:
            return None
        if key == "source_provider" and value not in {"deepseek", "openai", "missing", "other"}:
            return None
        safe[key] = value
    return safe


def stream_complete(protocol: str, result: dict) -> bool:
    events, terminals = result.get("event_types", []), result.get("terminals", [])
    if protocol == "chat":
        return "stop" in terminals
    if protocol == "responses":
        return "response.completed" in events and "completed" in terminals
    return "message_stop" in events and "end_turn" in terminals


def invalid_tool_rejected(result: dict) -> bool:
    if result.get("dispatched") is not False or result.get("tool_dispatch_count") != 0:
        return False
    return result.get("rejection") in {
        "not_allowlisted", "partial_json", "invalid_json", "invalid_argument_shape", "invalid_argument_value",
    } or (result.get("success") is False and result.get("error_type") in {"ValidationError", "APIResponseValidationError"})


def stream_error_detected(result: dict) -> bool:
    return result.get("success") is False or "error" in result.get("event_types", []) or (
        "response.failed" in result.get("event_types", []) and "failed" in result.get("terminals", [])
    )


def scope_status(checks: list[dict], scope: str, *, started: bool, completed: bool) -> str:
    if not started:
        return "NOT_RUN"
    relevant = [row for row in checks if scope in row["case"]]
    shared = [row for row in checks if row["case"] in {"RUNTIME", "LOCAL_RUNTIME_CLEANUP", "ALL_SDK_CLIENTS_CLOSED", "UPSTREAM_PRODUCERS_CLOSED", "ALL_UPSTREAM_REQUESTS_ACCOUNTED"}]
    return "PASS" if completed and relevant and all(row["status"] == "PASS" for row in relevant + shared) else "FAIL"


def receipt_matches(rows: list[dict], count: int, tenant: str, protocol: str, terminal: str | None = None) -> bool:
    target_route = any("_DEEPSEEK_" in row.get("test_id", "") for row in rows)
    model = "deepseek-flash" if target_route else "test-model" if tenant == "tenant-a" else "other-test-model"
    return len(rows) == count and all(
        row.get("tenant") == tenant
        and row.get("provider_key_match") is True
        and row.get("project_key_match") is False
        and row.get("model") == model
        and row.get("protocol") == protocol
        and (terminal is None or row.get("upstream_terminal") == terminal)
        for row in rows
    )


def receipts_exhaustive(records: list[dict], receipts: list[tuple]) -> bool:
    markers = {row[1] for row in receipts}
    return len(records) == sum(row[2] for row in receipts) and all(row.get("test_id") in markers for row in records)


def interrupted(_signum, _frame):
    raise KeyboardInterrupt("T00_INTERRUPTED")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--proxy-python", help="Isolated interpreter prepared with prepare_proxy.py")
    mode.add_argument("--sdk-only", action="store_true", help="Run only SDK_LOCAL; PROXY_LOCAL stays NOT_RUN")
    parser.add_argument("--report", type=Path, help="Write sanitized JSON evidence")
    args = parser.parse_args(argv)
    signal.signal(signal.SIGTERM, interrupted)
    # This process is disposable. Do not read provider credentials, proxies,
    # dotenv files, database URLs, or SDK account defaults from its environment.
    os.environ.clear()
    os.environ.update(isolated_env())
    from proxy_process import loopback_only
    sys.addaudithook(loopback_only)
    import protocol_cases as cases
    import upstream

    keys = {tenant: "sk-t00-" + secrets.token_hex(24) for tenant in ("tenant-a", "tenant-b")}
    upstream.KEY_LABELS = {value: key for key, value in keys.items()}
    server = QuietServer(("127.0.0.1", 0), upstream.Handler)
    upstream_url = "http://127.0.0.1:" + str(server.server_port)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    checks: list[dict] = []
    receipts: list[tuple[str, str, int, str, str | None]] = []
    proxy = None
    started_scopes = set()
    completed_scopes = set()
    report = {
        "task": "BYOK T00", "task_status": "PARTIAL",
        "implementation_baseline": "2e3254c890f52af626aa7d2400097301bf550d14",
        "scope": "SDK_AND_PINNED_PROXY_PROCESS_SYNTHETIC_ONLY",
        "versions": {name: importlib.metadata.version(name) for name in ("openai", "anthropic", "httpx2")},
        "python": sys.version.split()[0], "PROVIDER_REAL": "NOT_RUN", "UAT": "NOT_RUN",
        "T00-10_historical_image": "NOT_RUN", "pinned_image_digest_and_signature": "NOT_RUN",
        "checks": checks,
    }

    def check(contract: str, name: str, passed: bool, facts: dict | None = None) -> None:
        checks.append({"contract": contract, "case": name, "status": "PASS" if passed else "FAIL", "facts": facts or {}})

    def expect_receipt(source: str, marker: str, count: int, tenant: str = "tenant-a", terminal: str | None = None):
        receipts.append((source, marker, count, tenant, terminal))

    def call(protocol, url, sdk_key, marker, *, via_proxy, provider_key, model=None, stream=False):
        client = cases.protocol_client(protocol, sdk_key, url + ("" if protocol == "messages" else "/v1"), via_proxy=via_proxy)
        try:
            chosen = model or (("t00-messages" if protocol == "messages" else "t00-chat") if via_proxy else "test-model")
            kwargs = cases.protocol_request(protocol, chosen, marker, provider_key=provider_key, via_proxy=via_proxy, stream=stream)
            method = client.messages.create if protocol == "messages" else client.responses.create if protocol == "responses" else client.chat.completions.create
            result = method(**kwargs)
            if stream:
                with result:
                    for _event in result:
                        pass
                return {"success": True}
            terminal = result.stop_reason if protocol == "messages" else result.status if protocol == "responses" else result.choices[0].finish_reason
            return {"success": True, "terminal": terminal}
        except Exception as exc:
            return cases.safe_exception(exc)
        finally:
            client.close()

    def raw_chat_stream_status(url: str, project_key: str, marker: str, provider_key: str, stream_value) -> int:
        # Raw JSON (not the typed SDK) so a string/number stream flag that
        # typed parsing would coerce to True is exercised end-to-end.
        import http.client
        from urllib.parse import urlsplit
        parts = urlsplit(url)
        body = json.dumps({"model": "t00-chat", "messages": [{"role": "user", "content": marker}],
                           "stream": stream_value, "api_key": provider_key}).encode()
        conn = http.client.HTTPConnection(parts.hostname, parts.port, timeout=10)
        try:
            conn.request("POST", "/v1/chat/completions", body=body,
                         headers={"Content-Type": "application/json", "Authorization": "Bearer " + project_key})
            response = conn.getresponse()
            response.read()
            return response.status
        finally:
            conn.close()

    def suite(source: str, url: str, project_keys: dict | None = None):
        via_proxy = project_keys is not None
        sdk_key = project_keys["tenant-a"] if via_proxy else keys["tenant-a"]
        for protocol in ("chat", "responses", "messages"):
            base = url + ("" if protocol == "messages" else "/v1")
            upper = protocol.upper()
            marker = f"T00_{source}_{upper}_COMPLETE_A"
            result = call(protocol, url, sdk_key, marker, via_proxy=via_proxy, provider_key=keys["tenant-a"])
            expected = {"chat": "stop", "responses": "completed", "messages": "end_turn"}[protocol]
            check("T00-01", f"{source}_{upper}_COMPLETE", result.get("terminal") == expected, result)
            expect_receipt(source, marker, 1, terminal={"chat": "finish_reason_stop", "responses": "response_completed", "messages": "message_stop"}[protocol])

            if via_proxy:
                # Exercise actual JSON admission, not only direct callback
                # invocation. No overridden request may reach any upstream.
                import http.client
                from urllib.parse import urlsplit
                target = urlsplit(url)
                endpoint = {'chat': '/v1/chat/completions', 'responses': '/v1/responses',
                            'messages': '/v1/messages'}[protocol]
                chosen = 't00-messages' if protocol == 'messages' else 't00-chat'
                for label, override in (
                    ('URL', {'api_base': 'http://127.0.0.1:1/v1'}),
                    ('HEADER', {'headers': {'Authorization': 'synthetic-unapproved-key'}}),
                    ('EXTRA_HEADERS', {'extra_headers': {'Host': 'unapproved.invalid'}}),
                    ('RETRY', {'num_retries': 1}),
                    # An otherwise authorized target proves that the guard,
                    # rather than a missing model permission, denies fallback.
                    ('FALLBACK', {'fallbacks': ['t00-chat']}),
                    ('NESTED', {'extra_body': {'api_base': 'http://127.0.0.1:1/v1'}}),
                ):
                    marker = f'T00_PROXY_{upper}_OVERRIDE_{label}_A'
                    body = cases.protocol_request(protocol, chosen, marker,
                                                  provider_key=keys['tenant-a'], via_proxy=True, stream=False)
                    body.update(body.pop('extra_body', {}))
                    body.update(override)
                    connection = http.client.HTTPConnection(target.hostname, target.port, timeout=10)
                    try:
                        connection.request('POST', endpoint, body=json.dumps(body).encode(),
                                           headers={'Content-Type': 'application/json',
                                                    'Authorization': 'Bearer ' + sdk_key})
                        response = connection.getresponse()
                        status = response.status
                        response.read(65536)
                    finally:
                        connection.close()
                    # Virtual-key URL policy may reject earlier than our
                    # callback with 401. Both are explicit admission denials;
                    # the independently reconciled receipt MUST remain zero.
                    allowed_denials = (400, 401) if label in ('URL', 'NESTED') else (400,)
                    check('T00-08', f'PROXY_{upper}_OVERRIDE_{label}', status in allowed_denials,
                          {'status_code': status, 'expected_upstream_requests': 0,
                           'normal_route_control_passed': True})
                    expect_receipt(source, marker, 0)

            result = cases.run_incomplete_cases(base, protocol, project_key=sdk_key if via_proxy else None, provider_key=keys["tenant-a"])
            expected = {"chat": "length", "responses": "incomplete", "messages": "max_tokens"}[protocol]
            check("T00-02", f"{source}_{upper}_INCOMPLETE", result.get("terminal") == expected, result)
            expect_receipt(source, f"T00_{source}_{upper}_INCOMPLETE_A", 1)

            if via_proxy and protocol == "chat":
                marker = "T00_PROXY_CHAT_NO_FINISH_A"
                result = call(protocol, url, sdk_key, marker, via_proxy=True,
                              provider_key=keys["tenant-a"])
                check("T00-02", "PROXY_CHAT_RAW_TERMINAL_MISSING",
                      result.get("success") is False and result.get("status_code") == 502, result)
                expect_receipt(source, marker, 1, terminal="missing_finish_reason")

            errors = cases.run_protocol_error_cases(base, protocol, f"T00_{source}_{upper}", sdk_key, provider_key=keys["tenant-a"], via_proxy=via_proxy, cases=("HTTP_ERROR", "TIMEOUT", "TRUNCATED"))
            for kind, result in errors.items():
                check("T00-03", f"{source}_{upper}_{kind.upper()}", result.get("success") is False, result)
                expect_receipt(source, f"T00_{source}_{upper}_{kind.upper()}_A", 1)

            if via_proxy and protocol == "chat":
                marker = "T00_PROXY_CHAT_STREAM_GUARD_A"
                result = call(protocol, url, sdk_key, marker, via_proxy=True, provider_key=keys["tenant-a"], stream=True)
                check("T00-02", "PROXY_CHAT_STREAM_FAIL_CLOSED", result.get("status_code") == 400, result)
                expect_receipt(source, marker, 0)
                # EOF-named raw variants: if either reached upstream, its
                # EOF-without-terminal would surface as stop/[DONE].
                for variant, flag in (("STRING", "true"), ("NUMERIC", 1),
                                      ("SHORT_T", "t"), ("SHORT_Y", "y"),
                                      ("UPPER_T", "T"), ("UPPER_Y", "Y")):
                    raw_marker = f"T00_PROXY_CHAT_STREAM_EOF_{variant}_A"
                    status = raw_chat_stream_status(url, sdk_key, raw_marker, keys["tenant-a"], flag)
                    check("T00-02", f"PROXY_CHAT_STREAM_EOF_{variant}_FAIL_CLOSED", status == 400, {"status_code": status})
                    expect_receipt(source, raw_marker, 0)
            else:
                for kind in ("COMPLETE", "EOF", "INCOMPLETE", "SSE_ERROR", "CANCEL"):
                    result = cases.run_protocol_stream_case(base, protocol, kind, sdk_key, provider_key=keys["tenant-a"], via_proxy=via_proxy, upstream_url=upstream_url, proxy_health_url=url + "/health/liveliness" if via_proxy else None)
                    complete = stream_complete(protocol, result)
                    if kind == "COMPLETE":
                        passed = result.get("success") is True and complete
                    elif kind == "SSE_ERROR":
                        passed = not complete and stream_error_detected(result)
                    elif kind == "INCOMPLETE":
                        passed = not complete and {"chat": "length", "responses": "incomplete", "messages": "max_tokens"}[protocol] in result.get("terminals", [])
                    elif kind == "CANCEL":
                        passed = not complete and result.get("client_response_closed") is True and result.get("upstream_producer_exited_within_observation_window") is True
                    else:
                        passed = not complete
                    passed = passed and result.get("client_response_closed") is True
                    check("T00-07" if kind == "CANCEL" else "T00-02" if kind in ("EOF", "INCOMPLETE") else "T00-03" if kind == "SSE_ERROR" else "T00-01", f"{source}_{upper}_STREAM_{kind}", passed, result)
                    expect_receipt(source, f"T00_{source}_{upper}_STREAM_{kind}_A", 1)

            result = cases.proxy_tool_roundtrip(protocol, url, sdk_key, keys["tenant-a"], via_proxy=via_proxy)
            check("T00-05", f"{source}_{upper}_TOOL_ROUNDTRIP", result.get("success") is True and result.get("tool_dispatch_outcomes") == ["dispatched", "dispatched"] and result.get("continuation_in_public") is False and result.get("key_in_public") is False, {k: v for k, v in result.items() if k != "public_output"})
            for suffix in ("R1", "R2", "FINAL"):
                terminal = {"chat": "finish_reason_stop", "responses": "response_completed", "messages": "message_stop"}[protocol] if suffix == "FINAL" else "tool_call_turn"
                expect_receipt(source, f"T00_{source}_{upper}_TOOL_{suffix}_A", 1, terminal=terminal)
            if via_proxy:
                for variant in ("MALFORMED", "INVALID", "UNKNOWN"):
                    result = cases.probe_invalid_tool(protocol, variant, url, sdk_key, keys["tenant-a"])
                    check("T00-04", f"PROXY_{upper}_TOOL_{variant}", invalid_tool_rejected(result), {k: v for k, v in result.items() if k != "test_id"})
                    expect_receipt(source, f"T00_PROXY_{upper}_TOOL_{variant}_A", 1)

    def native_deepseek_stream(url: str, project_key: str, provider_key: str, marker: str, *, usage: bool = False):
        """Use the pinned official OpenAI SDK against the exact native DeepSeek route."""
        client = cases.openai_client(project_key, url + "/v1", timeout=10.0)
        stream = None
        event_types, terminals = [], []
        usage_chunks = 0
        started = time.monotonic()
        result = {"success": False}
        try:
            kwargs = {
                "model": "deepseek/deepseek-flash",
                "messages": [{"role": "user", "content": marker}],
                "stream": True,
                "reasoning_effort": "none",
                "extra_body": {"api_key": provider_key},
            }
            if usage:
                kwargs["stream_options"] = {"include_usage": True}
            stream = client.chat.completions.create(**kwargs)
            with stream:
                for event in stream:
                    event_type, terminal = cases._stream_event_facts("chat", event)
                    if event_type:
                        event_types.append(event_type)
                    if terminal:
                        terminals.append(terminal)
                    if getattr(event, "usage", None) is not None:
                        usage_chunks += 1
            result = {"success": True}
        except Exception as exc:
            result = cases.safe_exception(exc)
            diagnostic = _safe_terminal_guard_diagnostic(exc)
            if diagnostic is not None:
                result["guard_diagnostic"] = diagnostic
        finally:
            response = getattr(stream, "response", None)
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass
            result.update({
                "terminals": terminals,
                "event_types": event_types,
                "usage_chunks": usage_chunks,
                "client_response_closed": bool(response is not None and response.is_closed),
                "duration_ms": round((time.monotonic() - started) * 1000, 2),
            })
            client.close()
        return result

    def terminal_route_suite(url: str, project_key: str, provider_key: str):
        cases_to_run = (
            ("RAW_STOP", "T00_PROXY_CHAT_DEEPSEEK_RAW_STOP_A", True, False, "finish_reason_stop"),
            ("RAW_STOP_CLEAN_EOF", "T00_PROXY_CHAT_DEEPSEEK_STOP_EOF_A", True, False, "finish_reason_stop_without_done"),
            ("RAW_STOP_USAGE_DONE", "T00_PROXY_CHAT_DEEPSEEK_USAGE_DONE_A", True, True, "finish_reason_stop_with_usage"),
            ("RAW_STOP_USAGE_SAME_FRAME", "T00_PROXY_CHAT_DEEPSEEK_USAGE_SAME_FRAME_A", True, True, "finish_reason_stop_with_usage_same_frame"),
            ("DONE_WITHOUT_RAW_STOP", "T00_PROXY_CHAT_DEEPSEEK_NO_STOP_DONE_A", False, False, "protocol_done_without_finish_reason"),
            ("EOF_WITHOUT_RAW_STOP", "T00_PROXY_CHAT_DEEPSEEK_EOF_A", False, False, "normal_eof_without_protocol_terminal"),
            ("LENGTH_TERMINAL", "T00_PROXY_CHAT_DEEPSEEK_INCOMPLETE_A", False, False, "finish_reason_length"),
            ("CONTENT_FILTER_TERMINAL", "T00_PROXY_CHAT_DEEPSEEK_CONTENT_FILTER_A", False, False, "finish_reason_content_filter"),
            ("SSE_ERROR", "T00_PROXY_CHAT_DEEPSEEK_SSE_ERROR_A", False, False, "stream_error_no_terminal"),
            ("OPEN_AFTER_DONE", "T00_PROXY_CHAT_DEEPSEEK_OPEN_AFTER_DONE_A", True, False, "finish_reason_stop"),
        )
        for name, marker, should_succeed, usage, terminal in cases_to_run:
            completed_while_socket_held = None
            if name == "OPEN_AFTER_DONE":
                # Keep the raw upstream socket open behind an explicit barrier.
                # The SDK stream must finish while that upstream handler is
                # still held; release it afterward so the fixture can record
                # whether the client had already closed the connection.
                result_box = {}
                request_finished = threading.Event()

                def run_open_after_done():
                    try:
                        result_box["result"] = native_deepseek_stream(
                            url, project_key, provider_key, marker, usage=usage,
                        )
                    finally:
                        request_finished.set()

                worker = threading.Thread(target=run_open_after_done, daemon=True)
                worker.start()
                held_seen = False
                try:
                    deadline = time.monotonic() + 6.0
                    while time.monotonic() < deadline:
                        rows = [
                            row for row in cases.request_json(upstream_url + "/stats").get("records", [])
                            if row.get("test_id") == marker
                        ]
                        held_seen = bool(rows and rows[0].get("post_done_socket_held"))
                        observation_complete = bool(
                            rows and rows[0].get("post_done_peer_observation_complete")
                        )
                        if held_seen and request_finished.is_set() and observation_complete:
                            break
                        time.sleep(0.02)
                    completed_while_socket_held = (
                        held_seen
                        and request_finished.is_set()
                        and bool(rows and not rows[0].get("post_done_barrier_release_monotonic_ns"))
                    )
                finally:
                    # Always release the fixture, including when polling fails.
                    try:
                        cases.request_json(
                            upstream_url + "/test/release", {"test_id": marker},
                        )
                    except Exception:
                        pass
                    worker.join(timeout=12)
                result = result_box.get("result", {"success": False})
                result["completed_while_socket_held"] = completed_while_socket_held is True
                result["request_thread_terminated"] = not worker.is_alive()
                rows = [
                    row for row in cases.request_json(upstream_url + "/stats").get("records", [])
                    if row.get("test_id") == marker
                ]
                if name == "OPEN_AFTER_DONE":
                    producer_deadline = time.monotonic() + 3.0
                    while time.monotonic() < producer_deadline:
                        rows = [
                            row for row in cases.request_json(upstream_url + "/stats").get("records", [])
                            if row.get("test_id") == marker
                        ]
                        if rows and rows[0].get("upstream_stream_producer_exit_monotonic_ns") is not None:
                            break
                        time.sleep(0.02)
            else:
                result = native_deepseek_stream(
                    url, project_key, provider_key, marker, usage=usage,
                )
                rows = [
                    row for row in cases.request_json(upstream_url + "/stats").get("records", [])
                    if row.get("test_id") == marker
                ]
            row = rows[0] if len(rows) == 1 else {}
            terminal_ok = (
                result.get("terminals") == ["stop"]
                if should_succeed else "stop" not in result.get("terminals", [])
            )
            predicates = {
                "expected_success": result.get("success") is should_succeed,
                "client_response_closed": result.get("client_response_closed") is True,
                "expected_terminal": terminal_ok,
                "usage_count": result.get("usage_chunks") == 1 if usage else True,
                "single_upstream_request": len(rows) == 1,
                "native_deepseek_route": row.get("path") == "/v1/chat/completions"
                    and row.get("model") == "deepseek-flash"
                    and row.get("stream") is True
                    and row.get("thinking_disabled") is True,
                "synthetic_key_isolation": row.get("tenant") == "tenant-a"
                    and row.get("provider_key_match") is True
                    and row.get("project_key_match") is False,
                "upstream_terminal_receipt": row.get("upstream_terminal") == terminal,
                "request_key_redaction": provider_key not in json.dumps(result, sort_keys=True)
                    and project_key not in json.dumps(result, sort_keys=True),
            }
            fixture_facts = {
                key: row.get(key) for key in (
                    "path", "model", "stream", "thinking_disabled", "tenant",
                    "provider_key_match", "project_key_match", "upstream_terminal",
                    "post_done_socket_held", "post_done_peer_close_state",
                    "post_done_peer_observation_monotonic_ns",
                    "post_done_peer_observation_complete",
                    "post_done_barrier_release_monotonic_ns",
                    "post_done_probe_write_attempted",
                    "post_done_probe_write_succeeded", "client_disconnected",
                    "upstream_stream_producer_exit_monotonic_ns",
                )
            }
            if name == "OPEN_AFTER_DONE":
                close_state = row.get("post_done_peer_close_state")
                close_ns = row.get("post_done_peer_observation_monotonic_ns")
                release_ns = row.get("post_done_barrier_release_monotonic_ns")
                producer_exit_ns = row.get("upstream_stream_producer_exit_monotonic_ns")
                predicates.update({
                    "sdk_finished_while_barrier_held": completed_while_socket_held is True,
                    "held_socket_barrier_reached": row.get("post_done_socket_held") is True,
                    "peer_eof_or_reset_observed": close_state in {"eof", "reset"},
                    "peer_close_precedes_release": (
                        isinstance(close_ns, int) and isinstance(release_ns, int)
                        and close_ns < release_ns
                    ),
                    "peer_observation_completed": row.get("post_done_peer_observation_complete") is True,
                    "sdk_request_thread_terminated": result.get("request_thread_terminated") is True,
                    "producer_exited_after_release": (
                        isinstance(producer_exit_ns, int) and isinstance(release_ns, int)
                        and producer_exit_ns > release_ns
                    ),
                })
                result["post_done_fixture_facts"] = fixture_facts
                result["completed_while_socket_held"] = completed_while_socket_held is True
                result["request_thread_terminated"] = result.get("request_thread_terminated") is True
            result["case_predicates"] = predicates
            passed = all(predicates.values())
            check("T00-10", "NATIVE_DEEPSEEK_" + name, passed, result)
            expect_receipt("PROXY", marker, 1, terminal=terminal)

    try:
        started_scopes.add("SDK")
        suite("SDK", upstream_url)
        completed_scopes.add("SDK")
        if args.proxy_python:
            started_scopes.add("PROXY")
            proxy = LocalProxy(args.proxy_python, upstream_url)
            with proxy:
                report["versions"].update(proxy.versions)
                upstream.KEY_LABELS[proxy.master] = "master"
                upstream.PROJECT_KEY_HASHES.update(hashlib.sha256(key.encode()).hexdigest() for key in proxy.project_keys.values())
                suite("PROXY", proxy.url, proxy.project_keys)
                terminal_route_suite(proxy.url, proxy.project_keys["tenant-a"], keys["tenant-a"])
                for protocol in ("chat", "responses", "messages"):
                    upper = protocol.upper()
                    for variant, sdk_key, provider_key, model in (
                        ("MISSING_KEY", proxy.project_keys["tenant-a"], None, None),
                        ("EMPTY_KEY", proxy.project_keys["tenant-a"], "", None),
                        ("WHITESPACE_KEY", proxy.project_keys["tenant-a"], " \t ", None),
                        ("NONSTRING_KEY", proxy.project_keys["tenant-a"], {"synthetic": True}, None),
                        ("BAD_PROJECT", "sk-" + secrets.token_hex(32), keys["tenant-a"], None),
                        ("WRONG_MODEL", proxy.project_keys["tenant-a"], keys["tenant-a"], "t00-other-messages" if protocol == "messages" else "t00-other-chat"),
                    ):
                        marker = f"T00_PROXY_{upper}_{variant}_A"
                        result = call(protocol, proxy.url, sdk_key, marker, via_proxy=True, provider_key=provider_key, model=model)
                        check("T00-08", f"PROXY_{upper}_{variant}", result.get("status_code") in (400, 401, 403), result)
                        expect_receipt("PROXY", marker, 0)
                # Four simultaneous, real project-key authenticated SDK calls.
                with ThreadPoolExecutor(max_workers=4) as pool:
                    pending = []
                    for protocol in ("chat", "messages"):
                        for tenant, suffix in (("tenant-a", "A"), ("tenant-b", "B")):
                            marker = f"T00_PROXY_{protocol.upper()}_CONCURRENT_{suffix}"
                            model = ("t00-other-" if tenant == "tenant-b" else "t00-") + protocol
                            pending.append(pool.submit(call, protocol, proxy.url, proxy.project_keys[tenant], marker, via_proxy=True, provider_key=keys[tenant], model=model))
                            expect_receipt("PROXY", marker, 1, tenant)
                    result = [future.result() for future in pending]
                check("T00-06", "PROXY_CONCURRENT_PROJECT_PROVIDER_ISOLATION", all(row.get("success") is True for row in result), {"requests": len(result)})
                completed_scopes.add("PROXY")
        # Allow the bounded timeout fixtures to finish before checking receipts.
        deadline = time.monotonic() + 3
        while upstream.ACTIVE_STREAM_PRODUCERS and time.monotonic() < deadline:
            time.sleep(0.05)
        with upstream.LOCK:
            records = list(upstream.RECORDS)
        check("T00-09", "ALL_UPSTREAM_REQUESTS_ACCOUNTED", receipts_exhaustive(records, receipts), {"expected_total": sum(row[2] for row in receipts), "actual_total": len(records)})
        for source, marker, count, tenant, terminal in receipts:
            rows = [row for row in records if row.get("test_id") == marker]
            protocol = "completions" if "_CHAT_" in marker else "responses" if "_RESPONSES_" in marker else "messages"
            matched = receipt_matches(rows, count, tenant, protocol, terminal)
            check("T00-09", marker + "_RECEIPT", matched, {"expected_count": count, "actual_count": len(rows), "provider_labels": [row.get("tenant") for row in rows], "models": [row.get("model") for row in rows], "protocols": [row.get("protocol") for row in rows], "upstream_terminals": [row.get("upstream_terminal") for row in rows]})
        for source in ("SDK", "PROXY") if args.proxy_python else ("SDK",):
            for protocol in ("chat", "responses", "messages"):
                marker = f"T00_{source}_{protocol.upper()}_TOOL_FINAL_A"
                rows = [row for row in records if row.get("test_id") == marker]
                facts = rows[0].get("continuation_facts", {}) if len(rows) == 1 else {}
                required = {
                    "chat": [f"chat_r{i}_{suffix}" for i in (1, 2) for suffix in ("assistant_preserved", "tool_result_id_preserved")],
                    "responses": [f"responses_r{i}_{suffix}" for i in (1, 2) for suffix in ("output_items_preserved", "tool_result_preserved")],
                    "messages": [f"messages_r{i}_{suffix}" for i in (1, 2) for suffix in ("thinking_signature_preserved", "tool_result_preserved")],
                }[protocol]
                check("T00-05", f"{source}_{protocol.upper()}_CONTINUATION_PRESERVED", all(facts.get(name) is True for name in required), {name: facts.get(name) for name in required})
        if args.proxy_python:
            for protocol in ("CHAT", "MESSAGES"):
                rows = [row for row in records if row.get("test_id") in {f"T00_PROXY_{protocol}_CONCURRENT_A", f"T00_PROXY_{protocol}_CONCURRENT_B"}]
                overlapped = len(rows) == 2 and max(row.get("request_service_started_monotonic_ns", 0) for row in rows) < min(row.get("request_service_completed_monotonic_ns", 0) for row in rows)
                check("T00-06", f"PROXY_{protocol}_UPSTREAM_CONCURRENCY_OBSERVED", overlapped)
        check("T00-07", "ALL_SDK_CLIENTS_CLOSED", all(client.is_closed() for client in cases.CLIENTS_CREATED), {"client_count": len(cases.CLIENTS_CREATED)})
        check("T00-07", "UPSTREAM_PRODUCERS_CLOSED", upstream.ACTIVE_STREAM_PRODUCERS == 0)
    except (Exception, KeyboardInterrupt) as exc:
        check("T00", "RUNTIME", False, {"error_type": type(exc).__name__, "stage": str(exc) if str(exc).startswith("T00_") else "T00_RUNTIME_FAILED"})
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        check("T00-07", "LOCAL_RUNTIME_CLEANUP", not thread.is_alive() and (proxy is None or proxy.cleanup_complete))
    report["SDK_LOCAL"] = scope_status(checks, "SDK", started="SDK" in started_scopes, completed="SDK" in completed_scopes)
    report["PROXY_PROCESS_LOCAL"] = scope_status(checks, "PROXY", started="PROXY" in started_scopes, completed="PROXY" in completed_scopes)
    report["passed"] = sum(row["status"] == "PASS" for row in checks)
    report["failed"] = sum(row["status"] == "FAIL" for row in checks)
    encoded = json.dumps(report, ensure_ascii=True, indent=2)
    # Defense in depth: report output is an allowlist of facts, not raw SDK or
    # upstream responses, but reject it if any generated credential escaped.
    all_keys = list(keys.values()) + ([] if proxy is None else [proxy.master, *proxy.project_keys.values()])
    if any(value in encoded for value in all_keys):
        print('{"task_status":"BLOCKED","error":"T00_REPORT_REDACTION_FAILED"}')
        return 1
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(encoded + "\n")
    summary = {key: value for key, value in report.items() if key != "checks"}
    summary["failures"] = [row for row in checks if row["status"] == "FAIL"]
    print(json.dumps(summary, ensure_ascii=True))
    return int(report["failed"] > 0)


if __name__ == "__main__":
    raise SystemExit(main())
