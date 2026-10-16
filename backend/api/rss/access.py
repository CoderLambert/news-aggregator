"""Current SQL article ACL and body-origin checks for stored content only.

Publication is independent of collection state. Membership never grants another
binding's body rights; favorites and user-selected scopes never grant access.
No cross-request permission cache or network side effect belongs in this module.
"""
from dataclasses import dataclass
from hashlib import sha256

from django.db.models import Case, CharField, Exists, F, OuterRef, Q, Value, When
from django.db.models.functions import Cast, Replace, Trim
from django.http import Http404

from api.models import News, Source, NewsSourceItem
from api.rss.models import EngineEntryMap, SourceFeedLink
from api.services.source_policy import POLICIES

BODY_POLICIES = ('standard', 'public_rss', 'public_feed', 'official_html', 'regulatory_data')
ALL_ENTRIES = {'version': 1, 'mode': 'all'}


def _active_user(user):
    return bool(user and user.is_authenticated and user.is_active)


def authorized_sources(user, queryset=None, *, body=False):
    sources = Source.objects.all() if queryset is None else queryset
    grant = Q(publication__publication='public')
    if _active_user(user):
        grant |= Q(publication__publication='personal', channel_subscriptions__user_id=user.pk)
    sources = sources.filter(grant)
    if body:
        sources = sources.filter(publication__reading_policy__in=BODY_POLICIES)
        from api.services.body_access import can_view_article_body
        if not can_view_article_body(user):
            sources = sources.exclude(name__in=[p.name for p in POLICIES.values() if p.reading_policy == 'rss_summary_only'])
    return sources.distinct()


def _legacy_keys(sources):
    return sources.annotate(_policy_key=Case(
        *[When(name=p.name, then=Value(p.key)) for p in POLICIES.values()],
        default=Value(None), output_field=CharField(),
    )).values('_policy_key')


def news_in_sources(queryset, sources):
    """Historical membership; enabled/owner/connection state are fetch controls.

    V1 all-entry manifests are executable here. Unknown metadata filters fail
    closed until their reviewed SQL membership implementation is supplied.
    """
    legacy = NewsSourceItem.objects.filter(news_id=OuterRef('pk'), source_key__in=_legacy_keys(sources))
    engine = EngineEntryMap.objects.filter(news_id=OuterRef('pk'), disposition='linked',
        binding__source_links__source_id__in=sources.values('pk'),
        binding__source_links__association_policy=ALL_ENTRIES)
    return queryset.alias(_rss_legacy_member=Exists(legacy), _rss_engine_member=Exists(engine)).filter(
        Q(source_id__in=sources.values('pk')) | Q(_rss_legacy_member=True) | Q(_rss_engine_member=True))


def authorized_news(user, queryset=None):
    return news_in_sources(News.objects.all() if queryset is None else queryset, authorized_sources(user))


def article_sources(user, news):
    """Authorized channels only; callers must not expose a private primary source."""
    keys = set(news.source_items.values_list('source_key', flat=True))
    legacy_names = [p.name for p in POLICIES.values() if p.key in keys]
    links = SourceFeedLink.objects.filter(binding__entry_maps__news_id=news.pk,
        binding__entry_maps__disposition='linked', association_policy=ALL_ENTRIES).values('source_id')
    return authorized_sources(user).filter(Q(pk=news.source_id) | Q(name__in=legacy_names) | Q(pk__in=links)).order_by('pk')


def body_authorized_news(user, queryset=None):
    """SQL counterpart of stored-body readability, suitable before text search."""
    qs = authorized_news(user, queryset)
    body_sources = authorized_sources(user, body=True)
    links = SourceFeedLink.objects.filter(binding_id=OuterRef('body_owner_binding_id'),
        source_id__in=body_sources.values('pk'), association_policy=ALL_ENTRIES)
    # A current body owner does not erase the origin of previously accepted bytes.
    origin_link = links.filter(source_id=OuterRef('full_content_provenance__source_id'))
    origin_entry = EngineEntryMap.objects.filter(news_id=OuterRef('pk'),
        binding_id=OuterRef('body_owner_binding_id'),
        engine_entry_id=OuterRef('full_content_provenance__engine_entry_id'), disposition='linked')
    qs = qs.alias(_rss_body_link=Exists(links), _rss_origin_link=Exists(origin_link),
                  _rss_origin_entry=Exists(origin_entry),
                  _rss_origin_binding=Replace(Cast('full_content_provenance__binding_id', CharField()), Value('-'), Value('')),
                  _rss_owner_binding=Replace(Cast('body_owner_binding_id', CharField()), Value('-'), Value('')),
                  _rss_origin_instance=Replace(Cast('full_content_provenance__engine_instance_uuid', CharField()), Value('-'), Value('')),
                  _rss_binding_instance=Replace(Cast('body_owner_binding__engine_instance_uuid', CharField()), Value('-'), Value('')),
                  _rss_body_text=Trim('full_content'))
    engine_origin = Q(full_content_provenance__owner='miniflux', _rss_origin_link=True,
                      _rss_origin_entry=True, _rss_origin_binding=F('_rss_owner_binding'),
                      _rss_origin_instance=F('_rss_binding_instance'),
                      full_content_provenance__account_id=F('body_owner_binding__account_id'),
                      full_content_provenance__engine_feed_id=F('body_owner_binding__engine_feed_id'))
    # JSON missing owner needs an explicit isnull alternative (SQL NOT drops NULL).
    legacy_origin = Q(full_content_provenance__owner__isnull=True) | ~Q(full_content_provenance__owner='miniflux')
    legacy_owner = Q(body_owner_source_id__in=body_sources.values('pk')) | Q(
        body_owner_binding__isnull=False, _rss_body_link=True, source_id__in=body_sources.values('pk'))
    qs = qs.filter(engine_origin | (legacy_origin & legacy_owner)).filter(
        full_content_state__in=('legacy', 'complete', 'available')).exclude(_rss_body_text='')
    # Retained legacy provenance can name a different publisher from the primary
    # channel. Require its current grant too; a privileged fetch cannot bypass ACL.
    qs = qs.alias(_rss_legacy_origin_name=Case(
        *[When(full_content_provenance__source_key=p.key, then=Value(p.name)) for p in POLICIES.values()],
        default=Value(None), output_field=CharField(),
    )).alias(_rss_legacy_origin_grant=Exists(body_sources.filter(name=OuterRef('_rss_legacy_origin_name'))))
    unrecorded = Q(full_content_provenance__source_key__isnull=True) | Q(full_content_provenance__source_key='')
    qs = qs.filter(Q(full_content_provenance__owner='miniflux') | unrecorded | Q(_rss_legacy_origin_grant=True))
    return qs


@dataclass(frozen=True)
class AccessContext:
    user_id: int | None
    source_ids: tuple[int, ...]
    scope: str
    policy_versions: dict[str, int]


@dataclass(frozen=True)
class StoredArticle:
    news_id: int
    title: str
    url: str
    summary: str
    markdown: str
    scope: str
    revision: int
    canonical_hash: str
    content_kind: str
    completeness: str
    provenance: dict
    policy_versions: dict[str, int]
    body_owner: str | None
    access: AccessContext


def get_stored_article(user, news_id):
    """Always re-read grants and content. Anonymous/inactive users get public only."""
    try:
        news = authorized_news(user).get(pk=news_id)
    except (News.DoesNotExist, ValueError, TypeError):
        raise Http404 from None
    sources = list(article_sources(user, news).select_related('publication'))
    body = body_authorized_news(user, News.objects.filter(pk=news.pk)).exists()
    scope = 'full' if body and news.full_content_completeness != 'summary' else 'summary'
    markdown = news.full_content if scope == 'full' else news.content
    versions = {str(s.pk): s.publication.policy_version for s in sources}
    if body and news.body_owner_binding_id:
        versions['binding:' + str(news.body_owner_binding_id)] = news.body_owner_binding.policy_version
    context = AccessContext(user.pk if _active_user(user) else None, tuple(s.pk for s in sources), scope, versions)
    # Provenance is server-side evidence; public serializers expose no arbitrary JSON.
    return StoredArticle(news.pk, news.title, news.url, news.content, markdown, scope,
        news.full_content_revision, sha256(markdown.encode('utf-8')).hexdigest(), news.content_kind,
        news.full_content_completeness if scope == 'full' else 'summary',
        dict(news.full_content_provenance or {}) if scope == 'full' else {}, versions,
        ('miniflux' if news.body_owner_binding_id else 'legacy') if scope == 'full' else None, context)
