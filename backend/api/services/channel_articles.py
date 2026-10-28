"""Channel membership and reading policies shared by every reading path."""
from django.db.models import Q
from api.services.source_policy import POLICIES, policy_for_name


def channel_filter(queryset, source_ids):
    """Membership of these sources, starting from the source side.

    Equivalent to ``news_in_sources`` against this source set: primary channel,
    legacy source key, linked engine entry, or explicit public entry. A union
    keeps group and source filters from correlating that test against every
    article in the table.
    """
    from django.db.models import F
    from api.models import EngineEntryMap, News, NewsSourceItem, Source
    from api.rss.access import ALL_ENTRIES, _legacy_keys
    from api.rss.public_membership import public_entries_for_sources
    sources = Source.objects.filter(pk__in=source_ids)
    regular = sources.exclude(publication__requires_public_membership=True)
    primary = News.objects.filter(source_id__in=regular.values('pk')).annotate(_id=F('pk')).values('_id')
    legacy = NewsSourceItem.objects.filter(source_key__in=_legacy_keys(regular)).annotate(_id=F('news_id')).values('_id')
    engine = EngineEntryMap.objects.filter(
        disposition='linked', news_id__isnull=False,
        binding__source_links__source_id__in=regular.values('pk'),
        binding__source_links__association_policy=ALL_ENTRIES,
    ).annotate(_id=F('news_id')).values('_id')
    public = public_entries_for_sources(sources).annotate(_id=F('entry__news_id')).values('_id')
    return queryset.filter(pk__in=primary.union(legacy, engine, public))


def region_filter(queryset, region, *, actor=None):
    from api.models import NewsSourceItem
    keys = [p.key for p in POLICIES.values() if p.region == region]
    from api.rss.access import authorized_sources, _legacy_keys
    sources = authorized_sources(actor)
    members = NewsSourceItem.objects.filter(source_key__in=keys).filter(
        source_key__in=_legacy_keys(sources)).values('news_id')
    from api.models import EngineEntryMap
    engine_members = EngineEntryMap.objects.filter(disposition='linked',
        binding__source_links__association_policy={'version': 1, 'mode': 'all'},
        binding__source_links__source__region=region,
        binding__source_links__source_id__in=sources.values('pk')).values('news_id')
    return queryset.filter(Q(source__region=region) | Q(pk__in=members) | Q(pk__in=engine_members))


def news_policies(news):
    primary = policy_for_name(news.source.name) if getattr(news, 'source_id', None) else None
    policies = {primary.key: primary} if primary else {}
    prefetched = getattr(news, '_prefetched_objects_cache', {}).get('source_items')
    items = prefetched if prefetched is not None else news.source_items.all()
    for item in items:
        policy = POLICIES.get(item.source_key)
        if policy:
            policies[policy.key] = policy
    return tuple(policies.values())


def summary_only(news):
    # Only publishers with a restricted channel need an additional membership read.
    if not getattr(news, 'source_id', None):
        return False
    primary = policy_for_name(news.source.name)
    if primary and primary.reading_policy == 'rss_summary_only':
        return True
    from urllib.parse import urlsplit
    host = urlsplit(news.url).hostname
    if not any(p.reading_policy == 'rss_summary_only' and host in p.domains for p in POLICIES.values()):
        return False
    return any(p.reading_policy == 'rss_summary_only' for p in news_policies(news))


def exclude_summary_only(queryset):
    from api.models import NewsSourceItem
    policies = [p for p in POLICIES.values() if p.reading_policy == 'rss_summary_only']
    members = NewsSourceItem.objects.filter(source_key__in=[p.key for p in policies]).values('news_id')
    return queryset.exclude(source__name__in=[p.name for p in policies]).exclude(pk__in=members)



def category_filter(queryset, category_ids, *, actor=None):
    from api.models import Category, NewsSourceItem
    names = Category.objects.filter(pk__in=category_ids).values_list('name', flat=True)
    keys = [p.key for p in POLICIES.values() if p.default_category in names]
    from api.rss.access import authorized_sources, _legacy_keys
    sources = authorized_sources(actor)
    members = NewsSourceItem.objects.filter(source_key__in=keys).filter(
        source_key__in=_legacy_keys(sources)).values('news_id')
    from api.models import EngineEntryMap
    engine_members = EngineEntryMap.objects.filter(
        Q(binding__source_links__source__crawler_config__category_id__in=category_ids) |
        Q(binding__source_links__source__name__in=[p.name for p in POLICIES.values() if p.key in keys]),
        disposition='linked',
        binding__source_links__association_policy={'version': 1, 'mode': 'all'},
        binding__source_links__source_id__in=sources.values('pk')).values('news_id')
    from api.rss.public_membership import public_entries_for_sources
    from api.models import ChannelSubscription,Source
    from api.rss.access import news_in_sources
    personal_ids=ChannelSubscription.objects.filter(user=actor,category_id__in=category_ids).values('source_id') if actor and actor.is_authenticated else []
    personal_members=news_in_sources(queryset,Source.objects.filter(pk__in=personal_ids)).values('pk')
    public_members = public_entries_for_sources(sources).filter(
        source__public_candidate__category_id__in=category_ids).values('entry__news_id')
    return queryset.filter(Q(category_id__in=category_ids) | Q(pk__in=members) | Q(pk__in=engine_members) | Q(pk__in=public_members) | Q(pk__in=personal_members))



def medical_news(news):
    if news.category.name == '医疗健康':
        return True
    primary = policy_for_name(news.source.name)
    if primary and primary.default_category == '医疗健康':
        return True
    from urllib.parse import urlsplit
    host = urlsplit(news.url).hostname
    if not any(p.default_category == '医疗健康' and host in p.domains for p in POLICIES.values()):
        return False
    return any(p.default_category == '医疗健康' for p in news_policies(news))
