"""Fail-closed, offline BYOK gateway terminal contracts.

Only a verified non-streaming Chat Completions text response may be exposed
through the compatibility SSE adapter. These synthetic fixtures never contact
a real provider or consume user keys.
"""
from types import SimpleNamespace

import pytest

from api.services.provider_credentials import (
    ProviderCredentialError,
    _GatewayCompletions,
)


def _completion(*, reason='stop', content='complete reply', choices=1):
    return SimpleNamespace(choices=[
        SimpleNamespace(
            finish_reason=reason,
            message=SimpleNamespace(content=content),
        )
        for _ in range(choices)
    ])


class SyntheticGateway:
    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.reply


@pytest.mark.parametrize(('reason', 'content', 'count'), [
    ('length', 'partial text', 1),
    ('content_filter', 'filtered content', 1),
    ('tool_calls', 'unexpected tool stream', 1),
    (None, 'terminal missing', 1),
    ('stop', None, 1),
    ('stop', '', 1),
    ('stop', [{'type': 'text', 'text': 'multimodal'}], 1),
    ('stop', 'could be complete', 0),
    ('stop', 'ambiguous multi-choice', 2),
])
def test_gateway_stream_rejects_unverified_terminal_without_yielding_text(reason, content, count):
    fake = SyntheticGateway(_completion(reason=reason, content=content, choices=count))
    adapter = _GatewayCompletions(fake, 'only-synthetic-provider-key')
    with pytest.raises(ProviderCredentialError):
        adapter.create(stream=True, model='deepseek/deepseek-chat', messages=[])
    assert len(fake.calls) == 1
    assert fake.calls[0]['stream'] is False
    assert fake.calls[0]['extra_body'] == {'api_key': 'only-synthetic-provider-key'}


def test_complete_gateway_terminal_exposes_exactly_one_text_chunk_and_close():
    fake = SyntheticGateway(_completion())
    adapter = _GatewayCompletions(fake, 'only-synthetic-provider-key')
    stream = adapter.create(stream=True, model='deepseek/deepseek-chat', messages=[])
    chunks = list(stream)
    assert len(chunks) == 1
    assert chunks[0].choices[0].delta.content == 'complete reply'
    assert chunks[0].choices[0].finish_reason == 'stop'
    assert stream.close() is None


def test_non_streaming_tool_calls_remain_available_for_research():
    reply = _completion(reason='tool_calls', content=None)
    fake = SyntheticGateway(reply)
    adapter = _GatewayCompletions(fake, 'only-synthetic-provider-key')
    assert adapter.create(model='deepseek/deepseek-chat', messages=[]) is reply
    assert 'stream' not in fake.calls[0]
    assert fake.calls[0]['extra_body'] == {'api_key': 'only-synthetic-provider-key'}


def test_incomplete_gateway_stream_never_leaks_partial_text_into_chat():
    from api.services.llm_translator import stream_chat

    fake = SyntheticGateway(_completion(reason='length', content='PARTIAL_NEVER_DISPLAY'))
    wrapped = _GatewayCompletions(fake, 'only-synthetic-provider-key')
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=wrapped),
        _newshub_max_attempts=1,
    )
    result = list(stream_chat(
        [{'role': 'user', 'content': 'synthetic request'}],
        clients=[(client, 'deepseek/deepseek-chat')],
        require_completed=False,
    ))
    assert not any('PARTIAL_NEVER_DISPLAY' in chunk for chunk in result)
    assert len(fake.calls) == 1
