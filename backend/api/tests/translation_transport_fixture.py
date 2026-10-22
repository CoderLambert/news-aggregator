"""Explicit synthetic Redis only; never use the application's Redis configuration."""
import os
from pathlib import Path


def synthetic_redis_client():
    from api.services import translation_channel as transport
    socket = os.environ.get('TEST_TRANSLATION_REDIS_SOCKET')
    if socket:
        if not Path(socket).is_absolute():
            raise ValueError('synthetic Redis socket must be absolute')
        from redis import Redis
        from redis.retry import Retry
        from redis.backoff import NoBackoff
        return Redis(unix_socket_path=socket, password='synthetic-translation-only',
                     protocol=2, decode_responses=True, socket_timeout=1.5,
                     retry=Retry(NoBackoff(), 0))
    url = os.environ.get('TEST_TRANSLATION_REDIS_URL')
    return transport._client(url) if url else None
