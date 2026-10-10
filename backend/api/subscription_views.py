"""Authenticated local ChatGPT subscription connection endpoints."""

import html
import json
from urllib.parse import urlparse

from django.http import HttpResponse, HttpResponseRedirect, StreamingHttpResponse
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from api.models import ChatGPTArticleTranslation, ChatGPTSubscriptionConnection, News
from api.services import chatgpt_subscription as subscription
from api.services import chatgpt_subscription_jobs as translation_jobs
from api.services import shared_translations


def _connection_payload(connection):
    return {
        'id': str(connection.pk),
        'account_name': connection.account_name,
        'account_email': connection.account_email,
        'selected_model': connection.selected_model,
        'active': connection.is_active,
        'connected': connection.connected,
        'needs_reauth': connection.needs_reauth,
        'updated_at': connection.updated_at.isoformat(),
    }


def _subscription_error_response(exc):
    return Response(
        {'error': str(exc), 'error_code': exc.error_code},
        status=exc.status_code,
    )


def _safe_callback_message(error_code):
    if error_code in {'subscription_disabled', 'local_oss_production_forbidden'}:
        return '此环境当前未启用 ChatGPT 订阅连接。'
    if error_code == 'hosted_integration_unapproved':
        return '托管订阅连接尚未获得所需批准。'
    if error_code in {'session_mismatch', 'inactive_user'}:
        return '本地登录状态已切换，请回到原页面重新开始连接。'
    return '授权没有完成，请回到原页面重新开始连接。'


class ChatGPTSubscriptionStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            subscription._require_network_mode()
        except subscription.SubscriptionError as exc:
            return _subscription_error_response(exc)
        connections = ChatGPTSubscriptionConnection.objects.filter(user=request.user)
        active = connections.filter(is_active=True).first()
        return Response({
            'connections': [_connection_payload(item) for item in connections],
            'active_connection_id': str(active.pk) if active else None,
        })


class ChatGPTSubscriptionConnectView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            subscription._require_network_mode()
            connection_id = request.data.get('connection_id')
            target = subscription.get_user_connection(request.user, connection_id) if connection_id else None
            if not request.session.session_key:
                request.session.create()
            request.session['chatgpt_oauth_session'] = True
            attempt = subscription.create_authorization_attempt(
                request.user, target, session_key=request.session.session_key or '',
                origin=request.META.get('HTTP_ORIGIN', ''),
            )
        except subscription.SubscriptionError as exc:
            return _subscription_error_response(exc)
        return Response(attempt, status=status.HTTP_201_CREATED)


class ChatGPTSubscriptionHandoffView(APIView):
    """Set a callback-host-only HttpOnly cookie using a one-time form ticket."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        try:
            cookie_value, authorization_url = subscription.handoff_authorization(
                request.data.get('attempt_id', ''), request.data.get('handoff_token', ''),
                session_key=request.session.session_key or '',
                origin=request.META.get('HTTP_ORIGIN', ''),
            )
        except subscription.SubscriptionError as exc:
            return HttpResponse(
                '<!doctype html><meta charset="utf-8"><title>连接失败</title>'
                '<p>连接没有完成，请回到原页面重新开始。</p>',
                status=exc.status_code, content_type='text/html; charset=utf-8',
            )
        response = HttpResponseRedirect(authorization_url)
        response.set_cookie(
            subscription.BINDING_COOKIE_NAME,
            cookie_value,
            max_age=int(subscription.AUTH_ATTEMPT_TTL.total_seconds()),
            httponly=True,
            secure=request.is_secure(),
            samesite='Lax',
            path=subscription.BINDING_COOKIE_PATH,
        )
        return response


class ChatGPTSubscriptionAttemptView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, attempt_id):
        try:
            payload = subscription.authorization_attempt_status(request.user, attempt_id)
        except subscription.SubscriptionError as exc:
            return Response(
                {'error': '授权请求不存在。', 'error_code': exc.error_code},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(payload)

    def delete(self, request, attempt_id):
        cancelled = subscription.cancel_authorization_attempt(request.user, attempt_id)
        if not cancelled:
            try:
                payload = subscription.authorization_attempt_status(request.user, attempt_id)
            except subscription.SubscriptionError as exc:
                return Response(
                    {'error': '授权请求不存在。', 'error_code': exc.error_code},
                    status=status.HTTP_404_NOT_FOUND,
                )
            return Response(payload)
        return Response({
            'id': str(attempt_id), 'status': 'cancelled', 'message': '授权请求已取消。', 'connection_id': None,
        })


class ChatGPTSubscriptionCallbackView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        result_code = 200
        try:
            subscription._require_network_mode()
            redirect = urlparse(subscription.REDIRECT_URI)
            if (
                request.path != subscription.BINDING_COOKIE_PATH or
                request.get_host().lower() != redirect.netloc.lower() or
                request.is_secure() != (redirect.scheme == 'https')
            ):
                raise subscription.SubscriptionError(
                    '回调地址与授权请求不匹配。', 'callback_origin_mismatch', 400,
                )
            subscription.complete_authorization(
                request.query_params,
                request.COOKIES.get(subscription.BINDING_COOKIE_NAME, ''),
                session_key=request.session.session_key or '',
                user_id=request.user.pk,
            )
        except subscription.SubscriptionError as exc:
            message = _safe_callback_message(exc.error_code)
            result_code = exc.status_code
        else:
            message = 'ChatGPT 订阅连接已完成。可以关闭此窗口，原页面会自动更新。'
        safe_message = html.escape(message)
        page = (
            '<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>ChatGPT 订阅连接</title>'
            '<body style="font:16px system-ui;max-width:36rem;margin:10vh auto;padding:1rem">'
            f'<h1>{"连接完成" if result_code == 200 else "连接未完成"}</h1>'
            f'<p>{safe_message}</p><p>关闭此窗口后，回到新闻聚合器查看连接状态。</p>'
            '</body></html>'
        )
        response = HttpResponse(page, status=result_code, content_type='text/html; charset=utf-8')
        response.set_cookie(
            subscription.BINDING_COOKIE_NAME,
            '',
            max_age=0,
            httponly=True,
            secure=request.is_secure(),
            samesite='Lax',
            path=subscription.BINDING_COOKIE_PATH,
        )
        return response


class ChatGPTSubscriptionModelsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, connection_id):
        try:
            connection = subscription.get_user_connection(request.user, connection_id)
            models = subscription.discover_models(connection)
        except subscription.SubscriptionError as exc:
            return _subscription_error_response(exc)
        return Response({'models': models, 'selected_model': connection.selected_model})


class ChatGPTSubscriptionActivateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, connection_id):
        try:
            connection = subscription.activate_connection(request.user, connection_id)
        except subscription.SubscriptionError as exc:
            return _subscription_error_response(exc)
        return Response(_connection_payload(connection))


class ChatGPTSubscriptionSelectModelView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, connection_id):
        try:
            connection = subscription.get_user_connection(request.user, connection_id)
            slug = request.data.get('slug')
            if not isinstance(slug, str) or not slug:
                return Response({'error': '请选择模型。'}, status=status.HTTP_400_BAD_REQUEST)
            models = subscription.discover_models(connection)
            if slug not in {model['slug'] for model in models}:
                return Response({'error': '所选模型当前不在此账号的可见列表中。'}, status=status.HTTP_400_BAD_REQUEST)
            connection.selected_model = slug
            connection.save(update_fields=['selected_model', 'updated_at'])
        except subscription.SubscriptionError as exc:
            return _subscription_error_response(exc)
        return Response({'selected_model': connection.selected_model})


class ChatGPTSubscriptionDisconnectView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, connection_id):
        try:
            revoked = subscription.disconnect_connection(request.user, connection_id)
        except subscription.SubscriptionError as exc:
            return _subscription_error_response(exc)
        return Response({'disconnected': True, 'revocation_confirmed': revoked})


class _NoStoreAPIView(APIView):
    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response['Cache-Control'] = 'no-store'
        return response


def _translation_task_payload(task):
    return {
        'id': str(task.pk),
        'status': task.status,
        'generation': task.generation,
        'progress': task.progress,
        'result': task.result,
        'error_code': task.error_code,
        'error_message': task.error_message,
        'updated_at': task.updated_at.isoformat(),
        'finished_at': task.finished_at.isoformat() if task.finished_at else None,
    }




class ChatGPTTranslationTaskView(_NoStoreAPIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, job_id):
        try:
            task = translation_jobs.get_task(job_id, user_id=request.user.pk)
        except subscription.SubscriptionError as exc:
            return _subscription_error_response(exc)
        if task is None:
            return Response({'error': '任务不存在。'}, status=status.HTTP_404_NOT_FOUND)
        return Response(_translation_task_payload(task))


class ChatGPTTranslationTaskCancelView(_NoStoreAPIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, job_id):
        body = request.data
        generation = body.get('generation') if isinstance(body, dict) else None
        if (
            type(generation) is not int or
            not 1 <= generation <= 9223372036854775807
        ):
            return Response(
                {'error': 'generation 必须是正整数。', 'error_code': 'invalid_generation'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            task, _ = translation_jobs.cancel_task(
                job_id, user_id=request.user.pk, generation=generation,
            )
        except subscription.SubscriptionError as exc:
            return _subscription_error_response(exc)
        if task is None:
            return Response({'error': '任务不存在。'}, status=status.HTTP_404_NOT_FOUND)
        return Response(_translation_task_payload(task))


def subscription_translation_response(request, news: News, force=False):
    """SSE adapter for a per-user subscription translation job."""
    user = request.user
    connection = subscription.active_connection_for_user(user)

    def error_response(message):
        def stream():
            yield f"data: {json.dumps({'error': message}, ensure_ascii=False)}\n\n"
        response = StreamingHttpResponse(stream(), content_type='text/event-stream')
        response['Cache-Control'] = 'no-store'
        response['X-Accel-Buffering'] = 'no'
        return response

    if type(force) is not bool:
        return error_response('force 必须是布尔值。')
    if not user.is_authenticated or connection is None:
        return error_response('请先登录并连接 ChatGPT 订阅账号。')
    if not news.full_content:
        return error_response('请先获取完整原文。')

    digest = subscription.source_hash(news.full_content)
    try:
        job = translation_jobs.get_job(user.pk, connection.pk, news.pk, digest)
    except subscription.SubscriptionError as exc:
        return error_response(str(exc))
    cached = ChatGPTArticleTranslation.objects.filter(
        user=user, connection=connection, news=news, source_hash=digest,
    ).first()
    if cached and not force and not (job and not job.done) and not (job and job.status == 'succeeded'):
        response = shared_translations.completed_response(cached, 'private')
        response['Cache-Control'] = 'no-store'
        return response

    terminal_error = bool(job and job.done and job.status in {'failed', 'cancelled', 'interrupted'})
    successful_job = bool(job and job.done and job.status == 'succeeded')

    shared_lease = None
    if (
        not force and not (job and not job.done) and not terminal_error and
        not successful_job
    ):
        shared = shared_translations.get_shared_translation(news)
        if shared is not None:
            response = shared_translations.completed_response(shared)
            response['Cache-Control'] = 'no-store'
            return response
        if shared_translations.task_is_running(news):
            response = shared_translations.waiting_response(news)
            response['Cache-Control'] = 'no-store'
            return response
        else:
            if connection.needs_reauth or not connection.connected:
                return error_response('ChatGPT 订阅授权已失效，请重新连接账号。')
            if not connection.selected_model:
                return error_response('请先在订阅设置中选择可见模型。')
            shared_lease = shared_translations.claim_task(news)
            if shared_lease is None:
                response = shared_translations.waiting_response(news)
                response['Cache-Control'] = 'no-store'
                return response

    if connection.needs_reauth or not connection.connected:
        return error_response('ChatGPT 订阅授权已失效，请重新连接账号。')
    if not connection.selected_model:
        return error_response('请先在订阅设置中选择可见模型。')

    try:
        if force or not (job and job.status == 'running' and shared_lease is None):
            job = translation_jobs.start_or_get_job(
                user, connection, news, force=force, shared_lease=shared_lease,
            )
    except subscription.SubscriptionError as exc:
        if shared_lease is not None:
            shared_lease.finish('failed')
        return error_response(str(exc))

    def stream():
        sent_length = 0
        try:
            if job.text:
                yield f"data: {json.dumps({'progress': job.text}, ensure_ascii=False)}\n\n"
                sent_length = len(job.text)
            while not job.done:
                current_length = job.wait_for_update(sent_length, timeout=1.0)
                if current_length > sent_length:
                    data = {'progress': job.text}
                    yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                    sent_length = current_length
            if job.error:
                yield f"data: {json.dumps({'error': job.error}, ensure_ascii=False)}\n\n"
                return
            if job.result is None:
                yield f"data: {json.dumps({'error': '本次翻译没有保存完整结果。'}, ensure_ascii=False)}\n\n"
                return
            yield f"event: complete\ndata: {json.dumps(job.result, ensure_ascii=False)}\n\n"
        except subscription.SubscriptionError as exc:
            yield f"data: {json.dumps({'error': str(exc)}, ensure_ascii=False)}\n\n"
        except GeneratorExit:
            # Closing this subscriber stops only its SSE reader. The background
            # worker continues, matching the existing full-text translation UX.
            return

    response = StreamingHttpResponse(stream(), content_type='text/event-stream')
    response['Cache-Control'] = 'no-store'
    response['X-Accel-Buffering'] = 'no'
    response['Job-ID'] = str(job.id)
    return response
