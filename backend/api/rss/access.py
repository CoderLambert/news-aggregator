"""Current SQL article ACL and body-origin checks for stored content only.

Publication is independent of collection state. Membership never grants another
binding's body rights; favorites and user-selected scopes never grant access.
No cross-request permission cache or network side effect belongs in this module.
"""
from dataclasses import dataclass
from hashlib import sha256

from django.db.models import Case, CharField, Exists, F, OuterRef, Q, Value, When
from django.db.models.functions import Cast, Replace
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
    from api.services.article_body_state import trimmed_text_expression
    qs = authorized_news(user, queryset)
    body_sources = authorized_sources(user, body=True)
    links = SourceFeedLink.objects.filter(binding_id=OuterRef('body_owner_binding_id'),
        source_id__in=body_sources.values('pk'), association_policy=ALL_ENTRIES)
    # A current body owner does not erase the origin of previously accepted bytes.
    origin_link = links.filter(source_id=OuterRef('full_content_provenance__source_id'))
    origin_entry = EngineEntryMap.objects.filter(news_id=OuterRef('pk'),
        source_url=OuterRef('url'),
        binding_id=OuterRef('body_owner_binding_id'),
        engine_entry_id=OuterRef('full_content_provenance__engine_entry_id'), disposition='linked')
    qs = qs.alias(_rss_body_link=Exists(links), _rss_origin_link=Exists(origin_link),
                  _rss_origin_entry=Exists(origin_entry),
                  _rss_origin_binding=Replace(Cast('full_content_provenance__binding_id', CharField()), Value('-'), Value('')),
                  _rss_owner_binding=Replace(Cast('body_owner_binding_id', CharField()), Value('-'), Value('')),
                  _rss_origin_instance=Replace(Cast('full_content_provenance__engine_instance_uuid', CharField()), Value('-'), Value('')),
                  _rss_binding_instance=Replace(Cast('body_owner_binding__engine_instance_uuid', CharField()), Value('-'), Value('')),
                  _rss_body_text=trimmed_text_expression('full_content'))
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
        full_content_state__in=('legacy', 'complete', 'available')).exclude(_rss_body_text='').exclude(full_content_completeness='summary')
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
    completeness: str = 'unknown'
    body_owner: str | None = None


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


def _snapshot(user, news_id, *, include_body):
    try:
        body_grant = body_authorized_news(user, News.objects.filter(pk=OuterRef('pk')))
        query = authorized_news(user).annotate(_rss_body_grant=Exists(body_grant)).defer('full_content_zh')
        if not include_body:
            query = query.defer('full_content', 'full_content_provenance')
        # Body grant and bytes are selected in the same database snapshot.
        news = query.get(pk=news_id)
    except (News.DoesNotExist, ValueError, TypeError):
        raise Http404 from None
    sources = list(article_sources(user, news).select_related('publication'))
    if not sources:
        raise Http404
    scope = 'full' if news._rss_body_grant else 'summary'
    versions = {str(source.pk): source.publication.policy_version for source in sources}
    if news._rss_body_grant and news.body_owner_binding_id:
        versions['binding:' + str(news.body_owner_binding_id)] = news.body_owner_binding.policy_version
    context = AccessContext(user.pk if _active_user(user) else None, tuple(source.pk for source in sources), scope, versions,
        news.full_content_completeness if scope == 'full' else 'summary',
        ('miniflux' if news.body_owner_binding_id else 'legacy') if scope == 'full' else None)
    return news, context


def get_article_access(user, news_id):
    """Preview grant/metadata without loading full body or provenance into Python."""
    return _snapshot(user, news_id, include_body=False)[1]


def get_stored_article(user, news_id):
    """Always re-read grants and bytes together. No network or permission cache."""
    news, context = _snapshot(user, news_id, include_body=True)
    markdown = news.full_content if context.scope == 'full' else news.content
    # Provenance is server-side evidence; public serializers expose no arbitrary JSON.
    return StoredArticle(news.pk, news.title, news.url, news.content, markdown, context.scope,
        news.full_content_revision, sha256(markdown.encode('utf-8')).hexdigest(), news.content_kind,
        context.completeness, dict(news.full_content_provenance or {}) if context.scope == 'full' else {},
        context.policy_versions, context.body_owner, context)


def annotate_article_access(user, queryset):
    """Select the body grant with page rows; no body transfer to the application."""
    from django.db.models import IntegerField
    return queryset.annotate(
        _rss_publish_time_inferred=F('full_content_provenance___sync_metadata__publish_time_inferred'),
        _rss_body_grant=Exists(body_authorized_news(user, News.objects.filter(pk=OuterRef('pk')))),
        _rss_access_actor=Value(user.pk if _active_user(user) else None, output_field=IntegerField()),
    )


def prepare_article_previews(user, articles):
    """Two bounded batch reads for a page's engine memberships and source grants.

    Returned snapshots belong to one serialization call only. They must never be
    placed in a cross-request cache. Page rows already contain their SQL body grant.
    """
    if not articles:
        return {}
    ids = [article.pk for article in articles]
    actor = user.pk if _active_user(user) else None
    grants = None
    if any(not hasattr(article, '_rss_access_actor') or article._rss_access_actor != actor for article in articles):
        grants = dict(annotate_article_access(user, authorized_news(user).filter(pk__in=ids)).values_list('pk', '_rss_body_grant'))
    engine_sources = {}
    source_ids = {article.source_id for article in articles}
    for news_id, source_id in EngineEntryMap.objects.filter(news_id__in=ids, disposition='linked',
            binding__source_links__association_policy=ALL_ENTRIES).values_list('news_id', 'binding__source_links__source_id'):
        engine_sources.setdefault(news_id, set()).add(source_id)
        source_ids.add(source_id)
    keys_by_news = {article.pk: {item.source_key for item in article.source_items.all()} for article in articles}
    all_keys = set().union(*keys_by_news.values())
    names = [policy.name for policy in POLICIES.values() if policy.key in all_keys]
    sources = list(authorized_sources(user).filter(Q(pk__in=source_ids) | Q(name__in=names)).select_related('publication'))
    policy_keys = {policy.name: policy.key for policy in POLICIES.values()}
    snapshots = {}
    for article in articles:
        visible = [source for source in sources if source.pk == article.source_id
                   or source.pk in engine_sources.get(article.pk, set())
                   or policy_keys.get(source.name) in keys_by_news[article.pk]]
        if not visible or (grants is not None and article.pk not in grants):
            raise Http404
        visible.sort(key=lambda source: source.pk)
        body = grants[article.pk] if grants is not None else article._rss_body_grant
        context = AccessContext(actor, tuple(source.pk for source in visible), 'full' if body else 'summary',
            {str(source.pk): source.publication.policy_version for source in visible},
            article.full_content_completeness if body else 'summary',
            ('miniflux' if article.body_owner_binding_id else 'legacy') if body else None)
        snapshots[article.pk] = (context, visible)
    return snapshots


def with_authorized_source_counts(user, sources):
    """Count authorized members in SQL without a per-source application query."""
    from django.db.models import Count, IntegerField, Subquery
    from django.db.models.functions import Coalesce
    sources = sources.annotate(_rss_count_source_key=Case(
        *[When(name=policy.name, then=Value(policy.key)) for policy in POLICIES.values()],
        default=Value(None), output_field=CharField(),
    ))
    members = authorized_news(user).filter(
        Q(source_id=OuterRef('pk')) | Q(source_items__source_key=OuterRef('_rss_count_source_key')) |
        Q(engine_entries__disposition='linked', engine_entries__binding__source_links__source_id=OuterRef('pk'),
          engine_entries__binding__source_links__association_policy=ALL_ENTRIES)
    ).order_by().values(_group=Value(1)).annotate(n=Count('pk', distinct=True)).values('n')
    return sources.annotate(rss_news_count=Coalesce(Subquery(members, output_field=IntegerField()), Value(0)))
