"""Always read fresh authority; a regrant cannot revive an old authorization."""
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import transaction
from django.db.models import F
from django.http import Http404
from rest_framework.exceptions import PermissionDenied, ValidationError
from api.rss.http import RssConflict
from api.rss.operations import sqlite_retry
from api.rss.review_models import RssReviewerGrant, RssReviewerEvent
from api.rss.subscriptions import engine_identity


@dataclass(frozen=True)
class ReviewAuthority:
    user_id: int
    instance_uuid: str
    version: int
    superuser: bool


def review_authority(user):
    if not user or not user.is_authenticated:
        return None
    user = get_user_model().objects.filter(pk=user.pk, is_active=True).first()
    if user is None:
        return None
    instance, _ = engine_identity()
    if user.is_superuser:
        return ReviewAuthority(user.pk, str(instance), 0, True)
    grant = RssReviewerGrant.objects.filter(user=user, engine_instance_uuid=instance, active=True).first()
    if grant and user.has_perm('api.review_public_rss'):
        return ReviewAuthority(user.pk, str(instance), grant.version, False)
    return None


def assert_review_authority(user, expected):
    if isinstance(expected, dict):
        try: expected = ReviewAuthority(**expected)
        except (TypeError, ValueError): raise PermissionDenied('审核授权已改变。') from None
    if expected is None or review_authority(user) != expected:
        raise PermissionDenied('审核授权已改变，请刷新。')


def rss_capabilities(user):
    try: authority = review_authority(user)
    except Exception as exc:
        from api.rss.subscriptions import EngineUnavailable
        if not isinstance(exc, EngineUnavailable): raise
        authority = None
    return {'review_public_rss': authority is not None,
            'manage_rss_reviewers': bool(authority and authority.superuser),
            'reviewer_version': authority.version if authority else None}


def require_superuser(user):
    if not get_user_model().objects.filter(pk=user.pk, is_active=True, is_superuser=True).exists():
        raise PermissionDenied('需要超级管理员权限。')


def reviewer_data(grant):
    return {'id': grant.pk, 'username': grant.user.username, 'active': grant.active, 'version': grant.version}


@sqlite_retry
@transaction.atomic
def change_reviewer(actor, username, active, expected_version, key):
    get_user_model().objects.filter(pk=actor.pk).update(last_login=F('last_login'))
    require_superuser(actor)
    if (not isinstance(username,str) or not 1 <= len(username) <= 150 or type(active) is not bool
            or not isinstance(key,str) or not 1 <= len(key) <= 128 or not key.isprintable()
            or (expected_version is not None and (type(expected_version) is not int or expected_version < 1))):
        raise ValidationError('请提供准确用户名、授权状态及版本。')
    instance, _ = engine_identity()
    digest = sha256(json.dumps([str(instance),username,active,expected_version]).encode()).hexdigest()
    old = RssReviewerEvent.objects.filter(actor=actor,key=key).select_related('grant__user').first()
    if old:
        if old.request_hash != digest: raise RssConflict('幂等键已用于不同请求。')
        return {'id':old.grant_id,'username':username,'active':old.active,'version':old.version}
    target = get_user_model().objects.filter(username=username,is_active=True).first()
    if target is None: raise Http404
    if target.is_superuser: raise ValidationError('超级管理员已经拥有权限。')
    grant = RssReviewerGrant.objects.filter(user=target,engine_instance_uuid=instance).first()
    if (grant.version if grant else None) != expected_version: raise RssConflict()
    if grant:
        grant.version += 1; grant.active = active; grant.granted_by = actor; grant.save()
    else:
        grant = RssReviewerGrant.objects.create(user=target,engine_instance_uuid=instance,active=active,granted_by=actor)
    permission = Permission.objects.get(content_type__app_label='api',codename='review_public_rss')
    if active: target.user_permissions.add(permission)
    else: target.user_permissions.remove(permission)
    RssReviewerEvent.objects.create(actor=actor,grant=grant,version=grant.version,active=active,key=key,request_hash=digest)
    return reviewer_data(grant)
