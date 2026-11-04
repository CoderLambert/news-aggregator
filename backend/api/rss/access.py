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
    from api.rss.public_membership import public_entries_for_sources
    regular = sources.exclude(publication__requires_public_membership=True)
    legacy = NewsSourceItem.objects.filter(news_id=OuterRef('pk'), source_key__in=_legacy_keys(regular))
    engine = EngineEntryMap.objects.filter(news_id=OuterRef('pk'), disposition='linked',
        binding__source_links__source_id__in=regular.values('pk'),
        binding__source_links__association_policy=ALL_ENTRIES)
    explicit = public_entries_for_sources(sources).filter(entry__news_id=OuterRef('pk'))
    return queryset.alias(_rss_legacy_member=Exists(legacy), _rss_engine_member=Exists(engine),
        _rss_public_member=Exists(explicit)).filter(Q(source_id__in=regular.values('pk')) |
            Q(_rss_legacy_member=True) | Q(_rss_engine_member=True) | Q(_rss_public_member=True))


def authorized_news(user, queryset=None):
    return news_in_sources(News.objects.all() if queryset is None else queryset, authorized_sources(user))


def article_sources(user, news):
    """Authorized channels only; callers must not expose a private primary source."""
    from api.rss.public_membership import public_entries_for_sources
    sources = authorized_sources(user)
    keys = set(news.source_items.values_list('source_key', flat=True))
    legacy_names = [p.name for p in POLICIES.values() if p.key in keys]
    links = SourceFeedLink.objects.filter(binding__entry_maps__news_id=news.pk,
        binding__entry_maps__disposition='linked', association_policy=ALL_ENTRIES).values('source_id')
    public = public_entries_for_sources(sources).filter(entry__news_id=news.pk).values('source_id')
    return sources.filter(Q(publication__requires_public_membership=False) &
        (Q(pk=news.source_id) | Q(name__in=legacy_names) | Q(pk__in=links)) | Q(pk__in=public)).order_by('pk')


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
    from api.rss.public_membership import public_entries_for_sources
    explicit_pairs = set(public_entries_for_sources(authorized_sources(user)).filter(entry__news_id__in=ids).values_list('entry__news_id','source_id')) if any(source.publication.requires_public_membership for source in sources) else set()
    policy_keys = {policy.name: policy.key for policy in POLICIES.values()}
    snapshots = {}
    for article in articles:
        visible = [source for source in sources if (article.pk, source.pk) in explicit_pairs
                   or (not source.publication.requires_public_membership and (source.pk == article.source_id
                   or source.pk in engine_sources.get(article.pk, set())
                   or policy_keys.get(source.name) in keys_by_news[article.pk]))]
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


def _membership_counts(querysets):
    """Aggregate distinct authorized (source, article) pairs inside the DB.

    Django cannot annotate after UNION. Compile its parameterized queries and
    only wrap that trusted SQL; no request strings are interpolated here.
    """
    if not querysets:
        return {}
    from django.db import connections
    memberships = querysets[0].union(*querysets[1:]).order_by()
    database = connections[memberships.db]
    sql, params = memberships.query.get_compiler(using=memberships.db).as_sql()
    with database.cursor() as cursor:
        cursor.execute(
            f'WITH memberships(source_id, news_id) AS ({sql}) '
            'SELECT source_id, COUNT(DISTINCT news_id) FROM memberships GROUP BY source_id', params)
        return dict(cursor.fetchall())


def with_authorized_source_counts(user, sources):
    """Count authorized members once per path, then attach the totals.

    A correlated ``authorized_news`` subquery per source re-scans the article
    table for every channel on the history catalog. Group the same primary,
    legacy-key, and engine-link rules, and keep public-membership channels on
    their own explicit entries.
    """
    from django.db.models import Count, IntegerField
    from api.rss.public_membership import public_entries_for_sources
    rows = list(sources.annotate(_rss_count_source_key=Case(
        *[When(name=policy.name, then=Value(policy.key)) for policy in POLICIES.values()],
        default=Value(None), output_field=CharField(),
    )).values_list('pk', '_rss_count_source_key', 'publication__requires_public_membership'))
    if not rows:
        return sources.annotate(rss_news_count=Value(0, output_field=IntegerField()))
    public_ids = [pk for pk, _key, public in rows if public]
    regular = [(pk, key) for pk, key, public in rows if not public]
    regular_ids = [pk for pk, _key in regular]
    key_to_source = {key: pk for pk, key in regular if key}
    authorized = authorized_news(user)
    paths = []
    if regular_ids:
        paths.append(authorized.filter(source_id__in=regular_ids).order_by().values_list('source_id', 'pk'))
        paths.append(EngineEntryMap.objects.filter(
            disposition='linked', news_id__in=authorized.values('pk'),
            binding__source_links__source_id__in=regular_ids,
            binding__source_links__association_policy=ALL_ENTRIES,
        ).order_by().values_list('binding__source_links__source_id', 'news_id'))
    if key_to_source:
        paths.append(NewsSourceItem.objects.filter(
            news_id__in=authorized.values('pk'), source_key__in=key_to_source,
        ).annotate(_count_source_id=Case(
            *[When(source_key=key, then=Value(pk)) for key, pk in key_to_source.items()],
            output_field=IntegerField(),
        )).order_by().values_list('_count_source_id', 'news_id'))
    regular_counts = _membership_counts(paths)
    public_counts = {}
    if public_ids:
        public_counts = dict(public_entries_for_sources(Source.objects.filter(pk__in=public_ids)).filter(
            entry__news_id__in=authorized.values('pk'),
        ).order_by().values('source_id').annotate(total=Count('entry__news_id', distinct=True))
            .values_list('source_id', 'total'))
    totals = {
        pk: public_counts.get(pk, 0) if public else regular_counts.get(pk, 0)
        for pk, _key, public in rows
    }
    return sources.annotate(rss_news_count=Case(
        *[When(pk=pk, then=Value(total)) for pk, total in totals.items()],
        default=Value(0), output_field=IntegerField(),
    ))
