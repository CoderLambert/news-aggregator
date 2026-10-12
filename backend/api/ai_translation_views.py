"""Session-bound APIs for explicitly requested private BYOK translations."""

from __future__ import annotations

from django.conf import settings
from django.http import StreamingHttpResponse
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from api.authentication import AnonymousCsrfSessionAuthentication
from api.models import News
from api.public_policy import policy_error
from api.services import chatgpt_subscription as subscription
from api.services import chatgpt_subscription_jobs as translation_jobs
from api.services.ai_translation import BYOKTranslationError, TRANSLATION_ERRORS
from api.translation_sse import translation_sse_records


def _no_store(response):
    response['Cache-Control'] = 'no-store'
    return response


def _task_payload(task):
    result = task.result
    if task.ai_connection_id is not None and task.status == 'succeeded' and isinstance(result, dict):
        from api.services.shared_translations import source_hash

        result = dict(result)
        result['result_id'] = str(task.pk)
        result['current_match'] = task.source_hash == source_hash(task.news.full_content or '')
    return {
        'id': str(task.pk),
        'status': task.status,
        'generation': task.generation,
        'progress': task.progress,
        'result': result,
        'error_code': task.error_code,
        'error_message': task.error_message,
        'updated_at': task.updated_at.isoformat(),
        'finished_at': task.finished_at.isoformat() if task.finished_at else None,
    }


def _byok_error_response(exc):
    code = exc.code
    message = TRANSLATION_ERRORS.get(code, '个人模型全文翻译失败，请稍后重试。')
    if code in {'byok_disabled', 'authentication_required'}:
        code_status = status.HTTP_403_FORBIDDEN
    elif code in {'gateway_unavailable', 'provider_unavailable', 'translation_budget_unavailable'}:
        code_status = status.HTTP_503_SERVICE_UNAVAILABLE
    elif code in {'source_too_long', 'translation_budget_exceeded'}:
        code_status = status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
    elif code in {'execution_changed', 'model_reselection_required', 'model_not_configured',
                  'model_not_found', 'model_unavailable', 'model_route_unavailable',
                  'idempotency_key_reused'}:
        code_status = status.HTTP_409_CONFLICT
    else:
        code_status = status.HTTP_400_BAD_REQUEST
    return _no_store(Response({'error': message, 'error_code': code}, status=code_status))


def _require_byok_feature():
    if not settings.AI_BYOK_ENABLED:
        return policy_error('byok_disabled')
    if not settings.PUBLIC_AI_ENABLED:
        return policy_error('ai_disabled')
    return None


class PrivateTranslationStartView(APIView):
    authentication_classes = [AnonymousCsrfSessionAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, news_id):
        denied = _require_byok_feature()
        if denied:
            return denied
        if not isinstance(request.data, dict) or request.data:
            return _no_store(Response(
                {'error': '请求字段无效。', 'error_code': 'invalid_request'},
                status=status.HTTP_400_BAD_REQUEST,
            ))
        key = request.headers.get('Idempotency-Key', '')
        news = News.objects.filter(pk=news_id).first()
        if news is None:
            return _no_store(Response({'error': '新闻不存在。'}, status=status.HTTP_404_NOT_FOUND))
        try:
            job = translation_jobs.start_or_get_byok_job(request.user, news, key)
        except BYOKTranslationError as exc:
            return _byok_error_response(exc)
        except subscription.SubscriptionError as exc:
            return _no_store(Response(
                {'error': str(exc), 'error_code': exc.error_code},
                status=exc.status_code,
            ))

        def stream():
            sent_length = 0
            try:
                if job.text:
                    current = job.text
                    yield from translation_sse_records({'progress': current})
                    sent_length = len(current)
                while not job.done:
                    current_length = job.wait_for_update(sent_length, timeout=1.0)
                    if current_length > sent_length:
                        current = job.text
                        if len(current) > sent_length:
                            yield from translation_sse_records({'progress_delta': current[sent_length:]})
                            sent_length = len(current)
                if job.error:
                    yield from translation_sse_records({'error': job.error})
                    return
                if job.result is None:
                    yield from translation_sse_records({'error': '本次翻译没有保存完整结果。'})
                    return
                yield from translation_sse_records(job.result, event='complete')
            except subscription.SubscriptionError as exc:
                yield from translation_sse_records({'error': str(exc)})
            except GeneratorExit:
                # The durable worker is independent from this SSE subscriber.
                return

        response = StreamingHttpResponse(stream(), content_type='text/event-stream')
        response['Cache-Control'] = 'no-store'
        response['X-Accel-Buffering'] = 'no'
        response['Job-ID'] = str(job.id)
        return response


class PrivateTranslationTaskView(APIView):
    authentication_classes = [AnonymousCsrfSessionAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, job_id):
        denied = _require_byok_feature()
        if denied:
            return denied
        try:
            task = translation_jobs.get_task(job_id, user_id=request.user.pk)
        except subscription.SubscriptionError as exc:
            return _no_store(Response(
                {'error': str(exc), 'error_code': exc.error_code},
                status=exc.status_code,
            ))
        if task is None or task.ai_connection_id is None:
            return _no_store(Response({'error': '任务不存在。'}, status=status.HTTP_404_NOT_FOUND))
        return _no_store(Response(_task_payload(task)))


class PrivateTranslationResultView(APIView):
    """Read one saved BYOK result without consulting its current credential."""

    authentication_classes = [AnonymousCsrfSessionAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, result_id):
        from api.services.article_translations import (
            TranslationResultNotFound,
            get_byok_result_for_owner,
            result_payload,
        )

        try:
            result = get_byok_result_for_owner(request.user, str(result_id))
        except TranslationResultNotFound:
            return _no_store(Response(
                {'error': '译文结果不存在。', 'error_code': 'translation_result_not_found'},
                status=status.HTTP_404_NOT_FOUND,
            ))
        payload = result_payload(result)
        return _no_store(Response({
            'result_id': result.result_id,
            'full_content_zh': result.content,
            'full_content_zh_source': 'byok',
            'full_content_zh_scope': 'private',
            'full_content_zh_fetched_at': result.fetched_at.isoformat() if result.fetched_at else None,
            'source_hash': result.source_hash,
            'current_match': result.current_match,
            'model_source': payload['model_source'],
        }))


class PrivateTranslationCancelView(APIView):
    authentication_classes = [AnonymousCsrfSessionAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, job_id):
        denied = _require_byok_feature()
        if denied:
            return denied
        body = request.data
        generation = body.get('generation') if isinstance(body, dict) and set(body) == {'generation'} else None
        if type(generation) is not int or not 1 <= generation <= 9223372036854775807:
            return _no_store(Response(
                {'error': 'generation 必须是正整数。', 'error_code': 'invalid_generation'},
                status=status.HTTP_400_BAD_REQUEST,
            ))
        try:
            current = translation_jobs.get_task(job_id, user_id=request.user.pk)
            if current is None or current.ai_connection_id is None:
                return _no_store(Response({'error': '任务不存在。'}, status=status.HTTP_404_NOT_FOUND))
            task, _ = translation_jobs.cancel_task(
                job_id, user_id=request.user.pk, generation=generation,
            )
        except subscription.SubscriptionError as exc:
            return _no_store(Response(
                {'error': str(exc), 'error_code': exc.error_code},
                status=exc.status_code,
            ))
        if task is None or task.ai_connection_id is None:
            return _no_store(Response({'error': '任务不存在。'}, status=status.HTTP_404_NOT_FOUND))
        return _no_store(Response(_task_payload(task)))
