"""Credential-safe channel applications; review never activates a source."""
import ipaddress
import re
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import URLValidator
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from rest_framework.exceptions import APIException, NotFound, PermissionDenied, Throttled, ValidationError

from api.smart_channel_models import ChannelIntakeRequest
from api.services.channel_grouping import lock_user

# Applications are public catalog suggestions, not private feed credentials.
# Unknown/signed query fields must be removed by the applicant, never silently
# stripped and stored as a potentially different resource.
PUBLIC_QUERY_FIELDS = frozenset({'feed', 'format', 'category', 'cat', 'tag', 'section',
                                'lang', 'language', 'q', 's', 'id', 'type', 'page'})
QUERY_VALUE = re.compile(r'^[\w .,:+\-/]{0,100}$', re.UNICODE)


class IntakeConflict(APIException):
    status_code = 409
    default_detail = '申请已经由管理员处理，请刷新后查看结果。'


def normalize_intake_url(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 1024:
        raise ValidationError('请输入有效的公开网站或 RSS 地址。')
    value = value.strip()
    try:
        if any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError()
        URLValidator(schemes=['http', 'https'])(value)
        parsed = urlsplit(value)
        host = (parsed.hostname or '').encode('idna').decode('ascii').lower().rstrip('.')
        if (parsed.username is not None or parsed.password is not None or parsed.fragment
                or parsed.port not in (None, 80, 443)):
            raise ValueError()
        if (not host or host in {'localhost', 'metadata.google.internal'}
                or host.endswith(('.localhost', '.local', '.internal'))):
            raise ValueError()
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise ValueError()
        fields = parse_qsl(parsed.query, keep_blank_values=True, max_num_fields=20)
        seen = set()
        for key, content in fields:
            normalized_key = key.casefold()
            if normalized_key not in PUBLIC_QUERY_FIELDS or normalized_key in seen:
                raise ValueError()
            seen.add(normalized_key)
            # Disallow nested/signed URLs and double-encoded credentials.
            decoded = unquote(content)
            if decoded != content or not QUERY_VALUE.fullmatch(content) or '://' in content:
                raise ValueError()
        canonical_query = urlencode(sorted(fields))
        authority = host + (f':{parsed.port}' if parsed.port and parsed.port != (443 if parsed.scheme == 'https' else 80) else '')
        canonical = urlunsplit((parsed.scheme.lower(), authority, parsed.path or '/', canonical_query, ''))
    except (ValueError, UnicodeError, DjangoValidationError):
        # Never echo the submitted URL or a token into an error/log.
        raise ValidationError('仅接受无凭据、无签名参数的公开 HTTP(S) 频道地址。') from None
    return canonical, host.removeprefix('www.'), parsed.path.rstrip('/'), canonical_query


def intake_data(item):
    try:
        safe_url = normalize_intake_url(item.url)[0]
        url_safe = True
    except ValidationError:
        safe_url, url_safe = '', False
    return {'id': item.pk, 'url': safe_url, 'url_safe': url_safe,
            'status': item.status, 'created_at': item.created_at,
            'review_reason': item.review_reason,
            'reviewed_at': item.reviewed_at,
            'activation_status': 'not_enabled'}


@transaction.atomic
def submit_intake(user, value):
    lock_user(user)
    url = normalize_intake_url(value)[0]
    previous = ChannelIntakeRequest.objects.filter(user=user, url=url).first()
    if previous is not None:
        return previous, False
    if ChannelIntakeRequest.objects.filter(user=user, created_at__date=timezone.localdate()).count() >= 10:
        raise Throttled(3600, '已达到今日接入申请上限。')
    return ChannelIntakeRequest.objects.create(user=user, url=url), True


@transaction.atomic
def review_intake(reviewer, pk, decision, reason):
    if not reviewer.is_authenticated or not reviewer.is_active or not reviewer.is_superuser:
        raise PermissionDenied()
    if decision not in {'approved', 'rejected'}:
        raise ValidationError('请选择批准受理或驳回。')
    if (not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 500
            or any(ord(c) < 32 and c not in '\n\t' for c in reason)):
        raise ValidationError('请填写 1–500 字的审核说明，不要包含凭据。')
    reason = reason.strip()
    # First write is the SQLite writer reservation; concurrent administrators
    # cannot both read pending and produce conflicting decisions.
    if not ChannelIntakeRequest.objects.filter(pk=pk).update(status=F('status')):
        raise NotFound()
    item = ChannelIntakeRequest.objects.get(pk=pk)
    if item.status == decision and item.review_reason == reason:
        return item
    if item.status != 'pending':
        raise IntakeConflict()
    if decision == 'approved':
        normalize_intake_url(item.url)
    updated = ChannelIntakeRequest.objects.filter(pk=pk, status='pending').update(
        status=decision, review_reason=reason, reviewed_by=reviewer, reviewed_at=timezone.now())
    if updated != 1:
        raise IntakeConflict()
    item.refresh_from_db()
    return item
