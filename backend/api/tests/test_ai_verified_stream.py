"""SDK-normalized usage trailers cannot replace or invalidate a verified stop."""
from copy import deepcopy

import pytest
from openai.types.chat import ChatCompletionChunk

from api.services.ai_verified_stream import IncompleteStream, verified_text_deltas


USAGE = {'prompt_tokens': 4, 'completion_tokens': 5, 'total_tokens': 9}


def frame(*, content=None, finish=None, usage=None, choices=None):
    return ChatCompletionChunk(
        id='synthetic-stream', object='chat.completion.chunk', created=1,
        model='synthetic-model', usage=usage,
        choices=choices if choices is not None else [
            {'index': 0, 'delta': {'content': content}, 'finish_reason': finish},
        ],
    )


def consume(frames):
    return ''.join(verified_text_deltas(iter(frames), check=lambda: None, max_chars=100))


@pytest.mark.parametrize('normalized_choice', [False, True])
def test_verified_stop_accepts_one_empty_usage_trailer(normalized_choice):
    trailer = frame(usage=USAGE, choices=None if normalized_choice else [])
    assert consume([frame(content='answer'), frame(finish='stop'), trailer]) == 'answer'


@pytest.mark.parametrize('mutation', [
    'missing_stop', 'duplicate_usage', 'content', 'role', 'tool_call',
    'refusal', 'reasoning', 'wrong_index', 'length', 'duplicate_stop',
])
def test_usage_trailer_cannot_weaken_terminal_validation(mutation):
    trailer = frame(usage=deepcopy(USAGE))
    frames = [frame(content='answer'), frame(finish='stop'), trailer]
    delta = trailer.choices[0].delta
    if mutation == 'missing_stop':
        frames.pop(1)
    elif mutation == 'duplicate_usage':
        frames.append(frame(usage=USAGE))
    elif mutation == 'content':
        delta.content = 'unexpected text'
    elif mutation == 'role':
        delta.role = 'assistant'
    elif mutation == 'tool_call':
        delta.tool_calls = [{'index': 0}]
    elif mutation == 'refusal':
        delta.refusal = 'refused'
    elif mutation == 'reasoning':
        delta.reasoning_content = 'private reasoning'
    elif mutation == 'wrong_index':
        trailer.choices[0].index = 1
    elif mutation == 'length':
        trailer.choices[0].finish_reason = 'length'
    elif mutation == 'duplicate_stop':
        trailer.choices[0].finish_reason = 'stop'
    with pytest.raises(IncompleteStream):
        consume(frames)


def test_usage_trailer_does_not_hide_a_later_transport_failure():
    def broken():
        yield frame(content='answer')
        yield frame(finish='stop')
        yield frame(usage=USAGE)
        raise ConnectionError('synthetic transport failure')

    with pytest.raises(ConnectionError):
        consume(broken())
