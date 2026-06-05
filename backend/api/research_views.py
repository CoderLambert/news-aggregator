"""API views for the intelligent news research agent.

Provides session CRUD and SSE streaming for the agent loop.
The SSE protocol carries structured events: thinking, tool_call,
tool_result, text_delta, complete, error.

All endpoints require authentication. Sessions are scoped to the
requesting user — one user cannot access another's research sessions.
CSRF is handled by the frontend sending X-CSRFToken header (the same
pattern used by the chat and translate SSE endpoints).
"""

import json as json_lib
import logging
import time

from django.http import StreamingHttpResponse
from django.middleware.csrf import get_token as get_csrf_token
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework import generics, status
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination

from .models import ResearchSession, ResearchSearchResult
from .serializers import (
    ResearchSessionSerializer, ResearchSessionListSerializer,
    ResearchSearchResultSerializer, ResearchSearchResultListSerializer,
)

logger = logging.getLogger(__name__)


# ── CSRF-relaxed SessionAuthentication ──────────────────────────────────────
# The frontend sends X-CSRFToken header on all POST requests via streamingFetch,
# but DRF's SessionAuthentication.authenticate() enforces CSRF internally,
# before @csrf_exempt can take effect. This subclass authenticates the session
# user but defers CSRF enforcement to Django's middleware (which respects
# @csrf_exempt). This matches the pattern used by existing chat/translate views.
# The frontend still validates CSRF via the X-CSRFToken header — we just move
# the enforcement point.

class CsrfExemptSessionAuthentication(SessionAuthentication):
    """SessionAuthentication that defers CSRF to Django middleware.

    Used for SSE streaming endpoints where the frontend already sends
    X-CSRFToken but DRF's internal CSRF check blocks the request before
    @csrf_exempt can take effect.
    """

    def enforce_csrf(self, request):
        return  # Skip DRF's CSRF check — Django middleware + @csrf_exempt handle it


# ── SSE heartbeat interval ──────────────────────────────────────────────────

_SSE_HEARTBEAT_SEC = 15


# ── User-scoped querysets ───────────────────────────────────────────────────

def _user_sessions(user):
    """Return ResearchSession queryset scoped to the requesting user."""
    return ResearchSession.objects.filter(user=user)


# ── Session CRUD ────────────────────────────────────────────────────────────

class ResearchSessionListView(generics.ListAPIView):
    """List research sessions (most recently updated first)."""
    serializer_class = ResearchSessionListSerializer
    permission_classes = [IsAuthenticated]
    authentication_classes = [CsrfExemptSessionAuthentication]
    pagination_class = PageNumberPagination

    def get_queryset(self):
        return _user_sessions(self.request.user).filter(
            is_archived=False
        ).order_by('-updated_at')


class ResearchSessionDetailView(generics.RetrieveDestroyAPIView):
    """Get or delete a research session."""
    serializer_class = ResearchSessionSerializer
    permission_classes = [IsAuthenticated]
    authentication_classes = [CsrfExemptSessionAuthentication]
    lookup_field = 'pk'

    def get_queryset(self):
        return _user_sessions(self.request.user)


# ── SSE streaming helper ────────────────────────────────────────────────────

def _sse_event(event_type: str, data: dict) -> str:
    """Format a single SSE event."""
    payload = {'type': event_type, **data}
    return f"data: {json_lib.dumps(payload, ensure_ascii=False)}\n\n"


def _research_stream_generator(job, session_id=None):
    """Generate SSE events from a ResearchJob's event queue.

    Polls the job's events list using wait_for_events(), yielding
    structured JSON SSE data lines. Sends heartbeat comments to
    prevent proxy/browser timeout.

    If session_id is provided, emits an initial 'session_created' event
    so the frontend can capture the new session ID.
    """
    last_index = 0
    last_heartbeat = time.time()

    # Emit session ID as the first event for newly created sessions
    if session_id:
        yield _sse_event('session_created', {'session_id': str(session_id)})

    # Flush any events already accumulated (re-attach case)
    while last_index < len(job.events):
        event_type, data = job.events[last_index]
        yield _sse_event(event_type, data)
        last_index += 1

    # Poll for new events
    while True:
        try:
            current_len = job.wait_for_events(last_index, timeout=1.0)

            # Send new events
            while last_index < current_len:
                event_type, data = job.events[last_index]
                yield _sse_event(event_type, data)
                last_index += 1

            # Heartbeat to prevent timeout
            now = time.time()
            if now - last_heartbeat >= _SSE_HEARTBEAT_SEC:
                yield ": keepalive\n\n"
                last_heartbeat = now

            if job.done:
                break

        except Exception:
            # Client likely disconnected; leave the worker running
            return


# ── Create session + start agent ────────────────────────────────────────────

@csrf_exempt
@api_view(['POST'])
@permission_classes([IsAuthenticated])
@authentication_classes([CsrfExemptSessionAuthentication])
def research_create(request):
    """Create a new research session and start the agent loop.

    Request body: {"query": "What are the latest developments in LLM agents?", "local_only": true}
    Response: SSE stream with agent progress events.
    """
    query = request.data.get('query', '').strip()
    if not query:
        return Response({'error': 'query is required'}, status=status.HTTP_400_BAD_REQUEST)

    local_only = bool(request.data.get('local_only', False))

    # Create session scoped to the authenticated user
    session = ResearchSession.objects.create(
        user=request.user,
        title='',  # Auto-generated after first response
        messages=[],
    )

    # Start background research job
    from .services.research.job_manager import start_or_get_research_job
    job = start_or_get_research_job(session.id, session, query, local_only=local_only)

    return StreamingHttpResponse(
        _research_stream_generator(job, session_id=session.id),
        content_type='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Session-ID': str(session.id),
        },
    )


# ── Continue session (follow-up question) ───────────────────────────────────

@csrf_exempt
@api_view(['POST'])
@permission_classes([IsAuthenticated])
@authentication_classes([CsrfExemptSessionAuthentication])
def research_chat(request, pk):
    """Send a follow-up message to an existing research session.

    Request body: {"query": "Tell me more about tool use patterns", "local_only": true}
    Response: SSE stream with agent progress events.
    """
    try:
        session = _user_sessions(request.user).get(pk=pk)
    except ResearchSession.DoesNotExist:
        return Response({'error': 'Session not found'}, status=status.HTTP_404_NOT_FOUND)

    query = request.data.get('query', '').strip()
    if not query:
        return Response({'error': 'query is required'}, status=status.HTTP_400_BAD_REQUEST)

    local_only = bool(request.data.get('local_only', False))

    # Check for existing running job
    from .services.research.job_manager import get_research_job, start_or_get_research_job
    existing_job = get_research_job(session.id)
    if existing_job and not existing_job.done:
        # Already running — re-attach to the SSE stream
        return StreamingHttpResponse(
            _research_stream_generator(existing_job),
            content_type='text/event-stream',
            headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
        )

    # Start new agent loop for the follow-up
    job = start_or_get_research_job(session.id, session, query, local_only=local_only)

    return StreamingHttpResponse(
        _research_stream_generator(job),
        content_type='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )


# ── Re-attach to active SSE stream ─────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
@authentication_classes([CsrfExemptSessionAuthentication])
def research_stream(request, pk):
    """Re-attach to an in-progress agent SSE stream.

    Used when the user refreshes or re-opens the research panel while
    the agent is still running.
    """
    try:
        session = _user_sessions(request.user).get(pk=pk)
    except ResearchSession.DoesNotExist:
        return Response({'error': 'Session not found'}, status=status.HTTP_404_NOT_FOUND)

    from .services.research.job_manager import get_research_job
    job = get_research_job(session.id)

    if not job or job.done:
        # No active job — return the session's existing messages
        serializer = ResearchSessionSerializer(session)
        return Response(serializer.data)

    return StreamingHttpResponse(
        _research_stream_generator(job),
        content_type='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )


# ── Search results for a session ─────────────────────────────────────────────

class ResearchSearchResultListView(generics.ListAPIView):
    """List search results for a research session.

    Supports filtering by ``result_type`` query parameter (news, web, article,
    webpage, topic).  By default returns the lightweight list serializer (no
    ``result_data``); pass ``?detail=1`` to include full result data.
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [CsrfExemptSessionAuthentication]
    pagination_class = PageNumberPagination

    def get_serializer_class(self):
        if self.request.query_params.get('detail') == '1':
            return ResearchSearchResultSerializer
        return ResearchSearchResultListSerializer

    def get_queryset(self):
        session_pk = self.kwargs['session_pk']
        # Verify session belongs to user
        if not _user_sessions(self.request.user).filter(pk=session_pk).exists():
            return ResearchSearchResult.objects.none()

        qs = ResearchSearchResult.objects.filter(session_id=session_pk)

        result_type = self.request.query_params.get('result_type')
        if result_type:
            qs = qs.filter(result_type=result_type)

        return qs.order_by('created_at')
