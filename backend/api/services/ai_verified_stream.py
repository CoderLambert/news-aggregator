"""Bounded frame validation for the exact native-stop guarded Proxy route.

Clean iterator EOF after a verified stop is required. This layer never invents
completion from EOF or a synthetic DONE frame and owns no business cancellation.
"""


class IncompleteStream(RuntimeError):
    pass


def verified_text_deltas(stream, *, check, max_chars):
    pieces = []
    total = 0
    saw_stop = False
    usage_seen = False
    for frame in stream:
        check()
        choices = getattr(frame, 'choices', None)
        if not isinstance(choices, (list, tuple)):
            raise IncompleteStream('incomplete_response')
        if not choices:
            if getattr(frame, 'usage', None) is None or usage_seen:
                raise IncompleteStream('incomplete_response')
            usage_seen = True
            continue
        if len(choices) != 1:
            raise IncompleteStream('incomplete_response')
        choice = choices[0]
        reason = getattr(choice, 'finish_reason', None)
        if reason not in (None, 'stop'):
            raise IncompleteStream('incomplete_response')
        delta = getattr(choice, 'delta', None)
        if any(getattr(delta, name, None) for name in ('tool_calls', 'function_call', 'refusal')):
            raise IncompleteStream('incomplete_response')
        content = getattr(delta, 'content', None)
        if content is not None:
            if saw_stop or not isinstance(content, str):
                raise IncompleteStream('incomplete_response')
            total += len(content)
            if total > max_chars:
                raise IncompleteStream('incomplete_response')
            pieces.append(content)
            yield content
        if reason == 'stop':
            if saw_stop:
                raise IncompleteStream('incomplete_response')
            saw_stop = True
        elif saw_stop:
            raise IncompleteStream('incomplete_response')
    if not saw_stop or not ''.join(pieces).strip():
        raise IncompleteStream('incomplete_response')
