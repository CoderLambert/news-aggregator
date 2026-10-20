"""Consent-based public candidates; editorial approval is not feed health."""
from dataclasses import asdict
from datetime import timedelta
from hashlib import sha256
import json
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import F
from django.http import Http404
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, Throttled, ValidationError
from api.models import Category, ChannelSubscription
from api.rss.feed_policy import approved_feed_policy, assert_binding_policy
from api.rss.http import RssConflict
from api.rss.models import FeedBinding, FeedOperation, SourceFeedLink
from api.rss.operations import canonicalize_feed_url, enqueue_operation, get_or_create_binding, sqlite_retry
from api.rss.review_models import PublicFeedCandidate, PublicFeedSubmission, PublicFeedReviewEvent
from api.rss.review_permissions import review_authority, assert_review_authority, require_superuser
from api.rss.subscriptions import engine_identity


def reserve(actor):
    if not get_user_model().objects.filter(pk=actor.pk,is_active=True).update(last_login=F('last_login')):
        raise PermissionDenied('账号不可用。')


def candidates():
    instance,account=engine_identity()
    return PublicFeedCandidate.objects.filter(binding__engine_instance_uuid=instance,binding__account_id=account).select_related('binding','category','decision__actor')


def candidate_data(candidate, *, viewer):
    authority=review_authority(viewer)
    own=candidate.submissions.filter(user=viewer).exists()
    last=FeedOperation.objects.filter(binding=candidate.binding,kind__in=['register','set_enabled','update_feed_policy']).order_by('-created_at').first()
    cooldown=(last.created_at+timedelta(seconds=60)).isoformat() if last else None
    return {'candidate_id':str(candidate.pk),'name':candidate.name,'feed_url':candidate.binding.rsshub_alias or candidate.binding.canonical_feed_url,
        'effective_feed_url':candidate.binding.effective_feed_url,'category_id':candidate.category_id,
        'category_name':candidate.category.name,'language':candidate.language,'version':candidate.version,
        'state':candidate.state,'connection_state':candidate.binding.connection_state,
        'public_source_id':candidate.public_source_id,'scope_description':'公开 Feed 最近七天内经验证的文章及后续文章；个人记录不公开',
        'can_review':bool(authority and (authority.superuser or not own) and candidate.state in {'pending','approved'}),
        'can_verify':bool(authority and (authority.superuser or not own)), 'cooldown_until':cooldown,'reason':candidate.decision.reason if candidate.decision else '',
        'error_code':candidate.binding.last_error,'member_sync_complete':candidate.member_sync_complete,
        'created_at':candidate.created_at.isoformat()}


def metadata(data):
    name=data.get('name'); language=data.get('language','zh'); category_id=data.get('category_id')
    if not isinstance(name,str) or not 1<=len(name.strip())<=255 or any(c in name for c in '<>'):
        raise ValidationError('频道名称须为1–255字符。')
    if not isinstance(language,str) or language not in {'zh','en','other'} or type(category_id) is not int:
        raise ValidationError('请选择分类和语言。')
    category=Category.objects.filter(pk=category_id).first()
    if category is None: raise ValidationError('分类不存在。')
    return name.strip(),category,language


def version(data):
    value=data.get('expected_version')
    if type(value) is not int or value<1: raise ValidationError('请提供当前版本。')
    return value


def fingerprint(data): return sha256(json.dumps(data,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def replay(actor,key,data):
    event=PublicFeedReviewEvent.objects.filter(actor=actor,key=key).first()
    if event:
        if event.request_hash!=fingerprint(data): raise RssConflict('幂等键已用于不同请求。')
        # Current instance is a separate authorization boundary, even on a replay.
        if not candidates().filter(pk=event.candidate_id).exists(): raise Http404
        return event.result


def record(candidate,actor,key,data,action,result,authority=None):
    return PublicFeedReviewEvent.objects.create(candidate=candidate,actor=actor,key=key,
        candidate_version=candidate.version,authority=asdict(authority) if authority else {},
        action=action,reason=data.get('reason',''),request_hash=fingerprint(data),result=result)


def submission_result(submission,viewer):
    personal = ChannelSubscription.objects.filter(user=viewer,source__publication__publication='personal',source__feed_links__binding_id=submission.candidate.binding_id).order_by('pk').first()
    return {**candidate_data(submission.candidate,viewer=viewer),'personal_source_id':personal.source_id if personal else None,'submission_id':str(submission.pk),
        'note':submission.note,'withdrawn':submission.withdrawn_at is not None}


def submit_inner(user,data,key):
    if set(data)-{'source_id','name','category_id','language','note','confirm_public_scope'} or data.get('confirm_public_scope') is not True:
        raise ValidationError('请确认公共频道的公开范围。')
    name,category,language=metadata(data)
    note=data.get('note','')
    if not isinstance(note,str) or len(note)>1000 or type(data.get('source_id')) is not int: raise ValidationError('推荐资料无效。')
    subscription=ChannelSubscription.objects.filter(user=user,source_id=data['source_id']).select_related('source__publication').first()
    if subscription is None: raise Http404
    if subscription.source.publication.publication != 'personal': raise RssConflict('该频道已经公开，无需重复推荐。')
    instance,account=engine_identity()
    link=SourceFeedLink.objects.filter(source=subscription.source,binding__engine_instance_uuid=instance,
        binding__account_id=account,enabled=True).select_related('binding').first()
    if not link or subscription.source.publication.owner!='miniflux': raise RssConflict('来源尚未连接。')
    binding=link.binding
    approved_feed_policy(binding.canonical_feed_url); assert_binding_policy(binding)
    from api.rss.operations import unresolved_control_operations
    if (binding.connection_state!='ready' or binding.applied_policy_version!=binding.policy_version
            or binding.engine_feed_id is None or unresolved_control_operations(binding.pk).exists()):
        raise RssConflict('请先完成来源连接。')
    candidate=candidates().filter(binding=binding).first()
    existing=PublicFeedSubmission.objects.filter(candidate=candidate,user=user).first() if candidate else None
    if not existing or existing.withdrawn_at:
        recent=PublicFeedReviewEvent.objects.filter(actor=user,action='submit',created_at__gte=timezone.now()-timedelta(hours=1)).count()
        active=PublicFeedSubmission.objects.filter(user=user,withdrawn_at__isnull=True,candidate__state__in=['pending','approved']).count()
        if recent>=getattr(settings,'RSS_RECOMMENDATION_HOURLY_LIMIT',20): raise Throttled(wait=3600,detail='推荐次数已达每小时上限。')
        if active>=getattr(settings,'RSS_RECOMMENDATION_ACTIVE_LIMIT',10): raise Throttled(wait=60,detail='请等待已有推荐处理完成。')
    if candidate is None:
        candidate=PublicFeedCandidate.objects.create(binding=binding,name=name,category=category,language=language)
    elif candidate.state in {'rejected','withdrawn'}:
        candidate.version+=1; candidate.state='pending'; candidate.decision=None
        candidate.name=name; candidate.category=category; candidate.language=language; candidate.save()
    if existing:
        existing.withdrawn_at=None; existing.note=note; existing.save(); submission=existing
    else: submission=PublicFeedSubmission.objects.create(candidate=candidate,user=user,note=note)
    result=submission_result(submission,user)
    record(candidate,user,key,data,'submit',result)
    return result


@sqlite_retry
@transaction.atomic
def submit_recommendation(user,data,key):
    reserve(user)
    return replay(user,key,data) or submit_inner(user,data,key)


@sqlite_retry
@transaction.atomic
def change_submission(user,submission_id,data,key):
    reserve(user)
    previous=replay(user,key,data)
    if previous: return previous
    submission=PublicFeedSubmission.objects.select_related('candidate__binding','candidate__category','candidate__decision').filter(
        pk=submission_id,user=user,candidate__in=candidates()).first()
    if submission is None: raise Http404
    candidate=submission.candidate
    if version(data)!=candidate.version: raise RssConflict()
    if data.get('action')=='withdraw' and set(data)=={'action','expected_version'}:
        if candidate.state not in {'pending','withdrawn'}: raise RssConflict('审核决定后不能撤回，个人订阅仍保留。')
        submission.withdrawn_at=timezone.now(); submission.save()
        if not candidate.submissions.filter(withdrawn_at__isnull=True).exists():
            candidate.state='withdrawn'; candidate.version+=1; candidate.save()
        result=submission_result(submission,user); record(candidate,user,key,data,'withdraw',result); return result
    if data.get('action')=='resubmit':
        if candidate.state not in {'rejected','withdrawn','pending'}: raise RssConflict('当前推荐不能修改。')
        submission.withdrawn_at=timezone.now(); submission.save()
        if not candidate.submissions.filter(withdrawn_at__isnull=True).exists():
            candidate.state='withdrawn'; candidate.version+=1; candidate.decision=None; candidate.save()
        new_data={k:v for k,v in data.items() if k not in {'action','expected_version'}}
        result=submit_inner(user,new_data,key)
        # Preserve exact outer request hash for idempotent resubmission.
        PublicFeedReviewEvent.objects.filter(actor=user,key=key).update(request_hash=fingerprint(data))
        return result
    raise ValidationError('请选择撤回或更正后重提。')


@sqlite_retry
@transaction.atomic
def decide_candidate(actor,candidate_id,data,key):
    reserve(actor)
    authority=review_authority(actor)
    if authority is None: raise PermissionDenied('需要频道审核权限。')
    previous=replay(actor,key,data)
    if previous: return previous
    candidate=candidates().filter(pk=candidate_id).first()
    if candidate is None: raise Http404
    if not authority.superuser and candidate.submissions.filter(user=actor).exists(): raise PermissionDenied('不能审核自己提交的推荐。')
    if version(data)!=candidate.version or candidate.state not in {'pending','approved'}: raise RssConflict()
    if set(data)-{'action','expected_version','reason','name','category_id','language'}: raise ValidationError('审核参数无效。')
    action=data.get('action'); reason=data.get('reason','')
    if action not in {'approve','reject'} or not isinstance(reason,str) or len(reason)>1000 or (action=='reject' and not reason.strip()):
        raise ValidationError('驳回时请填写原因。')
    if not candidate.submissions.filter(withdrawn_at__isnull=True).exists() and candidate.creation_mode!='admin': raise RssConflict('推荐已全部撤回。')
    if any(k in data for k in ('name','category_id','language')):
        name,category,language=metadata({'name':data.get('name',candidate.name),'category_id':data.get('category_id',candidate.category_id),'language':data.get('language',candidate.language)})
        candidate.name=name; candidate.category=category; candidate.language=language
    approved_feed_policy(candidate.binding.canonical_feed_url); assert_binding_policy(candidate.binding)
    candidate.version += 1
    result={'candidate_id':str(candidate.pk),'version':candidate.version,'state':'approved' if action=='approve' else 'rejected'}
    event=record(candidate,actor,key,data,action,result,authority)
    candidate.state=result['state']; candidate.decision=event; candidate.save()
    return result


@sqlite_retry
@transaction.atomic
def register_public_candidate(actor,data,key):
    reserve(actor); require_superuser(actor)
    previous=replay(actor,key,data)
    if previous: return previous
    if set(data)-{'feed_url','name','category_id','language'}: raise ValidationError('新增参数无效。')
    name,category,language=metadata(data)
    url=canonicalize_feed_url(data.get('feed_url'))
    admission=approved_feed_policy(url)
    instance,account=engine_identity()
    binding=get_or_create_binding(instance,account,url,desired_mode=admission.desired_mode)
    assert_binding_policy(binding)
    existing=SourceFeedLink.objects.filter(binding=binding,source__publication__publication='public').first()
    candidate=candidates().filter(binding=binding).first()
    if existing:
        return {'candidate_id':str(candidate.pk) if candidate else None,'public_source_id':existing.source_id,'state':'published','version':candidate.version if candidate else 1}
    if candidate:
        return candidate_data(candidate,viewer=actor)
    candidate=PublicFeedCandidate.objects.create(binding=binding,name=name,category=category,language=language,creation_mode='admin',state='approved')
    result=candidate_data(candidate,viewer=actor)
    authority=review_authority(actor)
    event=record(candidate,actor,key,data,'register',result,authority)
    candidate.decision=event; candidate.save(update_fields=['decision'])
    # Durable proof this brand-new intent has not been sent. Worker dispatch
    # and automatic publication are installed before the UI exposes this path.
    op=enqueue_operation('register',actor=actor,binding=binding,dedupe_key='candidate:'+str(candidate.pk))
    from api.rss.operations import reconcile_binding
    from api.rss.admin_verification import binding_snapshot
    reconcile_binding(binding.pk)
    binding.refresh_from_db()
    FeedOperation.objects.filter(pk=op.pk).update(intent_version=binding.policy_version,safe_input={
        'review_target':{'candidate_id':str(candidate.pk),'version':candidate.version,'authority':asdict(authority)},
        'admin_recovery':{'allow_create':True,'snapshot':binding_snapshot(binding),'authority':asdict(authority)}})
    return result


@sqlite_retry
@transaction.atomic
def verify_candidate(actor,candidate_id,data,key):
    reserve(actor)
    authority=review_authority(actor)
    if authority is None: raise PermissionDenied('需要频道审核权限。')
    candidate=candidates().filter(pk=candidate_id).first()
    if candidate is None: raise Http404
    if set(data)!={'expected_version'}: raise ValidationError('请提供当前版本。')
    if version(data)!=candidate.version: raise RssConflict()
    if not authority.superuser and candidate.submissions.filter(user=actor).exists(): raise PermissionDenied('不能核验自己的公开推荐。')
    from api.rss.admin_verification import request_verification
    operation,reason=request_verification(candidate.binding,actor=actor,key='candidate-verify:'+sha256(key.encode()).hexdigest(),recover=True,
        target={'kind':'public_candidate','id':candidate.pk,'version':candidate.version})
    if reason=='cooldown': raise Throttled(wait=60,detail='刚提交过核验，请等待冷却结束。')
    if reason: raise RssConflict('当前连接不能重复执行，请查看核验记录。')
    return {'candidate_id':str(candidate.pk),'state':operation.state}
