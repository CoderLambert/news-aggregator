"""Bounded two-read synchronization. Network results never authorize their own write."""
from dataclasses import dataclass
from datetime import timezone as datetime_timezone
from hashlib import md5

import nh3
from bs4 import BeautifulSoup
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from api.models import (Category, EngineEntryMap, FeedBinding, FeedRejection,
                        IdentityConflict, News, SourceFeedLink, SourceConfig)
from api.rss.content import ConversionError, convert_html, _public_web_url
from api.rss.content_store import CommitResult, StaleWrite, WriteToken, commit_body
from api.rss.legacy_translation import archive_changed_translations, exact_hash
from api.services.article_identity import InvalidIdentity, normalize_article_url

ALL = {'version': 1, 'mode': 'all'}
SUMMARY_VERSION = 'rss-summary-v1:500'


def _binding_snapshot(binding):
    if binding is None:
        return None
    links = list(SourceFeedLink.objects.filter(binding=binding).order_by('source_id').values_list(
        'source_id', 'enabled', 'association_policy', 'source__publication__owner',
        'source__publication__epoch', 'source__publication__policy_version',
        'source__publication__reading_policy', 'source__publication__publication',
        # The source is used to derive catalog/category/content policy below.
        # Do not let a later rename, URL change or region edit silently refresh
        # the authority captured before the second engine GET.
        'source__name', 'source__url', 'source__region'))
    configs = list(SourceConfig.objects.filter(source_id__in=[x[0] for x in links]).order_by('source_id').values_list(
        'source_id', 'config_version', 'approved_config_version', 'status', 'category_id', 'content_kind'))
    return (binding.pk, binding.policy_version, binding.applied_policy_version,
            binding.desired_enabled, binding.connection_state, binding.desired_mode, links, configs,
            str(binding.engine_instance_uuid), binding.account_id, binding.engine_feed_id)


def _news_snapshot(news):
    return None if news is None else (news.pk, news.url, news.full_content_revision,
        news.body_owner_version, news.body_owner_source_id, news.body_owner_binding_id,
        news.title, news.content, news.publish_time, news.author,
        # News.source/category are stable article ownership and membership,
        # even when a local edit forgets to increment full_content_revision.
        news.source_id, news.category_id)


def _map_snapshot(entry):
    return None if entry is None else (entry.pk, entry.news_id, entry.source_url, entry.disposition)


@dataclass(frozen=True)
class EntryFence:
    identity: tuple
    url: str
    binding: tuple | None
    mapping: tuple | None
    news: tuple | None
    invalid_url: bool = False


def prepare_page(entries, *, instance_uuid, account_id):
    """Read only; capture AFTER identity discovery and BEFORE candidate GET."""
    fences = {}
    for dto in entries:
        identity = (str(dto.engine_instance_uuid), dto.account_id, dto.feed_id, dto.id)
        if identity[:2] != (str(instance_uuid), account_id):
            raise StaleWrite('engine_identity_mismatch')
        try:
            url = normalize_article_url(dto.url)
            invalid = False
        except InvalidIdentity:
            url, invalid = dto.url, True
        binding = FeedBinding.objects.filter(engine_instance_uuid=instance_uuid,
            account_id=account_id, engine_feed_id=dto.feed_id).first()
        mapping = EngineEntryMap.objects.filter(binding=binding, engine_entry_id=dto.id).first() if binding else None
        news = News.objects.filter(pk=mapping.news_id).first() if mapping and mapping.news_id else (
            News.objects.filter(url=url).first() if not invalid else None)
        fences[dto.id] = EntryFence(identity, url, _binding_snapshot(binding),
                                  _map_snapshot(mapping), _news_snapshot(news), invalid)
    return fences


def _issue(dto, reason, *, conflict=None):
    model = IdentityConflict if conflict is not None else FeedRejection
    defaults = {'last_seen': timezone.now(), 'safe_metadata': {'summary_version': SUMMARY_VERSION}}
    if conflict is not None:
        defaults['existing_news_id'] = conflict.pk
    model.objects.update_or_create(engine_instance_uuid=dto.engine_instance_uuid, account_id=dto.account_id,
        engine_feed_id=dto.feed_id, engine_entry_id=dto.id, reason=reason,
        content_hash=exact_hash(dto.content), defaults=defaults)
    return CommitResult('conflict' if conflict is not None else 'rejected', reason)


def _date(value):
    try:
        result = parse_datetime(value or '')
        return result.replace(tzinfo=datetime_timezone.utc) if result and timezone.is_naive(result) else result
    except (ValueError, TypeError, OverflowError):
        return None


def _metadata(dto, url):
    if not dto.title.strip() or len(dto.title) > 500:
        raise ValueError('invalid_title')
    if len(dto.author) > 100:
        raise ValueError('author_too_long')
    published, created = _date(dto.published_at), _date(dto.created_at)
    if not (published or created):
        raise ValueError('invalid_publication_time')
    # Bound the raw input before parsing it a second time for the list summary.
    converted = convert_html(dto.content, base_url=url)
    cleaned = nh3.clean(dto.content, tags={'p', 'br', 'div', 'img'},
        attributes={'img': {'src'}}, clean_content_tags={'script', 'style', 'iframe', 'object', 'embed', 'svg', 'math', 'template', 'noscript'})
    soup = BeautifulSoup(cleaned, 'html.parser')
    summary = ' '.join(soup.get_text(' ', strip=True).split())[:500]
    cover = next((safe for tag in soup.find_all('img')
        if (safe := _public_web_url(tag.get('src', ''), url, image=True)) and len(safe) <= 500), '')
    comments = ''
    if dto.comments_url:
        try:
            comments = normalize_article_url(dto.comments_url, max_length=1024, require_article=False)
        except InvalidIdentity:
            raise ValueError('invalid_comments_url') from None
    return converted, summary, cover, comments, published or created, published is None


def commit_entry(dto, fence, *, reserve):
    """One short atomic unit; reserve validates the durable sync/operation lease.

    Caller must retry the whole unit on SQLite busy. Deterministic bad content
    gets a durable issue. Stale fences raise, rolling back membership/metadata.
    """
    identity = (str(dto.engine_instance_uuid), dto.account_id, dto.feed_id, dto.id)
    try:
        url = normalize_article_url(dto.url)
    except InvalidIdentity:
        url = dto.url
    if identity != fence.identity or url != fence.url:
        raise StaleWrite('page_identity_changed')
    try:
        metadata = _metadata(dto, url) if not fence.invalid_url else None
        invalid = 'invalid_article_url' if fence.invalid_url else ''
    except (ValueError, ConversionError) as error:
        metadata, invalid = None, getattr(error, 'code', str(error))
    with transaction.atomic():
        reserve()  # First statement acquires the SQLite writer reservation.
        binding = FeedBinding.objects.filter(pk=fence.binding[0]).first() if fence.binding else None
        if _binding_snapshot(binding) != fence.binding:
            raise StaleWrite('binding_or_source_changed')
        if binding is None:
            return _issue(dto, 'unmapped_feed')
        if not binding.desired_enabled or binding.connection_state != 'ready' or binding.policy_version != binding.applied_policy_version:
            return _issue(dto, 'binding_unready')
        links = fence.binding[6]
        active = [link for link in links if link[1] and link[3] == 'miniflux']
        if not active:
            return _issue(dto, 'source_unready')
        # Membership currently derives from the binding's links. Any unsupported
        # filter blocks the shared feed, rather than accidentally granting all.
        if any(link[2] != ALL for link in links):
            return _issue(dto, 'unsupported_association_policy')
        if any(link[6] not in {'standard', 'public_rss', 'public_feed', 'official_html', 'regulatory_data', 'summary_only', 'rss_summary_only'} for link in active):
            return _issue(dto, 'unsupported_reading_policy')
        if any(config[3] not in {'approved', 'enabled'} or config[1] != config[2]
               for config in fence.binding[7] if config[0] in {link[0] for link in active}):
            return _issue(dto, 'source_config_unapproved')
        if invalid:
            return _issue(dto, invalid)
        mapping = EngineEntryMap.objects.filter(binding=binding, engine_entry_id=dto.id).first()
        if _map_snapshot(mapping) != fence.mapping:
            raise StaleWrite('entry_mapping_changed')
        news = News.objects.filter(pk=mapping.news_id).first() if mapping and mapping.news_id else News.objects.filter(url=url).first()
        if _news_snapshot(news) != fence.news:
            raise StaleWrite('article_changed_after_capture')
        if mapping and mapping.source_url and mapping.source_url != url:
            return _issue(dto, 'entry_url_changed', conflict=news)
        if news and news.url != url:
            return _issue(dto, 'article_url_conflict', conflict=news)
        source = active[0]
        converted, summary, cover, comments, published, inferred = metadata
        if news is None:
            config = SourceConfig.objects.filter(source_id=source[0]).first()
            from api.services.source_policy import policy_for_name
            from api.models import Source
            policy = policy_for_name(Source.objects.get(pk=source[0]).name)
            category = config.category if config else (
                Category.objects.filter(name=policy.default_category).first() if policy else None)
            category = category or Category.objects.filter(name='科技').first() or Category.objects.order_by('pk').first()
            if category is None:
                return _issue(dto, 'source_category_missing')
            news = News.objects.create(url=url, source_id=source[0], category=category,
                title=dto.title, content=summary, author=dto.author, publish_time=published,
                body_owner_binding=binding, full_content_provenance={'_sync_metadata': {
                    'publish_time_inferred': inferred, 'summary_version': SUMMARY_VERSION}})
        elif news.body_owner_binding_id != binding.pk:
            # Associating a URL expands access. Require equal source audience
            # policy, including personal subscribers, before adding membership.
            from api.models import SourcePublication, ChannelSubscription
            previous = SourcePublication.objects.filter(source_id=news.source_id).first()
            if previous is None or any((link[7], link[6]) != (previous.publication, previous.reading_policy) for link in active):
                return _issue(dto, 'incompatible_url_policy', conflict=news)
            if previous.publication == 'personal':
                audience = set(ChannelSubscription.objects.filter(source_id=news.source_id).values_list('user_id', flat=True))
                if any(set(ChannelSubscription.objects.filter(source_id=link[0]).values_list('user_id', flat=True)) != audience for link in active):
                    return _issue(dto, 'incompatible_url_audience', conflict=news)
        if mapping is None:
            mapping = EngineEntryMap.objects.create(binding=binding, engine_entry_id=dto.id,
                news=news, source_url=url, disposition='linked')
        else:
            EngineEntryMap.objects.filter(pk=mapping.pk).update(news=news, source_url=url, disposition='linked')
        EngineEntryMap.objects.filter(pk=mapping.pk).update(comments_url=comments, last_seen=timezone.now())
        if news.body_owner_binding_id != binding.pk:
            return CommitResult('unchanged', 'association_only', revision=news.full_content_revision)
        token = WriteToken(news.pk, news.url, news.full_content_revision, source[0], 'miniflux',
            source[4], source[5], news.body_owner_version, None, binding.pk, mapping.pk,
            binding.engine_instance_uuid, binding.account_id, binding.engine_feed_id, dto.id, binding.policy_version)
        updates = {'title': dto.title}
        if summary:
            updates['content'] = summary
        if dto.author:
            updates['author'] = dto.author
        if cover:
            updates['cover_image'] = cover
        sync_meta = dict(news.full_content_provenance.get('_sync_metadata', {}))
        if not inferred or sync_meta.get('publish_time_inferred') is True:
            updates['publish_time'] = published
            sync_meta['publish_time_inferred'] = inferred
        sync_meta['summary_version'] = SUMMARY_VERSION
        if news.title != dto.title or news.title_hash is None:
            updates['title_hash'] = int(md5(dto.title.lower().strip().encode()).hexdigest()[:8], 16)
        updates.update(archive_changed_translations(news, updates))
        News.objects.filter(pk=news.pk).update(**updates)
        config = SourceConfig.objects.filter(source_id=source[0]).first()
        from api.services.source_policy import policy_for_name
        from api.models import Source
        policy = policy_for_name(Source.objects.get(pk=source[0]).name)
        from api.rss.feed_policy import known_feed_content_kind
        kind = config.content_kind if config else (policy.content_kind if policy else
            known_feed_content_kind(binding.canonical_feed_url))
        result = commit_body(token, converted, content_kind=kind,
            completeness='summary' if source[6] in {'summary_only', 'rss_summary_only'} else 'unknown')
        if result.status == 'stale':
            raise StaleWrite(result.reason)
        current = News.objects.get(pk=news.pk)
        provenance = {**current.full_content_provenance, '_sync_metadata': sync_meta}
        News.objects.filter(pk=news.pk).update(full_content_provenance=provenance)
        if result.status == 'rejected':
            _issue(dto, result.reason)
        return result


def sync_metadata(news):
    """Read C04 provenance without granting body access or inferring old dates."""
    value = (news.full_content_provenance or {}).get('_sync_metadata', {})
    return {'publish_time_inferred': value.get('publish_time_inferred') is True,
            'summary_version': value.get('summary_version')}


def prepare_refetch(operation):
    from api.rss.engine import EntryDTO
    entry, binding = operation.entry, operation.binding
    if entry is None or binding is None:
        raise StaleWrite('refetch_identity_missing')
    dto = EntryDTO(str(binding.engine_instance_uuid), binding.account_id,
        binding.engine_feed_id, entry.engine_entry_id, '', entry.source_url, None, '', '', None, None)
    fence = prepare_page([dto], instance_uuid=binding.engine_instance_uuid, account_id=binding.account_id)[dto.id]
    return (operation.pk, operation.request_hash, operation.lease_epoch,
            operation.intent_version, operation.safe_input.get('fence')), fence


def commit_refetch(dto, operation_token, fence, *, reserve):
    from api.models import FeedOperation
    from api.rss.operations import OperationError, acknowledge_refetch, refetch_fence
    operation_id, request_hash, epoch, version, original = operation_token
    with transaction.atomic():
        reserve()
        operation = FeedOperation.objects.select_related('entry', 'binding').filter(pk=operation_id,
            request_hash=request_hash, lease_epoch=epoch, kind='refetch_entry', state='succeeded',
            safe_result__pending_sync=True).first()
        if operation is None:
            raise StaleWrite('refetch_operation_changed')
        try:
            if (operation.safe_input.get('fence') != original or operation.intent_version != version
                    or operation.binding.policy_version != version or not isinstance(original, dict)
                    or refetch_fence(operation.entry, original['source_id'], operation.actor_id) != original):
                raise StaleWrite('refetch_fence_changed')
            result = commit_entry(dto, fence, reserve=reserve)
        except (OperationError, StaleWrite, KeyError) as error:
            result = CommitResult('stale', getattr(error, 'reason', 'refetch_fence_changed'))
        if not acknowledge_refetch(operation.pk, request_hash, sync_status=result.status,
                reason=result.reason, revision=result.revision):
            raise StaleWrite('refetch_operation_changed')
        return result


def record_duplicate(dto, *, reserve):
    with transaction.atomic():
        reserve()
        return _issue(dto, 'duplicate_url_in_page')


def reject_missing_refetch(operation_token, *, reserve):
    """A confirmed engine 404 is terminal; outages leave the handoff pending."""
    from api.models import FeedOperation
    from api.rss.operations import acknowledge_refetch
    operation_id, request_hash, epoch, version, original = operation_token
    with transaction.atomic():
        reserve()
        if not FeedOperation.objects.filter(pk=operation_id, request_hash=request_hash,
                lease_epoch=epoch, intent_version=version, safe_input__fence=original,
                state='succeeded', safe_result__pending_sync=True).exists():
            raise StaleWrite('refetch_operation_changed')
        return acknowledge_refetch(operation_id, request_hash, sync_status='rejected', reason='engine_entry_missing')
