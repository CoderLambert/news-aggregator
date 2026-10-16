"""Website/Feed discovery through durable engine operations, never publisher HTTP."""
from datetime import timedelta
from hashlib import sha256
from urllib.parse import parse_qsl, urlsplit
import uuid

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import signing
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from rest_framework.exceptions import Throttled, ValidationError
from rest_framework.response import Response

from api.rss.http import RssAPIView
from api.rss.models import FeedOperation

TOKEN_SALT = 'rss.discovery.candidate.v1'
TOKEN_SECONDS = 15 * 60
ACTIVE_STATES = ('pending', 'running', 'retry_wait', 'unknown')
SECRET_KEYS = {'token', 'access_token', 'api_key', 'apikey', 'password', 'secret',
               'auth', 'authorization', 'cookie', 'signature'}


def normalize_input(value):
    from api.rss.engine import EngineError
    from api.rss.operations import OperationError, canonicalize_feed_url
    if not isinstance(value, str) or not 1 <= len(value) <= 1024:
        raise ValidationError('请输入公开 HTTPS 网址或域名。')
    value = value.strip()
    if '://' not in value:
        value = 'https://' + value
    try:
        parsed = urlsplit(value)
        if any(key.lower() in SECRET_KEYS for key, _ in parse_qsl(parsed.query)):
            raise ValueError
        return canonicalize_feed_url(value)
    except (ValueError, EngineError, OperationError):
        raise ValidationError('请输入不含凭据的公开 HTTPS 网址。') from None


def discovery_operation_result(operation, user):
    """Safe polling result; candidate signatures are minted only for the actor."""
    if not user.is_authenticated or operation.actor_id != user.pk or operation.kind != 'discover':
        from django.http import Http404
        raise Http404
    if operation.state != 'succeeded':
        return {'operation_id': str(operation.pk), 'state': operation.state,
                'error_code': operation.safe_result.get('code'),
                'retryable': bool(operation.safe_result.get('retryable', False))}
    candidates = []
    seen = set()
    for row in operation.safe_result.get('candidates', [])[:20]:
        try:
            url = normalize_input(row.get('url'))
        except (ValidationError, AttributeError):
            continue
        if url in seen:
            continue
        seen.add(url)
        title = row.get('title', '')
        if not isinstance(title, str) or '<' in title or '>' in title:
            title = ''
        candidates.append({'url': url, 'title': title[:255], 'candidate_token': signing.dumps(
            {'user_id': user.pk, 'url': url, 'operation_id': str(operation.pk)}, salt=TOKEN_SALT),
            'expires_in': TOKEN_SECONDS, 'cached_articles': []})
    return {'operation_id': str(operation.pk), 'state': 'succeeded', 'candidates': candidates}


def resolve_candidate_token(user, token):
    """A token selects a candidate; the subscription service still checks policy."""
    try:
        if not isinstance(token, str) or len(token) > 4096:
            raise ValueError
        data = signing.loads(token, salt=TOKEN_SALT, max_age=TOKEN_SECONDS)
        if data['user_id'] != user.pk or not user.is_authenticated:
            raise ValueError
        url = normalize_input(data['url'])
        operation = FeedOperation.objects.get(pk=data['operation_id'], actor=user,
                                               kind='discover', state='succeeded')
        if not any(row.get('url') == url for row in operation.safe_result.get('candidates', [])):
            raise ValueError
        return url
    except (signing.BadSignature, KeyError, TypeError, ValueError, FeedOperation.DoesNotExist):
        raise ValidationError('发现候选已失效，请重新发现。') from None


@transaction.atomic
def resolve_input(user, value):
    from api.rss.operations import enqueue_operation
    url = normalize_input(value)
    # Serialize quota and dedupe decisions on SQLite before reading operations.
    get_user_model().objects.filter(pk=user.pk).update(last_login=F('last_login'))
    now = timezone.now()
    operations = FeedOperation.objects.filter(actor=user, kind='discover', safe_input__url=url)
    cached = operations.filter(state='succeeded', updated_at__gte=now - timedelta(seconds=TOKEN_SECONDS)).order_by('-updated_at').first()
    if cached:
        return 200, discovery_operation_result(cached, user)
    active = operations.filter(state__in=ACTIVE_STATES).order_by('-created_at').first()
    if active:
        return 202, discovery_operation_result(active, user)
    limit = int(getattr(settings, 'RSS_DISCOVERY_HOURLY_LIMIT', 20))
    if FeedOperation.objects.filter(actor=user, kind='discover', created_at__gte=now - timedelta(hours=1)).count() >= limit:
        raise Throttled(wait=3600, detail='发现次数已达每小时上限，请稍后重试。')
    operation = enqueue_operation('discover', actor=user,
        dedupe_key='discover:' + sha256(url.encode()).hexdigest()[:32] + ':' + uuid.uuid4().hex,
        url=url)
    return 202, discovery_operation_result(operation, user)


class ResolveFeedView(RssAPIView):
    def post(self, request):
        if not isinstance(request.data, dict) or set(request.data) != {'input'}:
            raise ValidationError('请只提供 input 字段。')
        status, data = resolve_input(request.user, request.data['input'])
        return Response(data, status=status)
