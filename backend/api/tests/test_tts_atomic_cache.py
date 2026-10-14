import pytest
from api.services.tts_cache import AtomicAudioWriter, AudioBusy, AudioLimit
from api.services.tts_stream import BoundedAudioStream, audio_response
from api.services import tts_cache


def test_cache_is_published_atomically_without_partial_visibility(tmp_path):
    path = tmp_path / 'key.mp3'; path.write_bytes(b'old audio')
    with AtomicAudioWriter(tmp_path, 'key') as writer:
        writer.append(b'new complete audio')
        assert path.read_bytes() == b'old audio'
        with pytest.raises(AudioBusy):
            AtomicAudioWriter(tmp_path, 'key')
        writer.publish()
    assert path.read_bytes() == b'new complete audio'
    assert not list(tmp_path.glob('.*.partial'))


def test_failed_or_oversize_stream_retains_old_audio(tmp_path, monkeypatch):
    path = tmp_path / 'key.mp3'; path.write_bytes(b'old')
    monkeypatch.setattr(tts_cache, 'MAX_AUDIO_BYTES', 4)
    with AtomicAudioWriter(tmp_path, 'key') as writer:
        writer.append(b'1234')
        with pytest.raises(AudioLimit):
            writer.append(b'5')
    assert path.read_bytes() == b'old'
    assert not list(tmp_path.glob('.*.partial'))


def test_global_synthesis_slots_are_shared_and_released(tmp_path):
    first = AtomicAudioWriter(tmp_path, 'one'); second = AtomicAudioWriter(tmp_path, 'two')
    with pytest.raises(AudioBusy):
        AtomicAudioWriter(tmp_path, 'three')
    first.close()
    third = AtomicAudioWriter(tmp_path, 'three')
    second.close(); third.close()


def test_response_close_before_audio_iteration_releases_resources(tmp_path):
    class Fake:
        async def stream(self):
            yield {'type': 'audio', 'data': b'audio'}
            yield {'type': 'audio', 'data': b'more'}
    writer = AtomicAudioWriter(tmp_path, 'key')
    stream = BoundedAudioStream(Fake(), writer).prepare()
    response = audio_response(stream)
    response.close()
    assert stream.closed and writer.closed
    assert not (tmp_path / 'key.mp3').exists()
    next_writer = AtomicAudioWriter(tmp_path, 'key'); next_writer.close()


def test_complete_stream_publishes_file_in_chunks(tmp_path):
    class Fake:
        async def stream(self):
            for _ in range(3):
                yield {'type': 'audio', 'data': b'a' * 256}
    writer = AtomicAudioWriter(tmp_path, 'key')
    stream = BoundedAudioStream(Fake(), writer).prepare()
    assert b''.join(stream) == b'a' * 768
    assert (tmp_path / 'key.mp3').read_bytes() == b'a' * 768
    assert writer.closed
