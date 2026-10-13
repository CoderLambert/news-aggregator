"""Versioned editorial topics. Reading the catalog does not fetch or infer with AI."""
import hashlib
import json
from django.db.models import Q
from api.models import News, Source
from api.services.source_policy import policy_for_name
from api.services.channel_catalog import subscription_status
from api.smart_channel_models import SourceTopicProfile

TAXONOMY_VERSION = '2026-10-13.1'
TOPICS = [
    {'key': 'ai', 'name': '人工智能', 'description': '模型、机器学习与 AI 应用'},
    {'key': 'frontend', 'name': '前端开发', 'description': '浏览器、Web 平台与前端框架'},
    {'key': 'engineering', 'name': '开发与开源', 'description': '软件工程、开源项目与基础设施'},
    {'key': 'technology', 'name': '科技资讯', 'description': '科技产业、产品与互联网'},
    {'key': 'health', 'name': '医疗健康', 'description': '医学研究、健康政策与医疗产业'},
    {'key': 'energy', 'name': '新能源', 'description': '清洁能源、电网、储能与电动车'},
    {'key': 'science', 'name': '科研前沿', 'description': '科学发现、论文与科研进展'},
    {'key': 'business', 'name': '商业财经', 'description': '企业、商业与经济资讯'},
    {'key': 'security', 'name': '网络安全', 'description': '隐私、安全研究与漏洞'},
]
TOPIC_MAP = {item['key']: item for item in TOPICS}
PRESETS = [
    {'key': 'general', 'name': '综合阅读', 'topics': ['ai', 'technology', 'health', 'energy', 'science', 'business']},
    {'key': 'developer', 'name': '开发者', 'topics': ['frontend', 'engineering', 'ai', 'security']},
    {'key': 'industry', 'name': '行业洞察', 'topics': ['energy', 'health', 'business', 'science']},
]
# These describe the configured CHANNEL, not every section of its publisher.
EDITORIAL = {
    'react_blog': ['frontend'], 'webkit': ['frontend'], 'v8': ['frontend'],
    'mozilla_hacks': ['frontend'], 'svelte_blog': ['frontend'], 'angular_blog': ['frontend'],
    'smashing_magazine': ['frontend'], 'css_tricks': ['frontend'], 'webdev': ['frontend'],
    'chrome_dev': ['frontend'], 'frontend_focus': ['frontend'],
    'openai_blog': ['ai'], 'deepmind': ['ai', 'science'], 'anthropic': ['ai'],
    'meta_ai': ['ai'], 'mistral': ['ai'], 'venturebeat_ai': ['ai', 'business'],
    'ars_technica_ai': ['ai'], 'mit_tech_review_ai': ['technology'],
    'arxiv_ai': ['ai', 'science'], 'jiqizhixin': ['ai'], 'leiphone': ['technology', 'ai'],
    'devto': ['engineering'], 'github': ['engineering'], 'hackernews': ['engineering', 'technology'],
    'techcrunch': ['technology', 'business'], 'infoq': ['engineering'],
    'producthunt': ['technology'], 'sanliu_kr': ['business', 'technology'],
}


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def channel_articles(source):
    policy = policy_for_name(source.name)
    query = Q(source=source)
    if policy:
        query |= Q(source_items__source_key=policy.key)
    return News.objects.filter(query).distinct()


def base_profile(source):
    policy = policy_for_name(source.name)
    topics = []
    origin = 'unknown'
    about = source.description.strip() or (policy.description if policy else '')
    if policy:
        if policy.default_category in {'新能源', '医疗健康'}:
            topics = ['energy' if policy.default_category == '新能源' else 'health']
            origin = 'policy'
        elif policy.key in EDITORIAL:
            topics = EDITORIAL[policy.key]
            origin = 'catalog'
    if not about or about in {f'{source.name} 的资讯频道', f'来自 {source.name} 的资讯'}:
        about = '、'.join(TOPIC_MAP[key]['description'] for key in topics) if topics else ''
    evidence_hash = digest([TAXONOMY_VERSION, source.id, source.name, about,
                            policy.key if policy else '', policy.contract_version if policy else '', topics])
    return {'topics': topics, 'about': about, 'origin': origin, 'evidence_hash': evidence_hash}


def profile_data(source, stored=None):
    base = base_profile(source)
    if stored is None:
        stored = SourceTopicProfile.objects.filter(source=source).first()
    # An administrator's editorial correction survives policy refreshes.
    if stored and (stored.origin == 'manual' or stored.evidence_hash == base['evidence_hash']):
        base.update(topics=[t for t in stored.topics if t in TOPIC_MAP], about=stored.about, origin=stored.origin)
    status, reason = subscription_status(source)
    policy = policy_for_name(source.name)
    return {'id': source.id, 'name': source.name, 'url': source.url, 'logo': source.logo,
            'region': source.region, 'language': source.language, 'source_type': source.source_type,
            'description': base['about'], 'topics': base['topics'], 'origin': base['origin'],
            'needs_review': not base['topics'] or base['origin'] == 'ai',
            'evidence_hash': base['evidence_hash'], 'subscription_status': status,
            'subscription_reason': reason, 'feed_url': policy.feed_url if policy else '',
            'policy_key': policy.key if policy else '',
            'reading_policy': policy.reading_policy if policy else 'standard',
            'updated_at': stored.updated_at.isoformat() if stored else None}


def evidence_for(source):
    profile = profile_data(source)
    # Already-ingested public titles only. No private history or full-article fetch.
    titles = list(channel_articles(source).order_by('-publish_time').values_list('title', flat=True)[:12])
    return {'source_id': source.id, 'name': source.name[:100], 'about': profile['description'][:600],
            'titles': [str(t).replace('\x00', '')[:180] for t in titles],
            'evidence_hash': profile['evidence_hash']}


def refresh_profiles(limit=200):
    changed = 0
    for source in Source.objects.order_by('id')[:limit]:
        data = base_profile(source)
        stored = SourceTopicProfile.objects.filter(source=source).first()
        if stored and (stored.origin == 'manual' or stored.evidence_hash == data['evidence_hash']):
            continue
        SourceTopicProfile.objects.update_or_create(source=source, defaults={
            **data, 'revision': (stored.revision + 1) if stored else 1,
        })
        changed += 1
    return changed
