"""Owner-private progress and CAS actions over existing durable feed intents."""
from datetime import timedelta
from hashlib import sha256
import json
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import F, Q
from django.http import Http404
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, Throttled, ValidationError
from rest_framework.response import Response
from api.models import ChannelSubscription, Source
from api.rss.http import RssAPIView, RssConflict
from api.rss.models import FeedOperation
from api.rss.operations import cancel_operation, enqueue_operation, reconcile_binding, sqlite_retry
from api.rss.subscriptions import engine_identity

STATES = {'pending','running','retry_wait','unknown','manual_blocked','succeeded','failed','cancelled'}

def owned_additions(user):
    instance,account=engine_identity()
    return FeedOperation.objects.filter(actor=user,binding__engine_instance_uuid=instance,binding__account_id=account).filter(
        Q(safe_input__subscription_request__isnull=False)|Q(safe_input__subscription__isnull=False)).select_related('binding', 'shared_operation')


def addition_data(op):
    request=op.safe_input.get('subscription_request',op.safe_input.get('subscription',{}))
    work = (op.shared_operation or op) if op.state not in {'succeeded', 'cancelled', 'failed'} else op
    state = 'pending' if work.state == 'succeeded' and op.state != 'succeeded' else work.state
    unknown=bool(work.safe_result.get('outcome_unknown')) or state in {'unknown','manual_blocked'}
    actions=[]
    if state not in {'succeeded','failed','cancelled'} or (state=='manual_blocked'):
        actions.append('cancel')
    if unknown and state in {'unknown','manual_blocked'}: actions.append('reconcile')
    elif state=='failed' and work.execution_phase in {'not_sent','final_response'} and not op.safe_input.get('bulk_import'):
        from api.rss.import_models import RssImportItem
        if not RssImportItem.objects.filter(operation=op).exists(): actions.append('retry')
    cooldown=op.created_at+timedelta(seconds=60)
    # Count only the actor's current source audience, never the whole physical Feed.
    from api.rss.access import authorized_sources, news_in_sources
    from api.rss.models import FeedSyncState
    source_id=request.get('source_id')
    sources=authorized_sources(op.actor,Source.objects.filter(pk=source_id))
    from api.models import News
    article_count=news_in_sources(News.objects.all(),sources).count() if op.state=='succeeded' else 0
    completed=FeedSyncState.objects.filter(engine_instance_uuid=op.binding.engine_instance_uuid,account_id=op.binding.account_id,
        last_complete_at__gte=op.updated_at).exists() if op.state=='succeeded' else False
    article_state='ready' if article_count else ('empty' if completed else 'waiting')
    return {'operation_id':str(op.pk),'source_id':request.get('source_id'),
        'name': op.binding.rsshub_alias or op.binding.canonical_feed_url,'feed_url':op.binding.rsshub_alias or op.binding.canonical_feed_url,
        'article_count':article_count,'article_state':article_state,
        'state':state,'version':op.user_intent_version,'actions':actions,
        'error_code':work.safe_result.get('code',''),'cooldown_until':cooldown.isoformat(),
        'created_at':op.created_at.isoformat(),'connection_state':op.binding.connection_state,
        'recovery_of':str(op.recovery_of_id) if op.recovery_of_id else None,
        'can_recommend':op.state=='succeeded' and ChannelSubscription.objects.filter(user_id=op.actor_id,source_id=request.get('source_id'),source__publication__publication='personal').exists()}


def pagination(params):
    try:
        page=int(params.get('page',1)); size=int(params.get('page_size',25))
        if page<1 or page>100000 or size not in (25,50): raise ValueError
    except (ValueError,TypeError): raise ValidationError('页码须为正整数，每页25或50条。') from None
    return page,size


def list_additions(user, *, status='all', page=1, page_size=25):
    if status not in STATES|{'all'}: raise ValidationError('无效的添加状态。')
    rows=owned_additions(user).order_by('-created_at','-pk')
    if status!='all': rows=rows.filter(state=status)
    return {'results':[addition_data(op) for op in rows[(page-1)*page_size:page*page_size]],
        'count':rows.count(),'page':page,'page_size':page_size,'server_time':timezone.now().isoformat()}


def check_addition_limit(user,url, *, bulk_import=False):
    rows=owned_additions(user).filter(Q(safe_input__bulk_import__isnull=True) | Q(safe_input__bulk_import=False))
    if rows.filter(binding__canonical_feed_url=url,state__in=['pending','running','retry_wait','unknown','manual_blocked']).exists(): return
    # A confirmed, bounded OPML batch is one bulk intent, not hundreds of
    # manual additions. Keep its live queue bounded; uncertain targets retain
    # their own reconciliation fences without blocking unrelated feed URLs.
    active_states = ['pending', 'running', 'retry_wait'] if bulk_import else ['pending', 'running', 'retry_wait', 'unknown', 'manual_blocked']
    active=rows.filter(state__in=active_states).values('binding_id').distinct().count()
    if not bulk_import:
        recent=rows.filter(created_at__gte=timezone.now()-timedelta(hours=1)).values('binding_id').distinct().count()
        if recent>=getattr(settings,'RSS_ADDITION_HOURLY_LIMIT',20): raise Throttled(wait=3600,detail='每小时新增来源次数已达上限。')
    if active>=getattr(settings,'RSS_ADDITION_ACTIVE_LIMIT',5): raise Throttled(wait=60,detail='请先处理已有连接任务。')


def request_key(request):
    key=request.headers.get('Idempotency-Key')
    if not isinstance(key,str) or not 1<=len(key)<=128 or not key.isprintable(): raise ValidationError('请提供有效的 Idempotency-Key。')
    return key


@sqlite_retry
@transaction.atomic
def addition_action(user, operation_id, *, action, expected_version, key):
    if not get_user_model().objects.filter(pk=user.pk,is_active=True).update(last_login=F('last_login')):
        raise PermissionDenied('账号不可用。')
    op=owned_additions(user).filter(pk=operation_id).first()
    if op is None: raise Http404
    if action not in {'retry','reconcile','cancel'} or type(expected_version) is not int or expected_version<1:
        raise ValidationError('请提供操作及当前版本。')
    token=sha256(key.encode()).hexdigest()
    fingerprint=sha256(json.dumps([action,expected_version]).encode()).hexdigest()
    prior=op.safe_input.get('addition_actions',{}).get(token)
    if prior:
        if prior['hash']!=fingerprint: raise RssConflict('幂等键已用于不同请求。')
        result=owned_additions(user).get(pk=prior['operation_id'])
        return addition_data(result)
    if op.user_intent_version!=expected_version: raise RssConflict()
    if action not in addition_data(op)['actions']: raise RssConflict('当前状态不允许此操作。')
    result=op
    if action=='cancel':
        cancel_operation(user,op.pk)
    elif action=='reconcile':
        target = op.shared_operation_id or op.pk
        if not FeedOperation.objects.filter(pk=target, state__in=['unknown', 'manual_blocked']).update(
                state='unknown', next_attempt=timezone.now(), lease_epoch=F('lease_epoch')+1, lease_token=None, lease_until=None):
            raise RssConflict('共享任务已开始处理，请刷新进度。')
    else:
        from api.rss.import_models import RssImportItem
        if op.safe_input.get('bulk_import') or RssImportItem.objects.filter(operation=op).exists():
            raise RssConflict('请在导入历史中重试此项，以保留批次取消和移除范围。')
        # An explicit failure is not authority to resend another possibly-sent request.
        uncertain=FeedOperation.objects.filter(binding=op.binding,shared_operation__isnull=True,resolved_at__isnull=True).exclude(pk=op.pk).filter(
            Q(state__in=['unknown','manual_blocked'])|Q(safe_result__outcome_unknown=True))
        if uncertain.exists(): raise RssConflict('存在结果未知的请求，请先核对。')
        elapsed=(timezone.now()-op.created_at).total_seconds()
        if elapsed<60: raise Throttled(wait=60-elapsed,detail='连接重试冷却中。')
        check_addition_limit(user,op.binding.canonical_feed_url)
        result=enqueue_operation('register' if op.binding.engine_feed_id is None else 'set_enabled',actor=user,binding=op.binding,dedupe_key='addition:'+token)
        original=op.safe_input.get('subscription_request')
        if not original: raise RssConflict('原订阅意图已结束。')
        FeedOperation.objects.filter(pk=result.pk).update(recovery_of=op,safe_input={'subscription_request':original})
        reconcile_binding(op.binding_id)
        result.binding.refresh_from_db()
        FeedOperation.objects.filter(pk=result.pk).update(intent_version=result.binding.policy_version)
    op.refresh_from_db()
    inputs=dict(op.safe_input); actions=dict(inputs.get('addition_actions',{}))
    actions[token]={'hash':fingerprint,'operation_id':str(result.pk)}; inputs['addition_actions']=actions
    FeedOperation.objects.filter(pk=op.pk).update(safe_input=inputs,user_intent_version=F('user_intent_version')+1)
    result.refresh_from_db()
    return addition_data(result)


class AdditionsView(RssAPIView):
    def get(self,request):
        page,size=pagination(request.query_params)
        return Response(list_additions(request.user,status=request.query_params.get('status','all'),page=page,page_size=size))


class AdditionActionView(RssAPIView):
    def post(self,request,pk):
        if set(request.data)!={'action','expected_version'}: raise ValidationError('请提供操作及版本。')
        return Response(addition_action(request.user,pk,action=request.data['action'],expected_version=request.data['expected_version'],key=request_key(request)))
