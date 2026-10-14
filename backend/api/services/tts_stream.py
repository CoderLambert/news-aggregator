"""Closable audio iterator: no accumulated audio list and no half-written cache."""
import asyncio
import logging
import time
from django.http import StreamingHttpResponse
from api.services.tts_cache import AudioLimit, SYNTHESIS_TIMEOUT

logger = logging.getLogger(__name__)


class BoundedAudioStream:
    def __init__(self, communicate, writer):
        self.writer = writer
        self.loop = asyncio.new_event_loop()
        self.deadline = time.monotonic() + SYNTHESIS_TIMEOUT
        self.closed = False
        self.started = False
        self.pending = None
        self.generator = self._audio(communicate)

    async def _audio(self, communicate):
        async for chunk in communicate.stream():
            if chunk.get('type') == 'audio' and 'data' in chunk:
                if not isinstance(chunk['data'], bytes):
                    raise AudioLimit('invalid_audio_payload')
                if chunk['data']:
                    yield chunk['data']

    def _next_audio(self):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('tts_deadline')
        return self.loop.run_until_complete(asyncio.wait_for(self.generator.__anext__(), min(20, remaining)))

    def prepare(self):
        # A handshake failure is a 503 JSON response before the audio response
        # is constructed. The same deadline also applies to all later chunks.
        self.pending = self._next_audio()
        self.writer.append(self.pending)
        return self

    def __iter__(self):
        return self

    def __next__(self):
        if self.closed:
            raise StopIteration
        if self.pending is not None:
            chunk, self.pending = self.pending, None
            return chunk
        try:
            chunk = self._next_audio()
            self.writer.append(chunk)
            return chunk
        except StopAsyncIteration:
            try:
                self.writer.publish()
            finally:
                self.close()
            raise StopIteration from None
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            self.loop.run_until_complete(self.generator.aclose())
        except Exception:
            logger.warning('TTS transport cleanup failed')
        finally:
            self.loop.close()
            self.writer.close()


def audio_response(stream):
    # Django registers the iterable's close() even if it was never advanced by
    # the WSGI server, so cancellation before first yielded audio releases locks.
    response = StreamingHttpResponse(stream, content_type='audio/mpeg')
    response['Cache-Control'] = 'private, max-age=86400'
    return response
