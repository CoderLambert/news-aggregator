"""Owner-private research sessions, durable runs and replayable SSE routes."""

import time

from django.db import transaction
from django.http import StreamingHttpResponse
from rest_framework import generics, status
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination

from .models import ResearchSession, ResearchSearchResult, ResearchRun
from .serializers import (
    ResearchSessionSerializer, ResearchSessionListSerializer,
    ResearchSearchResultSerializer, ResearchSearchResultListSerializer,
)
from .services.research import job_manager

_SSE_HEARTBEAT_SEC = 15


def _user_sessions(user):
    return ResearchSession.objects.filter(user=user)


def _no_store(response):
    response['Cache-Control'] = 'no-store'
    return response


class ResearchNoStoreMixin:
    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        return _no_store(response)


class ResearchSessionListView(ResearchNoStoreMixin, generics.ListAPIView):
    serializer_class = ResearchSessionListSerializer
    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]
    pagination_class = PageNumberPagination

    def get_queryset(self):
        return _user_sessions(self.request.user).filter(is_archived=False).order_by('-updated_at')


class ResearchSessionDetailView(ResearchNoStoreMixin, generics.RetrieveDestroyAPIView):
    serializer_class = ResearchSessionSerializer
    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]
    lookup_field = 'pk'

    def get_queryset(self):
        return _user_sessions(self.request.user)

    def perform_destroy(self, instance):
        with transaction.atomic():
            # Fence workers before the existing session cascade removes run/events.
            job_manager.fence_session_runs(instance.user_id, instance.pk)
            super().perform_destroy(instance)


def _sse_stream(run_id):
    last_sequence = 0
    last_heartbeat = time.monotonic()
    while True:
        events = list(job_manager.get_run_events(run_id, after_sequence=last_sequence, limit=100))
        for event in events:
            yield job_manager.serialize_event(event.event_type, event.data)
            last_sequence = event.sequence
        state = ResearchRun.objects.filter(pk=run_id).values(
            'status', 'last_event_sequence',
        ).first()
        if state is None:
            return
        if state['status'] not in {'queued', 'running'} and last_sequence >= state['last_event_sequence']:
            return
        now = time.monotonic()
        if now - last_heartbeat >= _SSE_HEARTBEAT_SEC:
            yield ': keepalive\n\n'
            last_heartbeat = now
        job_manager.wait_for_run_change(run_id, 1.0)


def _stream_response(run, session_id=None):
    headers = {
        'Cache-Control': 'no-store',
        'X-Accel-Buffering': 'no',
        'Run-ID': str(run.pk),
        'Run-Status': run.status,
    }
    if session_id is not None:
        headers['Session-ID'] = str(session_id)
    return _no_store(StreamingHttpResponse(
        _sse_stream(run.pk), content_type='text/event-stream', headers=headers,
    ))


def _run_error_response(exc):
    response = Response(
        {'error': exc.message, 'error_code': exc.error_code},
        status=exc.status_code,
    )
    if exc.error_code == 'research_capacity_reached':
        response['Retry-After'] = '1'
    return _no_store(response)


def _request_data(request):
    query = request.data.get('query', '')
    if not isinstance(query, str) or not query.strip():
        return None, None, Response({'error': 'query is required'}, status=status.HTTP_400_BAD_REQUEST)
    return query.strip(), bool(request.data.get('local_only', False)), None

def _submit_response(request, *, session_id=None):
    query, local_only, error = _request_data(request)
    if error is not None:
        return _no_store(error)
    raw_key = request.headers.get('Idempotency-Key')
    try:
        session, run = job_manager.submit_research_run(
            request.user, session_id=session_id, query=query,
            local_only=local_only, idempotency_key=raw_key,
        )
    except job_manager.ResearchRunError as exc:
        return _run_error_response(exc)
    return _stream_response(run, session_id=session.pk)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@authentication_classes([SessionAuthentication])
def research_create(request):
    """Create/attach a research session; request closure never cancels its run."""
    return _submit_response(request)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@authentication_classes([SessionAuthentication])
def research_chat(request, pk):
    """Create/attach a follow-up run in an owner-scoped session."""
    if not _user_sessions(request.user).filter(pk=pk).exists():
        return _no_store(Response({'error': 'Session not found'}, status=status.HTTP_404_NOT_FOUND))
    return _submit_response(request, session_id=pk)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@authentication_classes([SessionAuthentication])
def research_stream(request, pk):
    """Read persistent events for an active run or return the saved owner DTO."""
    session = _user_sessions(request.user).filter(pk=pk).first()
    if session is None:
        return _no_store(Response({'error': 'Session not found'}, status=status.HTTP_404_NOT_FOUND))
    run = job_manager.active_run_for_session(request.user, session)
    if run is not None:
        return _stream_response(run)
    serializer = ResearchSessionSerializer(session)
    data = dict(serializer.data)
    data['latest_run'] = job_manager.latest_run_state(request.user, session)
    response = _no_store(Response(data))
    if data['latest_run'] is not None:
        response['Run-ID'] = data['latest_run']['run_id']
    return response


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@authentication_classes([SessionAuthentication])
def research_cancel(request, pk):
    """Cancel only the exact latest run in this owner's session."""
    session = _user_sessions(request.user).filter(pk=pk).first()
    if session is None:
        return _no_store(Response({'error': 'Session not found'}, status=status.HTTP_404_NOT_FOUND))
    body = request.data if isinstance(request.data, dict) else {}
    run_id = body.get('run_id')
    if not isinstance(run_id, str):
        return _no_store(Response(
            {'error': 'run_id is required', 'error_code': 'invalid_run_id'},
            status=status.HTTP_400_BAD_REQUEST,
        ))
    try:
        run = job_manager.cancel_research_run(request.user, session, run_id)
    except job_manager.ResearchRunError as exc:
        return _run_error_response(exc)
    return _no_store(Response({
        'run_id': str(run.pk), 'status': run.status,
        'error_code': run.error_code, 'error_message': run.error_message,
    }))


class ResearchSearchResultListView(ResearchNoStoreMixin, generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]
    pagination_class = PageNumberPagination

    def get_serializer_class(self):
        if self.request.query_params.get('detail') == '1':
            return ResearchSearchResultSerializer
        return ResearchSearchResultListSerializer

    def get_queryset(self):
        session_pk = self.kwargs['session_pk']
        if not _user_sessions(self.request.user).filter(pk=session_pk).exists():
            return ResearchSearchResult.objects.none()
        queryset = ResearchSearchResult.objects.filter(session_id=session_pk)
        result_type = self.request.query_params.get('result_type')
        if result_type:
            queryset = queryset.filter(result_type=result_type)
        return queryset.order_by('created_at')
