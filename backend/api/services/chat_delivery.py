"""Bounded chat delivery with an explicit completion result and durable status."""
import json
import logging

logger = logging.getLogger(__name__)
MAX_CHAT_RESPONSE_CHARS = 128000
MARKER = '__META__'


def frame(value):
    return '\u200b' + MARKER + json.dumps(value, ensure_ascii=False) + MARKER + '\n\n'


def prompt_history(messages):
    """Do not teach a model from interrupted/error or unverifiable old answers."""
    clean = []
    for message in messages[-20:]:
        if not isinstance(message, dict) or not isinstance(message.get('content'), str):
            continue
        role = message.get('role')
        if role == 'user' or (role == 'assistant' and message.get('status') == 'complete'):
            clean.append({'role': role, 'content': message['content']})
    return clean


def deliver_chat(chunks_factory, persist, *, context_scope, content_state, web_sources):
    """Publish terminal completion only AFTER the owner/generation CAS succeeds.

    Closing a streaming response persists any partial content as interrupted.
    Provider failure never fabricates a completed assistant answer, and a
    model cannot forge the reserved transport marker inside its own text.
    """
    pieces, tail = [], ''
    total = 0
    status = 'interrupted'
    chunks = None
    saved = False
    try:
        yield frame({'type': 'article_context', 'context_scope': context_scope,
                     'full_content_state': content_state, 'delivery_contract': 2})
        if web_sources:
            yield frame({'type': 'web_search', 'sources': web_sources})
        chunks = chunks_factory()
        for chunk in chunks:
            if not isinstance(chunk, str):
                raise ValueError('invalid_chat_chunk')
            total += len(chunk)
            if total > MAX_CHAT_RESPONSE_CHARS:
                raise ValueError('chat_output_limit')
            tail = (tail + chunk).replace(MARKER, '__META\u200b__')
            safe = tail[:-len(MARKER) + 1]
            tail = tail[-len(MARKER) + 1:]
            if safe:
                pieces.append(safe)
                yield safe
        if not (''.join(pieces) + tail).strip():
            raise ValueError('empty_chat_response')
        status = 'complete'
    except GeneratorExit:
        raise
    except Exception as exc:
        status = 'failed'
        logger.warning('Chat delivery failed (%s)', type(exc).__name__)
    finally:
        if chunks is not None and hasattr(chunks, 'close'):
            try:
                chunks.close()
            except Exception:
                logger.warning('Chat provider cleanup failed')
        # Never yield in finally: the browser may already have closed the stream.
        try:
            persist(''.join(pieces) + tail, status)
            saved = True
        except Exception as exc:
            status = 'interrupted'
            logger.warning('Chat state was not committed (%s)', type(exc).__name__)
    if tail:
        yield tail
    yield frame({'type': 'chat_status', 'status': status,
                 'saved': saved, 'context_scope': context_scope})
