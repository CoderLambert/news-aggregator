"""Owner-only T05 admission and read-only durable progress replay."""
import json
import time

from django.http import Http404, StreamingHttpResponse
from rest_framework.response import Response

from api.ai_connection_views import ConnectionView, error
from api.models import News
from api.services.ai_credentials import CredentialUnavailable
from api.services.ai_task_preferences import ModelSelectionError
from api.services.stored_readers import StoredContentChanged
from api.services import ai_private_translation as translation


class TranslationView(ConnectionView):
    allow_history_reads = True

    def handle_exception(self, exc):
        if isinstance(exc, translation.TranslationError):
            return error(exc.code, exc.status)
        if isinstance(exc, (ModelSelectionError, CredentialUnavailable, StoredContentChanged)):
            return error('execution_changed', 409)
        if isinstance(exc, (News.DoesNotExist, Http404)):
            return error('not_found', 404)
        return super().handle_exception(exc)


class PrivateTranslationStartView(TranslationView):
    def get(self, request, news_id):
        task = translation.latest_task(request.user, news_id)
        return Response({'task': translation.payload(task) if task else None})

    def post(self, request, news_id):
        body = request.data
        if (not isinstance(body, dict) or set(body) != {'model_config_id', 'billing_consent', 'target_language'}
                or body.get('target_language') != 'zh'):
            return error('invalid_request')
        task, created = translation.start_translation(
            request.user, news_id, model_config_id=body.get('model_config_id'),
            request_id=request.headers.get('Idempotency-Key'),
            billing_consent=body.get('billing_consent'),
        )
        return Response(translation.payload(task), status=202 if created else 200)


class PrivateTranslationTaskView(TranslationView):
    def get(self, request, task_id):
        task = translation.get_task(request.user, task_id)
        if task is None:
            return error('not_found', 404)
        return Response(translation.payload(task))


class PrivateTranslationCancelView(TranslationView):
    def post(self, request, task_id):
        body = request.data
        if not isinstance(body, dict) or set(body) != {'generation'} or type(body.get('generation')) is not int:
            return error('invalid_request')
        task = translation.cancel_translation(
            request.user, task_id, generation=body['generation'],
        )
        # A cancellation receipt confirms only lifecycle state. Never echo
        # progress or a private result from this write endpoint.
        return Response({
            'task_id': str(task.pk), 'status': task.status,
            'error_code': task.error_code,
        })


class PrivateTranslationRetryView(TranslationView):
    def post(self, request, task_id):
        body = request.data
        if (not isinstance(body, dict)
                or set(body) != {'model_config_id', 'billing_consent', 'target_language'}
                or body.get('target_language') != 'zh'):
            return error('invalid_request')
        task, created = translation.retry_translation(
            request.user, task_id, model_config_id=body.get('model_config_id'),
            request_id=request.headers.get('Idempotency-Key'),
            billing_consent=body.get('billing_consent'),
        )
        return Response(translation.payload(task), status=202 if created else 200)


class PrivateTranslationEventsView(TranslationView):
    def get(self, request, task_id):
        task = translation.get_task(request.user, task_id)
        if task is None:
            return error('not_found', 404)

        def events():
            previous = None
            # Bounded observation only. Reconnect/GET cannot schedule a task.
            for _ in range(120):
                try:
                    current = translation.get_task(request.user, task_id)
                    if current is None:
                        raise Http404
                    data = translation.payload(current)
                except Exception:
                    yield 'data: ' + json.dumps({'error_code': 'execution_changed'}) + '\n\n'
                    return
                wire = json.dumps(data, ensure_ascii=False)
                if wire != previous:
                    yield 'data: ' + wire + '\n\n'
                    previous = wire
                if data['status'] not in {'queued', 'running'}:
                    return
                time.sleep(0.5)
            # EOF is only end of this observation window, not task success.
        response = StreamingHttpResponse(events(), content_type='text/event-stream')
        response['Cache-Control'] = 'private, no-store'
        response['X-Accel-Buffering'] = 'no'
        return response
