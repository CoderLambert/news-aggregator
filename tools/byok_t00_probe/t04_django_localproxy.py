"""End-to-end T04/T05/T06 proof through Django, OpenAI SDK, pinned Proxy and loopback fixture.

Run only from the full CI gate after prepare_proxy.py; never use a live endpoint
or credential. The test intentionally uses the exact native DeepSeek alias.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import sys
import threading
import time
import urllib.request
import uuid
from http.server import ThreadingHTTPServer

import pytest
from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection as database_connection
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

PROBE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROBE_DIR))

from local_runtime import LocalProxy, OPENER  # noqa: E402
import upstream  # noqa: E402

from api.ai_connection_models import UserAIConnection  # noqa: E402
from api.ai_model_models import AIModelProbeAttempt, UserAIModelConfig  # noqa: E402
from api.models import (ArticleChatTurn, Category, ChatSession, News, Source,
                        ChatGPTArticleTranslation, SharedArticleTranslation)  # noqa: E402
from api.tests.rss.reader_fixtures import public_legacy_article  # noqa: E402
from api.services.stored_readers import article_snapshot, require_current  # noqa: E402

ALIAS = "deepseek/deepseek-flash"
CONNECTIONS = "/api/me/ai/connections/"


@pytest.fixture(scope="session")
def django_db_modify_db_settings(django_db_modify_db_settings_parallel_suffix, tmp_path_factory):
    # Concurrent HTTP readers/workers must exercise the application's file WAL
    # behavior. Django's default shared in-memory test DB uses table locks.
    from django.conf import settings
    root = tmp_path_factory.mktemp("t04-django-wal")
    settings.DATABASES["default"].setdefault("TEST", {})["NAME"] = str(root / "test.sqlite3")


@pytest.fixture(autouse=True)
def translation_redis(monkeypatch):
    # Use a real isolated transport while keeping credential/DB scrubbing.
    # Configuration injection changes only the Redis endpoint, never business
    # admission, worker fences, SDK/Proxy requests or completion validation.
    from api.services import translation_channel
    from api.tests.translation_transport_fixture import synthetic_redis_client
    redis = synthetic_redis_client()
    assert redis is not None, 'full CI must provision an isolated translation Redis'
    redis.ping()
    monkeypatch.setattr(translation_channel, 'client', lambda: redis)
    yield
    redis.close()


class QuietServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, _request, _client_address):
        # Client disconnects are expected in the cancellation proof.
        return


def _stats(url):
    with OPENER.open(url + "/stats", timeout=3) as response:
        return json.load(response)


def _wait_record(url, marker, predicate, timeout=8):
    deadline = time.monotonic() + timeout
    rows = []
    while time.monotonic() < deadline:
        rows = [row for row in _stats(url)["records"] if row.get("test_id") == marker]
        if rows and predicate(rows[-1]):
            return rows[-1]
        time.sleep(0.03)
    # Report only synthetic lifecycle facts, never request text or credentials.
    diagnostic_fields = (
        "stream_hold_waiting", "stream_hold_released", "stream_hold_timed_out",
        "stream_hold_peer_close_state", "client_disconnected", "producer_exit_reason",
        "upstream_stream_events_written", "upstream_stream_body_finished",
        "upstream_protocol_done_sentinel_written",
    )
    diagnostic = {name: rows[-1].get(name) for name in diagnostic_fields} if rows else {}
    pytest.fail(
        "synthetic upstream did not reach the expected bounded state: "
        + marker + " " + json.dumps(diagnostic, sort_keys=True)
    )


def _records(url, marker):
    return [row for row in _stats(url)["records"] if row.get("test_id") == marker]


def _consume(iterator):
    return b"".join(chunk if isinstance(chunk, bytes) else str(chunk).encode() for chunk in iterator).decode(
        "utf-8", errors="replace",
    )


def _create_verified_model(client, owner, provider_key):
    response = client.post(CONNECTIONS, {
        "provider_id": "deepseek",
        "endpoint_profile": "deepseek_default",
        "display_name": "Synthetic DeepSeek",
        "api_key": provider_key,
        "request_id": str(uuid.uuid4()),
    }, format="json")
    assert response.status_code == 201, response.content
    connection = UserAIConnection.objects.get(pk=response.data["id"])
    response = client.post(
        f"{CONNECTIONS}{connection.pk}/models/",
        {"model_id": "deepseek-flash"}, format="json",
    )
    assert response.status_code == 201, response.content
    model = UserAIModelConfig.objects.get(pk=response.data["id"])

    attempt_id = uuid.uuid4()
    AIModelProbeAttempt.objects.create(
        id=attempt_id, request_id=uuid.uuid4(), user=owner,
        connection=connection, model_config=model, model_id=model.model_id,
        model_revision=model.config_revision, probe_kind="text", status="succeeded",
        credential_epoch=connection.credential_epoch,
        credential_version=connection.credential_version,
        endpoint_profile=connection.endpoint_profile,
        endpoint_profile_version=connection.endpoint_profile_version,
        proxy_alias=ALIAS,
    )
    model.last_text_attempt = attempt_id
    model.capability_results = {
        "text": {
            "attempt_id": str(attempt_id), "status": "supported",
            "config_revision": model.config_revision,
            "credential_epoch": connection.credential_epoch,
            "credential_version": connection.credential_version,
            "endpoint_profile": connection.endpoint_profile,
            "endpoint_profile_version": connection.endpoint_profile_version,
        },
    }
    model.save(update_fields=["last_text_attempt", "capability_results"])
    return connection, model, AIModelProbeAttempt.objects.count()


def _enable_deep_research_capability(owner, model):
    """Create synthetic current T02 receipts and a saved T03 deep-research selection."""
    from api.ai_preference_models import TASK_KINDS

    connection = model.connection
    attempt_id = uuid.uuid4()
    AIModelProbeAttempt.objects.create(
        id=attempt_id, request_id=uuid.uuid4(), user=owner,
        connection=connection, model_config=model, model_id=model.model_id,
        model_revision=model.config_revision, probe_kind="tools", status="succeeded",
        credential_epoch=connection.credential_epoch,
        credential_version=connection.credential_version,
        endpoint_profile=connection.endpoint_profile,
        endpoint_profile_version=connection.endpoint_profile_version,
        proxy_alias=ALIAS,
    )
    model.last_tools_attempt = attempt_id
    capabilities = dict(model.capability_results)
    capabilities["tools"] = {
        "attempt_id": str(attempt_id), "status": "supported",
        "config_revision": model.config_revision,
        "credential_epoch": connection.credential_epoch,
        "credential_version": connection.credential_version,
        "endpoint_profile": connection.endpoint_profile,
        "endpoint_profile_version": connection.endpoint_profile_version,
    }
    model.capability_results = capabilities
    model.save(update_fields=["last_tools_attempt", "capability_results"])
    client = APIClient()
    client.force_authenticate(owner)
    response = client.patch('/api/me/ai/task-preferences/', {
        'revision': 0,
        'preferences': [
            {
                'task_kind': kind,
                    'selection_source': (
                        'byok' if kind == 'deep_research'
                        else 'unset' if kind == 'default'
                        else 'inherit'
                    ),
                'model_config_id': str(model.pk) if kind == 'deep_research' else None,
            }
            for kind in TASK_KINDS
        ],
    }, format='json')
    assert response.status_code == 200, response.content


def _wait_translation_response(read, *, timeout_seconds=12, transient_retry_seconds=12,
                                interval=0.03, monotonic=time.monotonic, sleep=time.sleep):
    """GET-only bounded retry for classified SQLite contention; never resubmit work."""
    deadline = monotonic() + timeout_seconds
    transient_deadline = None
    retryable_503 = {"credential_unavailable", "task_storage_busy"}
    while monotonic() < deadline:
        response = read()
        if monotonic() >= deadline:
            raise AssertionError("translation GET did not reach terminal state before its deadline")
        if response.status_code == 503:
            data = response.data if isinstance(response.data, dict) else {}
            if set(data) != {"error_code"} or data.get("error_code") not in retryable_503:
                raise AssertionError("translation GET returned a non-retryable HTTP 503")
            if transient_deadline is None:
                transient_deadline = min(monotonic() + transient_retry_seconds, deadline)
            remaining = transient_deadline - monotonic()
            if remaining <= 0:
                raise AssertionError("translation GET remained HTTP 503 past its retry deadline")
            sleep_for = max(0.0, min(interval, remaining, deadline - monotonic()))
            sleep(sleep_for)
            continue
        if response.status_code != 200:
            raise AssertionError(f"translation GET returned HTTP {response.status_code}")
        data = response.data
        if data["status"] not in {"queued", "running"}:
            return data
        sleep(max(0.0, min(interval, deadline - monotonic())))
    raise AssertionError("translation GET did not reach terminal state before its deadline")


def test_translation_poll_retries_only_classified_get_contention():
    from types import SimpleNamespace

    current = [0.0]
    clock = lambda: current[0]
    sleep = lambda amount: current.__setitem__(0, current[0] + amount)
    responses = [
        SimpleNamespace(status_code=503, data={"error_code": "credential_unavailable"}),
        SimpleNamespace(status_code=503, data={"error_code": "task_storage_busy"}),
        SimpleNamespace(status_code=200, data={"status": "succeeded", "result": {"result_id": 3}}),
    ]
    calls = []
    result = _wait_translation_response(
        lambda: calls.append(1) or responses.pop(0),
        monotonic=clock, sleep=sleep,
    )
    assert result["status"] == "succeeded"
    assert result["result"]["result_id"] == 3
    assert len(calls) == 3

    current[0] = 0.0
    persistent_calls = []
    def persistent_read():
        persistent_calls.append(1)
        return SimpleNamespace(status_code=503, data={"error_code": "task_storage_busy"})
    with pytest.raises(AssertionError, match="retry deadline"):
        _wait_translation_response(
            persistent_read, interval=1.0, transient_retry_seconds=3.0,
            monotonic=clock, sleep=sleep,
        )
    assert len(persistent_calls) == 4

    current[0] = 0.0
    terminal_calls = []
    terminal = _wait_translation_response(
        lambda: terminal_calls.append(1) or SimpleNamespace(
            status_code=200, data={"status": "failed", "result": None},
        ),
        monotonic=clock, sleep=sleep,
    )
    assert terminal["status"] == "failed"
    assert len(terminal_calls) == 1

    current[0] = 0.0
    slow_calls = []
    def slow_success():
        slow_calls.append(1)
        current[0] += 13.0
        return SimpleNamespace(status_code=200, data={"status": "succeeded"})
    with pytest.raises(AssertionError, match="deadline"):
        _wait_translation_response(slow_success, monotonic=clock, sleep=sleep)
    assert len(slow_calls) == 1

    for status, data in (
        (403, {"error_code": "permission_denied"}),
        (409, {"error_code": "model_changed"}),
        (500, {"error_code": "internal_error"}),
        (503, {"error_code": "provider_credential_unavailable"}),
        (503, {"error_code": "task_storage_busy", "retry_after": 1}),
    ):
        current[0] = 0.0
        immediate_calls = []
        with pytest.raises(AssertionError):
            _wait_translation_response(
                lambda status=status, data=data:
                    immediate_calls.append(1) or SimpleNamespace(status_code=status, data=data),
                monotonic=clock, sleep=sleep,
            )
        assert len(immediate_calls) == 1


def test_provider_key_identity_hash_rejects_same_tenant_seed():
    owner_key = "sk-t00-owner-only-synthetic-random"
    expected_hash = upstream.provider_key_sha256(owner_key)

    assert upstream.KEY_LABELS["sk-t00-provider-a-synthetic"] == "tenant-a"
    assert upstream.provider_key_identity_matches(owner_key, expected_hash) is True
    assert upstream.provider_key_identity_matches(
        "sk-t00-provider-a-synthetic", expected_hash,
    ) is False


def _assert_native_deepseek_request(rows, *, marker, stream, terminal, owner_key_match=False):
    assert len(rows) == 1
    row = rows[0]
    assert row["test_id"] == marker
    assert row["path"] == "/v1/chat/completions"
    assert row["model"] == "deepseek-flash"
    assert row["stream"] is stream
    if stream:
        assert row["thinking_disabled"] is True
    assert row["tenant"] == "tenant-a"
    assert row["provider_key_match"] is True
    if owner_key_match:
        assert row["provider_key_identity_match"] is True
    assert row["project_key_match"] is False
    assert row["provider_auth_scheme"] == "bearer"
    assert row["upstream_terminal"] == terminal
    return row


@pytest.mark.django_db(transaction=True)
def test_t04_real_django_sdk_proxy_deepseek_stream_terminal_and_cancel():
    # Production mode is explicit in the CI command so settings.py cannot read
    # either repository .env. Every database and key below is synthetic.
    from django.conf import settings
    assert settings.DJANGO_ENV == "production"
    assert Path(database_connection.settings_dict["NAME"]).is_file()
    # Production defaults point at /var/lib/newshub. This synthetic process
    # must own all derived state as well as its disposable SQLite database.
    private_root = Path(os.environ["TMPDIR"]).resolve()
    assert Path(settings.CHROMA_DATA_DIR).resolve().is_relative_to(private_root)
    assert Path(settings.TTS_CACHE_DIR).resolve().is_relative_to(private_root)
    with database_connection.cursor() as cursor:
        assert cursor.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    proxy_python = os.environ.get("T00_PROXY_PYTHON")
    assert proxy_python and Path(proxy_python).is_file(), "full CI must provide prepared pinned Proxy Python"

    old_labels = upstream.KEY_LABELS.copy()
    with upstream.LOCK:
        upstream.RECORDS.clear()
        upstream.RELEASE_EVENTS.clear()
        upstream.ACTIVE_STREAM_PRODUCERS = 0
    server = QuietServer(("127.0.0.1", 0), upstream.Handler)
    upstream_url = f"http://127.0.0.1:{server.server_port}"
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    proxy = None
    previous_t09_key_hashes = {}
    try:
        proxy = LocalProxy(proxy_python, upstream_url)
        proxy.start()
        provider_key = "sk-t04-e2e-" + secrets.token_hex(24)
        upstream.KEY_LABELS[provider_key] = "tenant-a"

        with override_settings(
            ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"],
            PUBLIC_SITE_MODE="full",
            PUBLIC_AI_ENABLED=True,
            AI_BYOK_ENABLED=True,
            PROVIDER_CREDENTIAL_ENCRYPTION_KEY="CI-only-synthetic-t04-encryption-material",
            AI_BYOK_GATEWAY_URL=proxy.url,
            AI_BYOK_GATEWAY_PROJECT_KEY=proxy.project_keys["tenant-a"],
            AI_BYOK_GATEWAY_PROJECT_KEY_FILE="",
            SECURE_SSL_REDIRECT=False,
            SESSION_COOKIE_SECURE=False,
            CSRF_COOKIE_SECURE=False,
            SECURE_HSTS_SECONDS=0,
        ):
            owner = get_user_model().objects.create_user(
                username="t04-local-proxy-owner", password="synthetic-only",
            )
            client = APIClient()
            client.force_login(owner)
            source = Source.objects.create(
                name="T04 synthetic publisher", url="https://publisher.example/",
            )
            category = Category.objects.create(name="T04 synthetic category", slug="t04-local-proxy")
            news = public_legacy_article(News.objects.create(
                title="Synthetic story", url="https://publisher.example/story",
                source=source, category=category, content="Synthetic article context.",
                publish_time=timezone.now(),
            ))
            chat_url = f"/api/news/{news.pk}/chat/"
            connection, model, probe_receipt_count = _create_verified_model(
                client, owner, provider_key,
            )

            # Non-stream text and tool-call compatibility stay on the same
            # native alias and exact same local Proxy process.
            from openai import OpenAI
            sdk = OpenAI(
                api_key=proxy.project_keys["tenant-a"],
                base_url=f"{proxy.url}/v1",
                max_retries=0,
            )
            try:
                text_marker = "T00_T04_E2E_T02_TEXT_A"
                text_result = sdk.chat.completions.create(
                    model=ALIAS, stream=False,
                    messages=[{"role": "user", "content": text_marker}],
                    extra_body={"api_key": provider_key},
                )
                assert text_result.choices[0].message.content == "synthetic t00 chat pass"
                _assert_native_deepseek_request(
                    _records(upstream_url, text_marker), marker=text_marker,
                    stream=False, terminal="finish_reason_stop",
                )

                tool_marker = "T00_T04_E2E_T02_TOOL_R1_A"
                tool_result = sdk.chat.completions.create(
                    model=ALIAS, stream=False,
                    messages=[{"role": "user", "content": tool_marker}],
                    tools=[{
                        "type": "function",
                        "function": {
                            "name": "lookup_weather",
                            "description": "Synthetic local test",
                            "parameters": {
                                "type": "object",
                                "properties": {"city": {"type": "string"}},
                                "required": ["city"],
                                "additionalProperties": False,
                            },
                        },
                    }],
                    tool_choice="auto",
                    extra_body={"api_key": provider_key},
                )
                assert tool_result.choices[0].finish_reason == "tool_calls"
                assert tool_result.choices[0].message.tool_calls[0].function.name == "lookup_weather"
                _assert_native_deepseek_request(
                    _records(upstream_url, tool_marker), marker=tool_marker,
                    stream=False, terminal="tool_call_turn",
                )
            finally:
                sdk.close()

            # Read the real Django StreamingHttpResponse incrementally. The
            # fixture holds the terminal behind an explicit barrier after the
            # first content delta, proving this is not buffered.
            turn = uuid.uuid4()
            success_marker = "T00_T04_E2E_SUCCESS_STREAM_HOLD_A"
            response = client.post(chat_url, {
                "question": success_marker, "model_config_id": str(model.pk),
                "billing_consent": True, "turn_id": str(turn),
            }, format="json")
            assert response.status_code == 200
            iterator = iter(response.streaming_content)
            received = []
            while True:
                chunk = next(iterator)
                text = chunk.decode("utf-8", errors="replace") if isinstance(chunk, bytes) else str(chunk)
                received.append(text)
                if "synthetic t00 stream" in text:
                    break
            held_delta = _wait_record(
                upstream_url, success_marker,
                lambda row: row.get("stream_hold_waiting") is True,
            )
            assert held_delta["upstream_stream_events_written"] >= 2
            assert held_delta["upstream_stream_body_finished"] is False
            release_delta = urllib.request.Request(
                upstream_url + "/test/release",
                data=json.dumps({"test_id": success_marker}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with OPENER.open(release_delta, timeout=3) as released:
                assert json.load(released)["released"] is True
            wire = "".join(received) + _consume(iterator)
            assert '"status": "complete"' in wire
            assert '"type": "chat_model"' in wire
            assert provider_key not in wire
            assert proxy.project_keys["tenant-a"] not in wire
            success_row = _assert_native_deepseek_request(
                _records(upstream_url, success_marker), marker=success_marker,
                stream=True, terminal="finish_reason_stop",
            )
            assert success_row["stream_hold_released"] is True
            assert success_row["client_disconnected"] is False
            assert success_row["upstream_stream_body_finished"] is True
            turn_row = ArticleChatTurn.objects.get(pk=turn)
            assert turn_row.status == "complete"
            session = ChatSession.objects.get(user=owner, news=news)
            assert [message["role"] for message in session.messages] == ["user", "assistant"]
            assert session.messages[-1]["status"] == "complete"
            assert session.messages[-1]["content"] == "synthetic t00 stream"
            assert AIModelProbeAttempt.objects.count() == probe_receipt_count

            assert client.delete(chat_url).data["status"] == "cleared"

            # Closing the Django response after an early delta must propagate
            # GeneratorExit through the API/service to close the SDK stream.
            close_turn = uuid.uuid4()
            close_marker = "T00_T04_E2E_CLIENT_CLOSE_STREAM_HOLD_A"
            close_response = client.post(chat_url, {
                "question": close_marker, "model_config_id": str(model.pk),
                "billing_consent": True, "turn_id": str(close_turn),
            }, format="json")
            assert close_response.status_code == 200
            close_iterator = iter(close_response.streaming_content)
            close_chunks = []
            while True:
                chunk = next(close_iterator)
                text = chunk.decode("utf-8", errors="replace") if isinstance(chunk, bytes) else str(chunk)
                close_chunks.append(text)
                if "synthetic t00 stream" in text:
                    break
            held_close = _wait_record(
                upstream_url, close_marker,
                lambda row: row.get("stream_hold_waiting") is True,
            )
            assert held_close["upstream_stream_body_finished"] is False
            close_response.close()
            # Do not release the terminal to infer closure from a failed write.
            # Require direct peer EOF/reset while the provider is still held.
            closed_row = _wait_record(
                upstream_url, close_marker,
                lambda row: row.get("stream_hold_peer_close_state") in {"eof", "reset"},
            )
            assert closed_row["client_disconnected"] is True
            assert closed_row["producer_exit_reason"] == "client_disconnect"
            assert not closed_row.get("stream_hold_released", False)
            assert not closed_row.get("upstream_stream_body_finished", False)
            assert not closed_row.get("upstream_protocol_done_sentinel_written", False)
            assert '"status": "complete"' not in "".join(close_chunks)
            assert '"type": "chat_model"' not in "".join(close_chunks)
            assert provider_key not in "".join(close_chunks)
            assert ArticleChatTurn.objects.get(pk=close_turn).status == "cancelled"
            session.refresh_from_db()
            assert [message["role"] for message in session.messages] == ["user"]
            deadline = time.monotonic() + 3
            while _stats(upstream_url)["active_stream_producers"] and time.monotonic() < deadline:
                time.sleep(0.02)
            assert _stats(upstream_url)["active_stream_producers"] == 0
            assert client.delete(chat_url).data["status"] == "cleared"

            # Raw EOF without an upstream finish_reason is rejected by the
            # pinned whole-iterator hook, even though the SDK/Proxy may have
            # emitted partial text before discovering the incomplete stream.
            eof_turn = uuid.uuid4()
            eof_marker = "T00_T04_E2E_EOF_A"
            eof_response = client.post(chat_url, {
                "question": eof_marker, "model_config_id": str(model.pk),
                "billing_consent": True, "turn_id": str(eof_turn),
            }, format="json")
            assert eof_response.status_code == 200
            eof_wire = _consume(eof_response.streaming_content)
            assert '"status": "failed"' in eof_wire
            assert '"status": "complete"' not in eof_wire
            assert '"type": "chat_model"' not in eof_wire
            assert provider_key not in eof_wire
            assert proxy.project_keys["tenant-a"] not in eof_wire
            eof_row = _assert_native_deepseek_request(
                _records(upstream_url, eof_marker), marker=eof_marker,
                stream=True, terminal="normal_eof_without_protocol_terminal",
            )
            assert eof_row["upstream_stream_body_finished"] is True
            assert ArticleChatTurn.objects.get(pk=eof_turn).status == "dispatched"
            session.refresh_from_db()
            assert [message["role"] for message in session.messages] == ["user"]
            assert AIModelProbeAttempt.objects.count() == probe_receipt_count

            assert client.delete(chat_url).data["status"] == "cleared"

            # Cancel from a second authenticated tab while the upstream
            # request is in flight. The durable receipt fences terminal commit;
            # after the controlled provider response resumes, the next read
            # boundary observes cancellation and closes the stream. Already-
            # dispatched provider work may still incur a charge.
            cancel_turn = uuid.uuid4()
            cancel_marker = "T00_T04_E2E_CANCEL_HOLD_A"
            cancel_response = client.post(chat_url, {
                "question": cancel_marker, "model_config_id": str(model.pk),
                "billing_consent": True, "turn_id": str(cancel_turn),
            }, format="json")
            assert cancel_response.status_code == 200
            cancel_chunks = []
            errors = []

            def consume_cancelled_response():
                close_old_connections()
                try:
                    cancel_chunks.append(_consume(cancel_response.streaming_content))
                except BaseException as error:
                    errors.append(error)
                finally:
                    close_old_connections()

            reader = threading.Thread(target=consume_cancelled_response, daemon=True)
            reader.start()
            held = _wait_record(upstream_url, cancel_marker, lambda row: row.get("held_waiting") is True)
            assert held["path"] == "/v1/chat/completions"
            cancel_client = APIClient()
            cancel_client.force_login(owner)
            cancel_result = cancel_client.post(
                f"{chat_url}{cancel_turn}/cancel/", {}, format="json",
            )
            assert cancel_result.status_code == 200, cancel_result.content
            assert cancel_result.data["status"] == "cancelled"
            release = urllib.request.Request(
                upstream_url + "/test/release",
                data=json.dumps({"test_id": cancel_marker}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with OPENER.open(release, timeout=3) as released:
                assert json.load(released)["released"] is True
            reader.join(timeout=12)
            assert not reader.is_alive(), "cancelled T04 response did not terminate"
            assert errors == []
            assert provider_key not in "".join(cancel_chunks)
            assert proxy.project_keys["tenant-a"] not in "".join(cancel_chunks)
            terminal_cancel = _wait_record(
                upstream_url, cancel_marker,
                lambda row: row.get("client_disconnected") is True
                or row.get("upstream_stream_body_finished") is True,
            )
            assert terminal_cancel["client_disconnected"] is True
            assert not terminal_cancel.get("upstream_protocol_done_sentinel_written", False)
            assert len(_records(upstream_url, cancel_marker)) == 1
            assert ArticleChatTurn.objects.get(pk=cancel_turn).status == "cancelled"
            session.refresh_from_db()
            assert [message["role"] for message in session.messages] == ["user"]
            assert AIModelProbeAttempt.objects.count() == probe_receipt_count
            assert _stats(upstream_url)["active_stream_producers"] == 0

            # T05 uses its own durable worker/admission path through this exact
            # SDK/Proxy process, not the T04 business generator or a fake gateway.
            def translation_article(marker, *, full_content=None):
                article = public_legacy_article(News.objects.create(
                    title="T05/T06 synthetic article", url="https://publisher.example/" + marker,
                    source=source, category=category, content="Synthetic summary",
                    full_content=full_content if full_content is not None else "# Full Markdown\n\n" + marker,
                    full_content_state="legacy",
                    publish_time=timezone.now(),
                ))

                stored = article_snapshot(article, owner)
                assert stored.scope == "full"
                assert require_current(owner, stored, full=True).markdown == article.full_content
                return article

            def wait_translation(task_id):
                return _wait_translation_response(
                    lambda: client.get(f"/api/me/ai/translations/{task_id}/"),
                )

            t05_marker = "T00_T05_E2E_SUCCESS_STREAM_HOLD_A"
            t05_news = translation_article(t05_marker)
            request_id = str(uuid.uuid4())
            start = client.post(f"/api/news/{t05_news.pk}/byok-translation/", {
                "model_config_id": str(model.pk), "billing_consent": True, "target_language": "zh",
            }, format="json", HTTP_IDEMPOTENCY_KEY=request_id)
            assert start.status_code == 202, start.content
            task_id = start.data["task_id"]
            held = _wait_record(upstream_url, t05_marker,
                                lambda row: row.get("stream_hold_waiting") is True)
            assert not held["upstream_stream_body_finished"]
            observation = client.get(f"/api/me/ai/translations/{task_id}/events/")
            first = next(iter(observation.streaming_content))
            assert b"succeeded" not in first
            observation.close()  # Only disconnect the observer, not the worker.
            observed = client.get(f"/api/me/ai/translations/{task_id}/")
            assert observed.status_code == 200, observed.content
            assert observed.data["status"] == "running"
            release = urllib.request.Request(upstream_url + "/test/release",
                data=json.dumps({"test_id": t05_marker}).encode(),
                headers={"Content-Type": "application/json"}, method="POST")
            with OPENER.open(release, timeout=3) as released:
                assert json.load(released)["released"] is True
            completed = wait_translation(task_id)
            assert completed["status"] == "succeeded", completed
            assert completed["result"]["content"] == "synthetic t00 stream"
            result_id = completed["result"]["result_id"]
            assert ChatGPTArticleTranslation.objects.get(pk=result_id).user_id == owner.pk
            again = client.get(f"/api/news/{t05_news.pk}/byok-translation/")
            assert again.data["task"]["task_id"] == task_id
            assert again.data["task"]["result"]["result_id"] == result_id
            _assert_native_deepseek_request(_records(upstream_url, t05_marker),
                marker=t05_marker, stream=True, terminal="finish_reason_stop")
            assert provider_key not in json.dumps(completed)
            assert proxy.project_keys["tenant-a"] not in json.dumps(completed)

            t05_eof = "T00_T05_E2E_EOF_A"
            eof_news = translation_article(t05_eof)
            failed_start = client.post(f"/api/news/{eof_news.pk}/byok-translation/", {
                "model_config_id": str(model.pk), "billing_consent": True, "target_language": "zh",
            }, format="json", HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()))
            assert failed_start.status_code == 202, failed_start.content
            failed = wait_translation(failed_start.data["task_id"])
            assert failed["status"] == "failed"
            assert failed["result"] is None
            assert not ChatGPTArticleTranslation.objects.filter(news=eof_news).exists()
            assert not SharedArticleTranslation.objects.filter(news__in=[t05_news, eof_news]).exists()
            _assert_native_deepseek_request(_records(upstream_url, t05_eof),
                marker=t05_eof, stream=True, terminal="normal_eof_without_protocol_terminal")

            # T06 long translation traverses the same real OpenAI SDK + pinned
            # Proxy path using only synthetic credentials/upstream responses.
            t06_chunk1 = "T00_T06_E2E_SUCCESS_CHUNK1_A"
            t06_chunk2 = "T00_T06_E2E_SUCCESS_CHUNK2_A"
            t06_body = "a" * 5000 + " " + t06_chunk1 + "\n\n" + "b" * 5000 + " " + t06_chunk2
            t06_news = translation_article(t06_chunk1, full_content=t06_body)
            t06_request_id = str(uuid.uuid4())
            t06_start = client.post(f"/api/news/{t06_news.pk}/byok-translation/", {
                "model_config_id": str(model.pk), "billing_consent": True, "target_language": "zh",
            }, format="json", HTTP_IDEMPOTENCY_KEY=t06_request_id)
            assert t06_start.status_code == 202, t06_start.content
            t06_task_id = t06_start.data["task_id"]
            t06_result = wait_translation(t06_task_id)
            assert t06_result["status"] == "succeeded", t06_result
            assert t06_result["result"]["content"] == "synthetic t00 stream\n\nsynthetic t00 stream"
            result_id = t06_result["result"]["result_id"]
            assert ChatGPTArticleTranslation.objects.get(pk=result_id).user_id == owner.pk
            assert not SharedArticleTranslation.objects.filter(news=t06_news).exists()
            _assert_native_deepseek_request(_records(upstream_url, t06_chunk1),
                marker=t06_chunk1, stream=True, terminal="finish_reason_stop")
            _assert_native_deepseek_request(_records(upstream_url, t06_chunk2),
                marker=t06_chunk2, stream=True, terminal="finish_reason_stop")
            detail = client.get(f"/api/me/ai/translations/{t06_task_id}/")
            latest = client.get(f"/api/news/{t06_news.pk}/byok-translation/")
            assert detail.status_code == 200 and detail.data["result"]["result_id"] == result_id
            assert latest.status_code == 200
            assert latest.data["task"]["result"]["result_id"] == result_id
            assert len(_records(upstream_url, t06_chunk1)) == 1
            assert len(_records(upstream_url, t06_chunk2)) == 1

            t06_failure_chunk1 = "T00_T06_E2E_LENGTH_CHUNK1_A"
            t06_failure_chunk2 = "T00_T06_E2E_LENGTH_INCOMPLETE_CHUNK2_A"
            t06_failure_body = "c" * 5000 + " " + t06_failure_chunk1 + "\n\n" + "d" * 5000 + " " + t06_failure_chunk2
            t06_failure_news = translation_article(t06_failure_chunk1, full_content=t06_failure_body)
            t06_failure_request_id = str(uuid.uuid4())
            t06_failure_start = client.post(f"/api/news/{t06_failure_news.pk}/byok-translation/", {
                "model_config_id": str(model.pk), "billing_consent": True, "target_language": "zh",
            }, format="json", HTTP_IDEMPOTENCY_KEY=t06_failure_request_id)
            assert t06_failure_start.status_code == 202, t06_failure_start.content
            t06_failed = wait_translation(t06_failure_start.data["task_id"])
            assert t06_failed["status"] == "failed"
            assert t06_failed["result"] is None
            assert t06_failed["progress"] == ""  # Redis drafts are not durable results.
            assert not ChatGPTArticleTranslation.objects.filter(news=t06_failure_news).exists()
            assert not SharedArticleTranslation.objects.filter(news=t06_failure_news).exists()
            _assert_native_deepseek_request(_records(upstream_url, t06_failure_chunk1),
                marker=t06_failure_chunk1, stream=True, terminal="finish_reason_stop")
            _assert_native_deepseek_request(_records(upstream_url, t06_failure_chunk2),
                marker=t06_failure_chunk2, stream=True, terminal="finish_reason_length")
            detail = client.get(f"/api/me/ai/translations/{t06_failure_start.data['task_id']}/")
            latest = client.get(f"/api/news/{t06_failure_news.pk}/byok-translation/")
            assert detail.status_code == 200 and detail.data["result"] is None
            assert latest.status_code == 200 and latest.data["task"]["result"] is None
            assert len(_records(upstream_url, t06_failure_chunk1)) == 1
            assert len(_records(upstream_url, t06_failure_chunk2)) == 1
            assert AIModelProbeAttempt.objects.count() == probe_receipt_count


            # T09 first-run requests use the real SDK and the same pinned local
            # Proxy/upstream as T04. Public AI is deliberately disabled to prove
            # only the explicit, currently verified BYOK path reaches the model.
            from api.models import ResearchRun
            _enable_deep_research_capability(owner, model)
            t09_markers = (
                "T00_T09_RESEARCH_STOP_A",
                "T00_T09_RESEARCH_TOOL_A",
                "T00_T09_RESEARCH_NO_FINISH_A",
                "T00_T09_RESEARCH_TRUNCATED_A",
                "T00_T09_RESEARCH_HTTP_ERROR_A",
                "T00_T09_RESEARCH_INCOMPLETE_A",
            )
            expected_provider_key_hash = upstream.provider_key_sha256(provider_key)
            with upstream.LOCK:
                previous_t09_key_hashes = {
                    marker: upstream.EXPECTED_PROVIDER_KEY_HASHES.get(marker)
                    for marker in t09_markers
                }
                upstream.EXPECTED_PROVIDER_KEY_HASHES.update({
                    marker: expected_provider_key_hash for marker in t09_markers
                })

            def run_t09(marker, expected_status):
                response = client.post(
                    "/api/research/",
                    {
                        "query": marker,
                        "local_only": True,
                            "execution_source": "byok",
                        "model_config_id": str(model.pk),
                        "consent": True,
                    },
                    format="json",
                    HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
                )
                assert response.status_code == 200, response.content
                wire = _consume(response.streaming_content)
                run = ResearchRun.objects.get(pk=response["Run-ID"])
                assert run.status == expected_status, {
                    "marker": marker, "status": run.status,
                    "error_code": run.error_code,
                }
                assert provider_key not in wire
                assert proxy.project_keys["tenant-a"] not in wire
                return run, wire

            with override_settings(PUBLIC_AI_ENABLED=False):
                stop_marker = "T00_T09_RESEARCH_STOP_A"
                stop_run, stop_wire = run_t09(stop_marker, "succeeded")
                stop_rows = _records(upstream_url, stop_marker)
                stop_row = _assert_native_deepseek_request(
                    stop_rows, marker=stop_marker, stream=False, terminal="finish_reason_stop",
                    owner_key_match=True,
                )
                assert stop_row["upstream_raw_http_status"] == 200
                assert stop_row["upstream_raw_body_complete"] is True
                assert stop_row["upstream_raw_finish_reason"] == "stop"
                assert stop_row["upstream_raw_terminal_present"] is True
                assert "synthetic t00 chat pass" in stop_wire

                tool_marker = "T00_T09_RESEARCH_TOOL_A"
                tool_run, tool_wire = run_t09(tool_marker, "succeeded")
                tool_rows = _records(upstream_url, tool_marker)
                tool_call_row = _assert_native_deepseek_request(
                    [row for row in tool_rows if row["upstream_terminal"] == "tool_call_turn"],
                    marker=tool_marker, stream=False, terminal="tool_call_turn", owner_key_match=True,
                )
                tool_result_row = _assert_native_deepseek_request(
                    [row for row in tool_rows if row["upstream_terminal"] == "finish_reason_stop"],
                    marker=tool_marker, stream=False, terminal="finish_reason_stop", owner_key_match=True,
                )
                assert [tool_call_row["upstream_raw_finish_reason"], tool_result_row["upstream_raw_finish_reason"]] == [
                    "tool_calls", "stop",
                ]
                assert all(row["upstream_raw_body_complete"] is True for row in tool_rows)
                assert "tool_result" in tool_wire
                assert tool_run.session.messages[-1]["role"] == "assistant"

                failure_cases = [
                    ("T00_T09_RESEARCH_NO_FINISH_A", "missing_finish_reason", True, None, "failed"),
                    ("T00_T09_RESEARCH_TRUNCATED_A", "truncated_http_body", False, None, "failed"),
                    ("T00_T09_RESEARCH_HTTP_ERROR_A", "http_503_no_completion", True, 503, "failed"),
                ]
                for marker, terminal, complete, status_code, expected in failure_cases:
                    run, wire = run_t09(marker, expected)
                    rows = _records(upstream_url, marker)
                    row = _assert_native_deepseek_request(
                        rows, marker=marker, stream=False, terminal=terminal, owner_key_match=True,
                    )
                    assert row["upstream_raw_body_complete"] is complete
                    assert row["upstream_raw_http_status"] == (status_code or 200)
                    assert row["upstream_raw_terminal_present"] is False
                    assert row["upstream_raw_finish_reason"] is None
                    assert run.session.messages == []
                    assert '"type": "complete"' not in wire
                    assert ResearchRun.objects.get(pk=run.pk).status == "failed"

                # A proven but incomplete raw terminal must remain visibly
                # incomplete through the Proxy and never commit a report.
                marker = "T00_T09_RESEARCH_INCOMPLETE_A"
                run, wire = run_t09(marker, "failed")
                row = _assert_native_deepseek_request(
                    _records(upstream_url, marker), marker=marker, stream=False,
                    terminal="finish_reason_length", owner_key_match=True,
                )
                assert row["upstream_raw_body_complete"] is True
                assert row["upstream_raw_http_status"] == 200
                assert row["upstream_raw_terminal_present"] is True
                assert row["upstream_raw_finish_reason"] == "length"
                assert run.session.messages == []
                assert '"type": "complete"' not in wire
                assert ResearchRun.objects.get(pk=run.pk).status == "failed"

    finally:
        with upstream.LOCK:
            pending_releases = list(upstream.RELEASE_EVENTS.values())
        for release_event in pending_releases:
            release_event.set()
        if proxy is not None:
            proxy.close()
            assert proxy.cleanup_complete
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=3)
        upstream.KEY_LABELS = old_labels
        with upstream.LOCK:
            for marker, previous_hash in previous_t09_key_hashes.items():
                if previous_hash is None:
                    upstream.EXPECTED_PROVIDER_KEY_HASHES.pop(marker, None)
                else:
                    upstream.EXPECTED_PROVIDER_KEY_HASHES[marker] = previous_hash
            upstream.RECORDS.clear()
            upstream.RELEASE_EVENTS.clear()
