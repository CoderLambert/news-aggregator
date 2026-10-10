"""Bound simultaneous AI event-stream request threads per application process."""

import threading

from django.http import JsonResponse


_MAX_SSE_REQUESTS = 2
_SSE_ROUTES = {
    'news-chat': {'POST'},
    'news-translate': {'POST'},
    'research-create': {'POST'},
    'research-chat': {'POST'},
    'research-stream': {'GET'},
}
_sse_lock = threading.Lock()
_active_sse_requests = 0


def _capacity_response():
    response = JsonResponse(
        {'error': '流式连接容量已满，请稍后重试。', 'error_code': 'sse_capacity_reached'},
        status=503,
    )
    response['Retry-After'] = '1'
    response['Cache-Control'] = 'no-store'
    return response


class SSEResourceMiddleware:
    """Acquire before view dispatch; release on every response/close path."""

    def __init__(self, get_response):
        self.get_response = get_response

    def process_view(self, request, view_func, view_args, view_kwargs):
        global _active_sse_requests
        match = getattr(request, 'resolver_match', None)
        allowed_methods = _SSE_ROUTES.get(match.url_name if match else None)
        if not allowed_methods or request.method not in allowed_methods:
            return None
        with _sse_lock:
            if _active_sse_requests >= _MAX_SSE_REQUESTS:
                return _capacity_response()
            _active_sse_requests += 1
        released = False
        release_lock = threading.Lock()

        def release():
            nonlocal released
            global _active_sse_requests
            with release_lock:
                if released:
                    return
                released = True
            with _sse_lock:
                _active_sse_requests -= 1

        request._sse_resource_release = release
        return None

    def __call__(self, request):
        try:
            response = self.get_response(request)
        except Exception:
            release = getattr(request, '_sse_resource_release', None)
            if release:
                release()
            raise

        release = getattr(request, '_sse_resource_release', None)
        if release is None:
            return response
        if not response.streaming or 'text/event-stream' not in response.get('Content-Type', '').lower():
            release()
            return response

        source = response.streaming_content

        def release_when_consumed():
            try:
                yield from source
            finally:
                release()

        response.streaming_content = release_when_consumed()
        # Django/Waitress closes response objects even if their body was never iterated.
        response._resource_closers.append(release)
        return response
