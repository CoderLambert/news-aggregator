"""Explicit public article membership, independent of shared feed references."""
from datetime import datetime, timedelta, timezone as utc
from hashlib import sha256
from urllib.parse import urlsplit
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from api.models import Source
from api.rss.models import EngineEntryMap, SourcePublication, SourceFeedLink, FeedBinding
from api.rss.review_models import PublicFeedCandidate, PublicFeedEntry
from api.rss.review_permissions import assert_review_authority
from api.rss.feed_policy import approved_feed_policy, assert_binding_policy
from api.rss.operations import unresolved_control_operations, reconcile_binding, sqlite_retry
from api.rss.http import RssConflict


def public_entries_for_sources(sources):
    return PublicFeedEntry.objects.filter(source_id__in=sources.values('pk'),
        source__publication__publication='public',source__publication__requires_public_membership=True,
        source__public_candidate__state='published',approval_version=F('source__public_candidate__version'),
        entry__binding_id=F('source__public_candidate__binding_id'),entry__disposition='linked',
        entry__source_url=F('entry__news__url'))


@sqlite_retry
@transaction.atomic
def publish_candidate(candidate_id,expected_version):
    PublicFeedCandidate.objects.filter(pk=candidate_id).update(updated_at=F('updated_at'))
    from api.rss.recommendations import candidates,candidate_data
    candidate=candidates().get(pk=candidate_id)
    if candidate.version!=expected_version: raise RssConflict()
    if candidate.state=='published': return {'public_source_id':candidate.public_source_id,'state':'published'}
    if candidate.state!='approved' or not candidate.decision_id: return {'state':candidate.state}
    assert_review_authority(candidate.decision.actor,candidate.decision.authority)
    if candidate.decision.candidate_version!=candidate.version: raise RssConflict()
    binding=candidate.binding
    assert_binding_policy(binding)
    admission=approved_feed_policy(binding.canonical_feed_url)
    if (binding.engine_feed_id is None or binding.connection_state!='ready'
            or binding.applied_policy_version!=binding.policy_version or unresolved_control_operations(binding.pk).exists()):
        return {'state':'approved','reason':'connection_pending'}
    source=Source.objects.create(name='Public RSS '+str(candidate.pk),url='https://'+urlsplit(binding.canonical_feed_url).netloc,
        language=candidate.language,description='公开 RSS 频道')
    SourcePublication.objects.create(source=source,publication='public',owner='miniflux',display_name=candidate.name,
        reading_policy=admission.reading_policy,requires_public_membership=True)
    SourceFeedLink.objects.create(source=source,binding=binding,enabled=True,editorial_pin=True)
    candidate.public_source=source; candidate.state='published'
    candidate.scope_since=timezone.now()-timedelta(days=7)
    if binding.published_since:
        candidate.scope_since=max(candidate.scope_since,datetime.combine(binding.published_since,datetime.min.time(),tzinfo=utc.utc))
    candidate.save()
    reconcile_binding(binding.pk)
    return {'public_source_id':source.pk,'state':'published'}


@sqlite_retry
@transaction.atomic
def record_public_entry(candidate_id,entry_id,*,expected_version,evidence):
    PublicFeedCandidate.objects.filter(pk=candidate_id).update(updated_at=F('updated_at'))
    candidate=PublicFeedCandidate.objects.select_related('binding','public_source__publication').filter(pk=candidate_id).first()
    if (not candidate or candidate.version!=expected_version or candidate.state!='published'
            or not candidate.public_source_id or not candidate.scope_since): return False
    entry=EngineEntryMap.objects.select_related('news').filter(pk=entry_id,binding=candidate.binding,
        disposition='linked',news__isnull=False).first()
    if not entry or entry.source_url!=entry.news.url: return False
    published=parse_datetime(evidence.get('published_at','')) if isinstance(evidence.get('published_at'),str) else None
    binding=candidate.binding
    identity=(str(binding.engine_instance_uuid),binding.account_id,binding.engine_feed_id,entry.engine_entry_id,entry.source_url)
    supplied=(evidence.get('engine_instance_uuid'),evidence.get('account_id'),evidence.get('feed_id'),evidence.get('engine_entry_id'),evidence.get('source_url'))
    if (not evidence.get('verified') or identity!=supplied or published is None or timezone.is_naive(published)
            or published<candidate.scope_since or published>timezone.now()+timedelta(minutes=5)
            or evidence.get('summary_hash')!=sha256(entry.news.content.encode()).hexdigest()): return False
    if candidate.public_source.publication.owner!='miniflux' or not SourceFeedLink.objects.filter(
            source=candidate.public_source,binding=binding,enabled=True).exists(): return False
    assert_binding_policy(binding)
    PublicFeedEntry.objects.update_or_create(source=candidate.public_source,entry=entry,
        defaults={'approval_version':candidate.version,'evidence':evidence})
    return True


def dto_evidence(dto,summary,*,published,inferred):
    return {'verified':not inferred,'engine_instance_uuid':str(dto.engine_instance_uuid),'account_id':dto.account_id,
        'feed_id':dto.feed_id,'engine_entry_id':dto.id,'source_url':dto.url,
        'published_at':published.isoformat(),'summary_hash':sha256(summary.encode()).hexdigest()}


def process_approved_candidates(*,limit=25,instance_uuid=None,account_id=None):
    from rest_framework.exceptions import PermissionDenied
    from api.rss.operations import OperationError
    from api.rss.recommendations import candidates
    result={'published':0,'waiting':0}
    rows = PublicFeedCandidate.objects.filter(binding__engine_instance_uuid=instance_uuid,binding__account_id=account_id) if instance_uuid is not None else candidates()
    for candidate in rows.filter(state='approved').order_by('updated_at')[:limit]:
        try:
            state=publish_candidate(candidate.pk,candidate.version)
            result['published' if state.get('state')=='published' else 'waiting']+=1
        except (PermissionDenied,OperationError,RssConflict):
            result['waiting']+=1
        finally:
            # Rotate blocked approvals so one stale authority cannot monopolize a tick.
            rows.filter(pk=candidate.pk,state='approved').update(updated_at=timezone.now())
    return result


def prepare_public_member(*,instance_uuid=None,account_id=None):
    """Main thread selects one stored-engine read; never publisher I/O."""
    from api.rss.recommendations import candidates
    from api.rss.admin_verification import binding_snapshot
    rows = PublicFeedCandidate.objects.filter(binding__engine_instance_uuid=instance_uuid,binding__account_id=account_id).select_related('binding') if instance_uuid is not None else candidates()
    for candidate in rows.filter(state='published',member_sync_complete=False).order_by('updated_at')[:25]:
        entry=EngineEntryMap.objects.filter(binding=candidate.binding,engine_entry_id__gt=candidate.member_cursor,news__isnull=False,
            disposition='linked',news__publish_time__gte=candidate.scope_since).filter(
                Q(news__full_content_provenance___sync_metadata__publish_time_inferred__isnull=True) |
                Q(news__full_content_provenance___sync_metadata__publish_time_inferred=False)).order_by('engine_entry_id').first()
        if entry is None:
            PublicFeedCandidate.objects.filter(pk=candidate.pk,version=candidate.version).update(member_sync_complete=True)
            continue
        # One stored-engine read per tick, round-robin across active candidates.
        rows.filter(pk=candidate.pk,version=candidate.version).update(updated_at=timezone.now())
        return {'candidate_id':str(candidate.pk),'version':candidate.version,'mapping_id':entry.pk,
            'entry_id':entry.engine_entry_id,'cursor':candidate.member_cursor,'binding':binding_snapshot(candidate.binding)}
    return None


def finish_public_member(token,dto,*,reserve):
    from api.rss.admin_verification import binding_snapshot
    from api.rss.content_store import StaleWrite
    from api.rss.sync import _metadata
    with transaction.atomic():
        reserve()
        candidate=PublicFeedCandidate.objects.select_related('binding').get(pk=token['candidate_id'])
        if candidate.version!=token['version'] or candidate.member_cursor!=token['cursor'] or binding_snapshot(candidate.binding)!=token['binding']:
            raise StaleWrite('public_member_authority_changed')
        entry=EngineEntryMap.objects.select_related('news').filter(pk=token['mapping_id'],binding=candidate.binding).first()
        if dto is not None and entry and entry.news_id:
            identity=(str(dto.engine_instance_uuid),dto.account_id,dto.feed_id,dto.id,dto.url)
            expected=(str(candidate.binding.engine_instance_uuid),candidate.binding.account_id,candidate.binding.engine_feed_id,token['entry_id'],entry.source_url)
            if identity!=expected: raise StaleWrite('public_entry_identity_changed')
            try:
                _,summary,_,_,published,inferred=_metadata(dto,dto.url)
                evidence=dto_evidence(dto,summary,published=published,inferred=inferred)
                record_public_entry(candidate.pk,entry.pk,expected_version=candidate.version,evidence=evidence)
            except (ValueError,TypeError):
                pass  # Invalid or changed publisher metadata grants no membership.
        PublicFeedCandidate.objects.filter(pk=candidate.pk,version=token['version'],member_cursor=token['cursor']).update(member_cursor=token['entry_id'])
