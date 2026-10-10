"""Bounded transport for large translation SSE payloads.

The shared frontend SSE reader deliberately limits a *single wire line* to 32 KiB.
Translation results can be much larger. Keep small legacy records unchanged and
fragment oversized JSON records into bounded UTF-8 frames; callers still receive
the same logical event after the frontend reassembles the frames.
"""
import json

_MAX_SINGLE_RECORD_BYTES = 16 * 1024
_FRAGMENT_CHARS = 2048


def translation_sse_records(payload, *, event=None):
    """Yield SSE records, with each data line safely below the 32-KiB parser cap."""
    encoded = json.dumps(payload, ensure_ascii=False)
    prefix = f'event: {event}\n' if event else ''
    legacy = f'{prefix}data: {encoded}\n\n'
    if len(legacy.encode('utf-8')) <= _MAX_SINGLE_RECORD_BYTES:
        yield legacy
        return

    for index, offset in enumerate(range(0, len(encoded), _FRAGMENT_CHARS)):
        fragment = encoded[offset:offset + _FRAGMENT_CHARS]
        frame = {
            '__translation_sse_fragment_v1': fragment,
            'index': index,
            'last': offset + _FRAGMENT_CHARS >= len(encoded),
        }
        # A single Python code point requires <= 4 UTF-8 bytes; at 2048
        # characters, the fragment plus JSON envelope remains under 16 KiB.
        yield f'data: {json.dumps(frame, ensure_ascii=False, separators=(",", ":"))}\n\n'
