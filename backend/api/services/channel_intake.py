"""Credential-free intake URLs and one-way, auditable review decisions."""
import ipaddress
import re
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit
from django.core.validators import URLValidator
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import ValidationError, PermissionDenied
from api.models import Source
from api.smart_channel_models import ChannelIntakeRequest
from api.services.channel_grouping import lock_user, GroupingConflict
from api.services.source_policy import policy_for_name

# A narrow public-query contract, rather than a forever-incomplete blacklist.
PUBLIC_QUERY_KEYS = frozenset({'feed', 'files', 'format', 'lang', 'language', 'category', 'tag', 'page', 'id', 'output', 'topic'})
VALUE_PATTERN = re.compile(r'^[\w .,\-]{0,80}$', re.UNICODE)
OPAQUE_PATH = re.compile(r'(?:^|/)[A-Za-z0-9_\-]{40,}(?:/|$)')
SECRET_PATH = re.compile(r'(?:^|/)(?:token|apikey|api-key|api_key|password|signature|credential|authorization)(?:/|$)', re.I)


def _decode(value):
    for _ in range(3):
        decoded = unquote(value)
        if decoded == value:
            return value
        value = decoded
    if unquote(value) != value:
        raise ValueError('nested_encoding')
    return value


def normalize_intake_url(value):
    message = '只接受不含令牌、签名或私有参数的公开网站/RSS 地址；请提交公开入口。'
    try:
        if not isinstance(value, str) or not 1 <= len(value) <= 1024 or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError('invalid_url')
        value = value.strip()
        URLValidator(schemes=['http', 'https'])(value)
        parsed = urlsplit(value)
        host = (parsed.hostname or '').encode('idna').decode('ascii').lower().rstrip('.')
        if (parsed.username is not None or parsed.password is not None or '@' in parsed.netloc
                or '#' in value or parsed.port not in (None, 80, 443)):
            raise ValueError('credentials_or_port')
        if host in {'localhost', 'metadata.google.internal'} or host.endswith(('.local', '.localhost', '.internal')):
            raise ValueError('private_host')
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise ValueError('literal_ip')
        decoded_path = _decode(parsed.path)
        if (any(ord(c) < 32 or ord(c) == 127 for c in decoded_path) or '\\' in decoded_path
                or SECRET_PATH.search(decoded_path) or OPAQUE_PATH.search(decoded_path)):
            raise ValueError('private_path')
        pairs = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True, max_num_fields=8)
        normalized = []
        for key, query_value in pairs:
            key, query_value = _decode(key).casefold(), _decode(query_value)
            if key not in PUBLIC_QUERY_KEYS or not VALUE_PATTERN.fullmatch(query_value):
                raise ValueError('private_query')
            normalized.append((key, query_value))
        if len({key for key, _ in normalized}) != len(normalized):
            raise ValueError('duplicate_query')
        netloc = host
        if parsed.port is not None and parsed.port != (443 if parsed.scheme == 'https' else 80):
            netloc += f':{parsed.port}'
        normalized_query = urlencode(sorted(normalized))
        canonical = urlunsplit((parsed.scheme.lower(), netloc, parsed.path or '/', normalized_query, ''))
        if len(canonical) > 1024:
            raise ValueError('too_long')
        return canonical, host.removeprefix('www.'), decoded_path.rstrip('/'), normalized_query
    except (ValueError, UnicodeError, DjangoValidationError):
        raise ValidationError(message) from None


def intake_data(item):
    try:
        url = normalize_intake_url(item.url)[0]
        requires_resubmission = False
    except ValidationError:
        # Historical records may predate the safe intake contract. Never echo
        # the old private URL into either user or administrator responses.
        url, requires_resubmission = '', True
    return {'id': item.pk, 'url': url, 'status': item.status, 'created_at': item.created_at,
            'reason': item.review_reason, 'reviewed_at': item.reviewed_at,
            'review_revision': item.review_revision, 'source_id': item.registered_source_id,
            'requires_resubmission': requires_resubmission,
            'collection_enabled': False}


@transaction.atomic
def review_intake(reviewer, pk, payload):
    if not reviewer.is_active or not reviewer.is_superuser:
        raise PermissionDenied()
    lock_user(reviewer)
    item = get_object_or_404(ChannelIntakeRequest.objects.select_for_update(), pk=pk)
    decision, reason = payload.get('status'), payload.get('reason')
    expected, source_id = payload.get('review_revision'), payload.get('source_id')
    if decision not in {'approved', 'rejected'} or not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 500:
        raise ValidationError('请选择通过或驳回，并填写 1–500 字审核说明。')
    if type(expected) is not int or expected < 0:
        raise ValidationError('缺少有效审核版本，请刷新列表。')
    reason = reason.strip()
    if source_id is not None and (type(source_id) is not int or source_id <= 0 or decision != 'approved'):
        raise ValidationError('只能为通过的申请选择已登记来源。')
    if item.status != 'pending':
        if (item.status == decision and item.review_reason == reason and item.registered_source_id == source_id
                and item.reviewed_by_id == reviewer.pk):
            return item
        raise GroupingConflict('申请已被审核，不能覆盖既有决定。')
    if expected != item.review_revision:
        raise GroupingConflict('审核版本已变化，请刷新列表。')
    if decision == 'approved':
        normalize_intake_url(item.url)
    if source_id is not None:
        source = get_object_or_404(Source, pk=source_id)
        policy = policy_for_name(source.name)
        if policy is None or policy.unsupported_reason:
            raise ValidationError('目标必须是已审核登记的可用来源。')
    item.status, item.review_reason = decision, reason
    item.reviewed_by, item.reviewed_at = reviewer, timezone.now()
    item.registered_source_id = source_id
    item.review_revision += 1
    item.save(update_fields=['status', 'review_reason', 'reviewed_by', 'reviewed_at', 'registered_source', 'review_revision'])
    return item
