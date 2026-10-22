"""Owner-only T05 admission and read-only durable progress replay."""
import json
import time

from django.http import Http404, StreamingHttpResponse
from rest_framework.response import Response
from rest_framework.renderers import JSONRenderer

from api.ai_connection_views import ConnectionView, error
from api.models import News
from api.services.ai_credentials import CredentialUnavailable
from api.services.ai_task_preferences import ModelSelectionError
from api.services.stored_readers import StoredContentChanged
from api.services import ai_private_translation as translation
from api.services import translation_channel as transport


class TranslationView(ConnectionView):
    allow_history_reads = True

    def handle_exception(self, exc):
        if isinstance(exc, transport.ChannelUnavailable):
            return error('translation_channel_unavailable', 503)
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


class EventStreamRenderer(JSONRenderer):
    # DRF negotiates Accept before get(), including for StreamingHttpResponse.
    media_type = 'text/event-stream'
    format = 'eventstream'


class PrivateTranslationEventsView(TranslationView):
    renderer_classes = [JSONRenderer, EventStreamRenderer]

    def get(self, request, task_id):
        task = translation.get_task(request.user, task_id)
        if task is None:
            return error('not_found', 404)

        cursor = request.headers.get('Last-Event-ID') or request.query_params.get('cursor', '')
        if cursor and not transport.CURSOR.fullmatch(cursor):
            return error('invalid_request', 400)
        initial = translation.payload(task)
        identity = {key: initial[key] for key in ('task_id', 'news_id', 'generation')}

        def frame(kind, data, event_id=''):
            return (('id: ' + event_id + '\n') if event_id else '') + 'event: ' + kind + '\ndata: ' + json.dumps(data, ensure_ascii=False) + '\n\n'

        def events():
            current_cursor = cursor
            # The initial authorization above is the only DB access phase.
            # Control freshness/stop fences are checked atomically on every replay.
            if initial['status'] not in {'queued', 'running'}:
                yield frame('terminal', {**identity, 'task': initial}, cursor)
                return
            if initial['status'] == 'queued':
                yield frame('snapshot', {**identity, 'task': initial})
            try:
                channel = transport.Channel(task.user_id, task.pk, task.generation)
                deadline = time.monotonic() + 120
                while time.monotonic() < deadline:
                    try:
                        state = channel.read(current_cursor)
                    except transport.ChannelUnavailable:
                        # A queued task has no publisher yet. Wait on Redis only;
                        # the next HTTP observation rechecks durable authorization.
                        if initial['status'] != 'queued' or current_cursor:
                            raise
                        channel.wait('0-0')
                        yield ': keepalive\n\n'
                        continue
                    if state['snapshot']:
                        current_cursor = state['cursor']
                        data = {**initial, 'progress': state['text'], 'status': state['status'],
                                'result': json.loads(state['result']), 'error_code': state['error_code']}
                        kind = 'snapshot' if state['status'] == 'running' else 'terminal'
                        yield frame(kind, {**identity, 'task': data}, current_cursor)
                        if kind == 'terminal':
                            return
                    else:
                        for event_id, fields in state['events']:
                            fields = dict(zip(fields[::2], fields[1::2]))
                            body = json.loads(fields['body'])
                            kind = fields['kind']
                            if kind == 'terminal':
                                body = {'task': {**initial, **body, 'progress': ''}}
                            elif kind == 'snapshot':
                                body = {'task': {**initial, 'status': 'running', 'progress': body.get('text', '')}}
                            yield frame(kind, {**body, **identity}, event_id)
                            current_cursor = event_id
                            if kind == 'terminal':
                                return
                        if state['status'] != 'running' and not state['events']:
                            # A reconnect at the terminal cursor still gets a terminal.
                            current_cursor = ''
                            continue
                    channel.wait(current_cursor)
                    yield ': keepalive\n\n'
            except transport.ChannelUnavailable:
                yield frame('unavailable', {**identity, 'error_code': 'translation_channel_unavailable'})
            # EOF is not task completion. Observation never dispatches work.
        response = StreamingHttpResponse(events(), content_type='text/event-stream')
        response['Cache-Control'] = 'private, no-store'
        response['X-Accel-Buffering'] = 'no'
        return response
