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
        from .services.research.access import require_session_evidence
        from django.http import Http404
        run = ResearchRun.objects.select_related('user', 'session').filter(pk=run_id).first()
        if run is None:
            return
        try:
            require_session_evidence(run.session, run.user)
        except Http404:
            yield job_manager.serialize_event('error', {'message': '研究资料的读取权限或内容已变化。'})
            return
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

def _byok_create_values(request, *, allowed):
    body = request.data
    if not hasattr(body, 'get'):
        return None, None, _no_store(Response({'error': 'invalid request'}, status=400))
    has_model = 'model_config_id' in body
    has_consent = 'consent' in body
    if not has_model and not has_consent:
        return None, None, None
    if not allowed:
        return None, None, _no_store(Response(
            {'error': 'Explicit model authorization is required for this research run.',
             'error_code': 'research_byok_create_only'}, status=400,
        ))
    model_config_id = body.get('model_config_id')
    if body.get('consent') is not True or type(model_config_id) is not str or len(model_config_id) != 36:
        return None, None, _no_store(Response(
            {'error': 'Select a verified personal research model and explicitly approve provider billing.',
             'error_code': 'research_consent_required'}, status=400,
        ))
    if set(body.keys()) - {'query', 'local_only', 'model_config_id', 'consent'}:
        return None, None, _no_store(Response(
            {'error': 'Unsupported research request fields.', 'error_code': 'invalid_research_request'},
            status=400,
        ))
    return model_config_id, True, None


def _submit_response(request, *, session_id=None, allow_byok_create=False):
    query, local_only, error = _request_data(request)
    if error is not None:
        return _no_store(error)
    model_config_id, consent, error = _byok_create_values(
        request, allowed=allow_byok_create,
    )
    if error is not None:
        return error
    raw_key = request.headers.get('Idempotency-Key')
    try:
        session, run = job_manager.submit_research_run(
            request.user, session_id=session_id, query=query,
            local_only=local_only, idempotency_key=raw_key,
            model_config_id=model_config_id, consent=consent,
        )
    except job_manager.ResearchRunError as exc:
        return _run_error_response(exc)
    return _stream_response(run, session_id=session.pk)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@authentication_classes([SessionAuthentication])
def research_create(request):
    """Create a new first-run session; request closure never cancels its run."""
    return _submit_response(request, allow_byok_create=True)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@authentication_classes([SessionAuthentication])
def research_chat(request, pk):
    """Create/attach a follow-up run in an owner-scoped session."""
    if not _user_sessions(request.user).filter(pk=pk).exists():
        return _no_store(Response({'error': 'Session not found'}, status=status.HTTP_404_NOT_FOUND))
    return _submit_response(request, session_id=pk, allow_byok_create=True)


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
    serializer = ResearchSessionSerializer(session, context={"request": request})
    data = dict(serializer.data)
    data['latest_run'] = job_manager.latest_run_state(request.user, session)
    response = _no_store(Response(data))
    if data['latest_run'] is not None:
        response['Run-ID'] = data['latest_run']['run_id']
    return response


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@authentication_classes([SessionAuthentication])
def research_resume_queued(request, pk):
    """Owner-verified, CSRF-protected dispatch of a never-started durable run."""
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
        run = job_manager.resume_queued_run(request.user, session, run_id)
    except job_manager.ResearchRunError as exc:
        return _run_error_response(exc)
    return _no_store(Response({'run_id': str(run.pk), 'status': run.status}))



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
        from .services.research.access import require_session_evidence
        require_session_evidence(_user_sessions(self.request.user).get(pk=session_pk), self.request.user)
        queryset = ResearchSearchResult.objects.filter(session_id=session_pk)
        result_type = self.request.query_params.get('result_type')
        if result_type:
            queryset = queryset.filter(result_type=result_type)
        return queryset.order_by('created_at')
