"""Transition-only legacy tokens: capture before source I/O, never after results."""
from contextlib import contextmanager
from dataclasses import asdict, dataclass
import hashlib
import json

from django.db import transaction
from django.db.models import F

from api.models import News, Source, SourceConfig, SourcePublication
from api.rss.content_store import StaleWrite, WriteToken, capture_write_token
from api.services.source_policy import policy_for_key, policy_for_name


@dataclass(frozen=True)
class LegacySourceToken:
    source_id: int
    source_key: str
    epoch: int
    policy_version: int
    registry_hash: str
    config_version: int | None
    articles: tuple[WriteToken, ...] = ()

    def article(self, news_id):
        return next((token for token in self.articles if token.news_id == news_id), None)


def _policy_hash(policy):
    return hashlib.sha256(json.dumps(asdict(policy), sort_keys=True).encode()).hexdigest()


def initialize_legacy_source(source_key, *, source=None):
    """Explicit legacy entry-point initialization, never a public-read fallback."""
    policy = policy_for_key(source_key)
    if not policy or policy.unsupported_reason:
        raise StaleWrite('legacy_policy_unavailable')
    config = SourceConfig.objects.filter(source_key=source_key).first()
    if config and (config.status not in {'approved', 'enabled'} or not config.approval_is_current):
        raise StaleWrite('legacy_policy_unavailable')
    if config and config.source_id:
        source = Source.objects.get(pk=config.source_id)
    elif source is None:
        source, _ = Source.objects.get_or_create(name=policy.name, defaults={
            'url': policy.feed_url or 'https://' + policy.domains[0],
            'region': policy.region, 'language': policy.language,
        })
    if source.name != policy.name and (not config or config.source_id != source.pk):
        raise StaleWrite('legacy_source_identity_mismatch')
    publication, _ = SourcePublication.objects.get_or_create(source=source, defaults={
        'owner': 'legacy', 'publication': 'personal', 'reading_policy': config.reading_policy if config else policy.reading_policy,
        'display_name': source.name,
    })
    if publication.owner != 'legacy':
        raise StaleWrite('source_not_legacy')
    return source, publication, policy, config


def capture_source_token(source_key, *, include_articles=True):
    """One compact known-article snapshot per crawl, before its first request.

    Rows first discovered later in that run can be associated but are never
    retrospectively given a pre-request ownership token.
    """
    with transaction.atomic():
        source, publication, policy, config = initialize_legacy_source(source_key)
        # First write serializes initialization/claim with ownership handovers.
        SourcePublication.objects.filter(source=source).update(epoch=F('epoch'))
        publication.refresh_from_db()
        if publication.owner != 'legacy':
            raise StaleWrite('source_not_legacy')
        articles = []
        if include_articles:
            # Explicit compatibility claim applies only to this source's primary,
            # still unclaimed articles. It does not steal another owner's body.
            News.objects.filter(source=source, body_owner_source__isnull=True,
                                body_owner_binding__isnull=True).update(body_owner_source=source)
            rows = News.objects.filter(body_owner_source=source, body_owner_binding__isnull=True).only(
                'id', 'url', 'full_content_revision', 'body_owner_version', 'body_owner_source_id', 'body_owner_binding_id')
            for news in rows.iterator(chunk_size=500):
                articles.append(WriteToken(news_id=news.pk, news_url=news.url,
                    expected_revision=news.full_content_revision, source_id=source.pk, source_owner='legacy',
                    source_epoch=publication.epoch, source_policy_version=publication.policy_version,
                    body_owner_version=news.body_owner_version, body_owner_source_id=source.pk, body_owner_binding_id=None))
        return LegacySourceToken(source.pk, source_key, publication.epoch, publication.policy_version,
            _policy_hash(policy), config.config_version if config else None, tuple(articles))


def validate_source_token(token):
    if not isinstance(token, LegacySourceToken):
        raise StaleWrite('legacy_token_missing')
    publication = SourcePublication.objects.filter(source_id=token.source_id).first()
    policy = policy_for_key(token.source_key)
    config = SourceConfig.objects.filter(source_key=token.source_key).first()
    if (not publication or publication.owner != 'legacy' or publication.epoch != token.epoch
            or publication.policy_version != token.policy_version):
        raise StaleWrite('legacy_source_changed')
    if (not policy or policy.unsupported_reason or _policy_hash(policy) != token.registry_hash
            or (config.config_version if config else None) != token.config_version
            or (config is not None and (config.status not in {'approved', 'enabled'} or not config.approval_is_current))):
        raise StaleWrite('legacy_policy_changed')
    return publication


@contextmanager
def fenced_source(token):
    if not isinstance(token, LegacySourceToken):
        raise StaleWrite('legacy_token_missing')
    with transaction.atomic():
        if not SourcePublication.objects.filter(source_id=token.source_id).update(epoch=F('epoch')):
            raise StaleWrite('legacy_source_missing')
        validate_source_token(token)
        yield Source.objects.get(pk=token.source_id)


def capture_legacy_article(news, *, initialize=False):
    """Full-content/manual acquisition captures one article before its HTTP call."""
    if initialize:
        policy = policy_for_name(news.source.name)
        if policy is None:
            config = SourceConfig.objects.filter(source_id=news.source_id).first()
            policy = policy_for_key(config.source_key) if config else None
        if policy is None:
            raise StaleWrite('legacy_policy_unavailable')
        with transaction.atomic():
            source, _, _, _ = initialize_legacy_source(policy.key, source=news.source)
            SourcePublication.objects.filter(source=source).update(epoch=F('epoch'))
            if not SourcePublication.objects.filter(source=source, owner='legacy').exists():
                raise StaleWrite('source_not_legacy')
            News.objects.filter(pk=news.pk, source=source, body_owner_source__isnull=True,
                                body_owner_binding__isnull=True).update(body_owner_source=source)
    return capture_write_token(news_id=news.pk, source_id=news.source_id)


def capture_article_source_token(news):
    config = SourceConfig.objects.filter(source_id=news.source_id).first()
    policy = policy_for_key(config.source_key) if config else policy_for_name(news.source.name)
    if policy is None:
        raise StaleWrite('legacy_policy_unavailable')
    return capture_source_token(policy.key, include_articles=False)


def legacy_body_policy_allows(news, *, html=False):
    publication = SourcePublication.objects.filter(source_id=news.source_id).first()
    config = SourceConfig.objects.filter(source_id=news.source_id).first()
    denied = {'summary_only', 'rss_summary_only'}
    if html:
        denied |= {'public_feed', 'public_rss'}
    return publication is not None and publication.reading_policy not in denied and (
        config is None or config.reading_policy not in denied)


def legacy_news_queryset(queryset):
    return queryset.filter(source__publication__owner='legacy', body_owner_source_id=F('source_id'), body_owner_binding__isnull=True)


def legacy_translation_update(news, updates, *, title, content):
    """Pipeline legacy translation cannot publish onto changed source strings."""
    from api.rss.legacy_translation import exact_hash
    from api.models import LegacyTranslationSnapshot
    with transaction.atomic():
        News.objects.filter(pk=news.pk).update(full_content_revision=F('full_content_revision'))
        current = News.objects.get(pk=news.pk)
        unchanged = (current.title, current.content) == (title, content)
        for field, original in [('title', title), ('content', content)]:
            translated = updates.get(field + '_zh')
            if not translated:
                continue
            previous = getattr(current, field + '_zh')
            if unchanged and previous and previous != translated:
                LegacyTranslationSnapshot.objects.get_or_create(news=current, field=field,
                    source_hash=exact_hash(original), translation_hash=exact_hash(previous),
                    defaults={'source_text': original, 'translated_text': previous, 'origin': 'legacy'})
            # This result was acquired for the exact captured source strings.
            # It may be a usable current translation or a late historical one.
            LegacyTranslationSnapshot.objects.update_or_create(news=current, field=field,
                source_hash=exact_hash(original), translation_hash=exact_hash(translated),
                defaults={'source_text': original, 'translated_text': translated, 'origin': 'legacy-bound'})
        if unchanged:
            return News.objects.filter(pk=news.pk).update(**updates) == 1
        return False


def legacy_admin_guard(source_id, news_ids=()):
    """Serializable read-only scope guard for explicit pre-reviewed repair plans."""
    publication = SourcePublication.objects.filter(source_id=source_id, owner='legacy').first()
    if publication is None:
        raise StaleWrite('admin_repair_requires_legacy_source')
    rows = list(News.objects.filter(pk__in=news_ids).order_by('pk'))
    if len(rows) != len(set(news_ids)) or any(
            row.body_owner_source_id != source_id or row.body_owner_binding_id is not None for row in rows):
        raise StaleWrite('admin_repair_not_body_owner')
    config = SourceConfig.objects.filter(source_id=source_id).first()
    policy = policy_for_key(config.source_key) if config else policy_for_name(publication.source.name)
    return {'source_id': source_id, 'source_epoch': publication.epoch, 'source_policy_version': publication.policy_version,
            'config_version': config.config_version if config else None, 'registry_hash': _policy_hash(policy) if policy else None,
            'articles': [{'news_id': row.pk, 'body_owner_version': row.body_owner_version} for row in rows]}


def assert_legacy_admin_guard(guard):
    if not isinstance(guard, dict):
        raise StaleWrite('admin_repair_token_missing')
    if legacy_admin_guard(guard['source_id'], [row['news_id'] for row in guard['articles']]) != guard:
        raise StaleWrite('admin_repair_token_stale')
