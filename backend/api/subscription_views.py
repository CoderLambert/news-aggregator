"""Authenticated local ChatGPT subscription connection endpoints."""

import html
import json

from django.http import HttpResponse, HttpResponseRedirect, StreamingHttpResponse
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from api.models import ChatGPTArticleTranslation, ChatGPTSubscriptionConnection, News
from api.services import chatgpt_subscription as subscription
from api.services import chatgpt_subscription_jobs as translation_jobs


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


class ChatGPTSubscriptionStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        connections = ChatGPTSubscriptionConnection.objects.filter(user=request.user)
        active = connections.filter(is_active=True).first()
        return Response({
            'connections': [_connection_payload(item) for item in connections],
            'active_connection_id': str(active.pk) if active else None,
        })


class ChatGPTSubscriptionConnectView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        connection_id = request.data.get('connection_id')
        try:
            target = subscription.get_user_connection(request.user, connection_id) if connection_id else None
            if not request.session.session_key:
                request.session.create()
            request.session['chatgpt_oauth_session'] = True
            attempt = subscription.create_authorization_attempt(
                request.user, target, session_key=request.session.session_key or '',
                origin=request.META.get('HTTP_ORIGIN', ''),
            )
        except subscription.SubscriptionError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
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
                f'<p>{html.escape(str(exc))}</p>',
                status=400, content_type='text/html; charset=utf-8',
            )
        response = HttpResponseRedirect(authorization_url)
        response.set_cookie(
            subscription.BINDING_COOKIE_NAME,
            cookie_value,
            max_age=int(subscription.AUTH_ATTEMPT_TTL.total_seconds()),
            httponly=True,
            secure=False,
            samesite='Lax',
            path=subscription.BINDING_COOKIE_PATH,
        )
        return response


class ChatGPTSubscriptionAttemptView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, attempt_id):
        try:
            payload = subscription.authorization_attempt_status(request.user, attempt_id)
        except subscription.SubscriptionError:
            return Response({'error': '授权请求不存在。'}, status=status.HTTP_404_NOT_FOUND)
        return Response(payload)

    def delete(self, request, attempt_id):
        cancelled = subscription.cancel_authorization_attempt(request.user, attempt_id)
        if not cancelled:
            try:
                payload = subscription.authorization_attempt_status(request.user, attempt_id)
            except subscription.SubscriptionError:
                return Response({'error': '授权请求不存在。'}, status=status.HTTP_404_NOT_FOUND)
            return Response(payload)
        return Response({
            'id': str(attempt_id), 'status': 'cancelled', 'message': '授权请求已取消。', 'connection_id': None,
        })


class ChatGPTSubscriptionCallbackView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        try:
            subscription.complete_authorization(
                request.query_params,
                request.COOKIES.get(subscription.BINDING_COOKIE_NAME, ''),
            )
            message = 'ChatGPT 订阅连接已完成。可以关闭此窗口，原页面会自动更新。'
            result_code = 200
        except subscription.SubscriptionError as exc:
            message = str(exc)
            result_code = 400
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
        return HttpResponse(page, status=result_code, content_type='text/html; charset=utf-8')


class ChatGPTSubscriptionModelsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, connection_id):
        try:
            connection = subscription.get_user_connection(request.user, connection_id)
            models = subscription.discover_models(connection)
        except subscription.SubscriptionError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({'models': models, 'selected_model': connection.selected_model})


class ChatGPTSubscriptionActivateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, connection_id):
        try:
            connection = subscription.activate_connection(request.user, connection_id)
        except subscription.SubscriptionError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
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
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({'selected_model': connection.selected_model})


class ChatGPTSubscriptionDisconnectView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, connection_id):
        try:
            revoked = subscription.disconnect_connection(request.user, connection_id)
        except subscription.SubscriptionError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({'disconnected': True, 'revocation_confirmed': revoked})


def subscription_translation_response(request, news: News, force=False):
    """SSE adapter for a per-user subscription translation job."""
    user = request.user
    connection = subscription.active_connection_for_user(user)

    def error_response(message):
        def stream():
            yield f"data: {json.dumps({'error': message}, ensure_ascii=False)}\n\n"
        response = StreamingHttpResponse(stream(), content_type='text/event-stream')
        response['Cache-Control'] = 'no-cache'
        response['X-Accel-Buffering'] = 'no'
        return response

    if not user.is_authenticated or connection is None:
        return error_response('请先登录并连接 ChatGPT 订阅账号。')
    if connection.needs_reauth or not connection.connected:
        return error_response('ChatGPT 订阅授权已失效，请重新连接账号。')
    if not connection.selected_model:
        return error_response('请先在订阅设置中选择可见模型。')
    if not news.full_content:
        return error_response('请先获取完整原文。')

    digest = subscription.source_hash(news.full_content)
    job = translation_jobs.get_job(user.pk, connection.pk, news.pk, digest)
    cached = ChatGPTArticleTranslation.objects.filter(
        user=user, connection=connection, news=news, source_hash=digest,
    ).first()
    if cached and not force and not (job and not job.done):
        def existing_stream():
            data = {
                'full_content_zh': cached.content,
                'full_content_zh_fetched_at': cached.completed_at.isoformat(),
            }
            yield f"event: complete\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
        response = StreamingHttpResponse(existing_stream(), content_type='text/event-stream')
        response['Cache-Control'] = 'no-cache'
        response['X-Accel-Buffering'] = 'no'
        return response

    try:
        job = translation_jobs.start_or_get_job(user, connection, news)
    except subscription.SubscriptionError as exc:
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
        except GeneratorExit:
            # Closing this subscriber stops only its SSE reader. The background
            # worker continues, matching the existing full-text translation UX.
            return

    response = StreamingHttpResponse(stream(), content_type='text/event-stream')
    response['Cache-Control'] = 'no-cache'
    response['X-Accel-Buffering'] = 'no'
    return response
