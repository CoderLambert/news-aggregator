"""F01: long translation SSE records must stay within the shared reader cap."""
import json

from api.translation_sse import translation_sse_records

WIRE_LIMIT = 32 * 1024


def decode_translation_records(records):
    parts = []
    values = []
    for record in records:
        for line in record.splitlines():
            assert len(line.encode('utf-8')) < WIRE_LIMIT
        data = next(line[6:] for line in record.splitlines() if line.startswith('data: '))
        event = json.loads(data)
        if '__translation_sse_fragment_v1' in event:
            assert event['index'] == len(parts)
            parts.append(event['__translation_sse_fragment_v1'])
            if event['last']:
                values.append(json.loads(''.join(parts)))
                parts.clear()
        else:
            assert not parts
            values.append(event)
    assert not parts
    return values


def test_short_translation_result_preserves_existing_wire_protocol():
    payload = {'full_content_zh': '短译文', 'full_content_zh_fetched_at': None}
    frames = list(translation_sse_records(payload, event='complete'))
    assert len(frames) == 1
    assert frames[0].startswith('event: complete\ndata: ')
    assert '\"full_content_zh\": \"短译文\"' in frames[0]
    assert decode_translation_records(frames) == [payload]


def test_large_unicode_translation_result_has_bounded_frames_and_no_data_loss():
    payload = {
        'full_content_zh': ('多语言🙂🌏"\\\n内容' * 9500),
        'full_content_zh_fetched_at': '2026-10-10T00:00:00Z',
        'full_content_zh_scope': 'shared',
    }
    assert len(json.dumps(payload, ensure_ascii=False).encode('utf-8')) > WIRE_LIMIT
    frames = list(translation_sse_records(payload, event='complete'))
    assert len(frames) > 1
    assert decode_translation_records(frames) == [payload]


def test_large_initial_progress_and_incremental_delta_keep_original_values():
    initial = {'progress': '译文🙂' * 9500}
    delta = {'progress_delta': ('新进度\r\n' * 9000)}
    assert decode_translation_records(translation_sse_records(initial)) == [initial]
    assert decode_translation_records(translation_sse_records(delta)) == [delta]
