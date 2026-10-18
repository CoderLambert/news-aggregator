"""Offline BYOK gateway transport regressions.

This adapter forwards the true OpenAI SDK stream only for the exact T04
DeepSeek alias. Raw terminal verification belongs to LiteLLM's pinned Proxy
hook. All values are synthetic and no provider key is sent to a real service.
"""
from types import SimpleNamespace

import pytest

from api.services.ai_gateway import AIGatewayError, _GatewayCompletions


class SyntheticGateway:
    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.reply


class SyntheticStream:
    def __init__(self):
        self.closed = False

    def __iter__(self):
        yield SimpleNamespace(choices=[SimpleNamespace(
            delta=SimpleNamespace(content="synthetic delta"),
            finish_reason=None,
        )])

    def close(self):
        self.closed = True


def test_exact_deepseek_stream_is_forwarded_without_buffering_or_retry():
    stream = SyntheticStream()
    fake = SyntheticGateway(stream)
    adapter = _GatewayCompletions(fake, "only-synthetic-provider-key")
    returned = adapter.create(
        stream=True, model="deepseek/deepseek-chat",
        messages=[{"role": "user", "content": "synthetic"}],
    )
    assert returned is stream
    assert fake.calls == [{
        "stream": True,
        "model": "deepseek/deepseek-chat",
        "messages": [{"role": "user", "content": "synthetic"}],
        "extra_body": {"api_key": "only-synthetic-provider-key"},
    }]
    assert next(iter(returned)).choices[0].delta.content == "synthetic delta"
    assert not stream.closed
    returned.close()
    assert stream.closed


@pytest.mark.parametrize("model", [
    "deepseek/other", "openai/gpt-test", "deepseek/*",
])
def test_other_model_stream_is_rejected_before_dispatch(model):
    fake = SyntheticGateway(SyntheticStream())
    adapter = _GatewayCompletions(fake, "only-synthetic-provider-key")
    with pytest.raises(AIGatewayError):
        adapter.create(stream=True, model=model, messages=[])
    assert fake.calls == []


def test_exact_alias_non_stream_tool_calls_remain_available():
    tool_reply = SimpleNamespace(choices=[SimpleNamespace(
        finish_reason="tool_calls",
        message=SimpleNamespace(content=None, tool_calls=[]),
    )])
    fake = SyntheticGateway(tool_reply)
    adapter = _GatewayCompletions(fake, "only-synthetic-provider-key")
    assert adapter.create(model="deepseek/deepseek-chat", messages=[]) is tool_reply
    assert fake.calls == [{
        "model": "deepseek/deepseek-chat",
        "messages": [],
        "extra_body": {"api_key": "only-synthetic-provider-key"},
    }]
