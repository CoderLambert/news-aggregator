"""Public discovery taxonomy, independent of account-owned channel groups."""
from urllib.parse import urlsplit, urlunsplit

SECTIONS = [{'key': 'tech',
  'label': '技术',
  'groups': [{'key': 'ai-llm', 'label': 'AI / 大模型'},
             {'key': 'frontend', 'label': '前端开发'},
             {'key': 'backend-architecture', 'label': '后端与架构'},
             {'key': 'open-source-ecosystem', 'label': '开源生态'},
             {'key': 'devops-cloud', 'label': 'DevOps / 云原生'},
             {'key': 'network-security', 'label': '网络与安全'},
             {'key': 'devtools', 'label': '开发工具'},
             {'key': 'bigtech-engineering', 'label': '大厂技术官方'},
             {'key': 'open-source-trends', 'label': '开源趋势'}]},
 {'key': 'business',
  'label': '商业',
  'groups': [{'key': 'technology-business', 'label': '科技商业'},
             {'key': 'startup-product', 'label': '创业与产品'},
             {'key': 'investment-market', 'label': '投资与市场'}]},
 {'key': 'industry',
  'label': '行业',
  'groups': [{'key': 'healthcare', 'label': '医疗健康'},
             {'key': 'energy', 'label': '能源'},
             {'key': 'automotive', 'label': '汽车'},
             {'key': 'consumer-electronics', 'label': '消费电子'},
             {'key': 'semiconductors', 'label': '芯片与半导体'}]},
 {'key': 'news',
  'label': '新闻时事',
  'groups': [{'key': 'world-news', 'label': '国际新闻'},
             {'key': 'china-news', 'label': '国内新闻'},
             {'key': 'policy-regulation', 'label': '政策与监管'}]},
 {'key': 'reading',
  'label': '人文与阅读',
  'groups': [{'key': 'longreads-stories', 'label': '深度阅读与故事'}]}]

PATHS = {(s['label'], g['label']): (s['key'], g['key'])
         for s in SECTIONS for g in s['groups']}
GROUP_SECTIONS = {g['key']: s['key'] for s in SECTIONS for g in s['groups']}


def catalog_tag(section, group):
    return f'newshub:{section}:{group}'


def url_key(value):
    """Conservative identity after URL-policy validation; never infer redirects."""
    parsed = urlsplit(value)
    host = (parsed.hostname or '').lower()
    if ':' in host:
        host = f'[{host}]'
    if parsed.port not in (None, 443):
        host += f':{parsed.port}'
    return urlunsplit((parsed.scheme.lower(), host, parsed.path, parsed.query, parsed.fragment))


def validate_selection(section='', group=''):
    if not isinstance(section, str) or not isinstance(group, str):
        raise ValueError('invalid catalog selection')
    if section not in {'', *(s['key'] for s in SECTIONS)}:
        raise ValueError('invalid catalog section')
    if group and (group not in GROUP_SECTIONS or section and GROUP_SECTIONS[group] != section):
        raise ValueError('invalid catalog group')


def paths_for_tags(tags):
    return [{'section_key': s['key'], 'section_label': s['label'],
             'group_key': g['key'], 'group_label': g['label']}
            for s in SECTIONS for g in s['groups']
            if catalog_tag(s['key'], g['key']) in tags]


def matches_selection(tags, section='', group=''):
    if not section and not group:
        return True
    return any((not section or p['section_key'] == section) and
               (not group or p['group_key'] == group) for p in paths_for_tags(tags))


def taxonomy_counts(rows):
    """Whole-snapshot unique URL counts, not page size or a user's subscriptions."""
    groups = {key: set() for key in GROUP_SECTIONS}
    roots = {s['key']: set() for s in SECTIONS}
    for row in rows:
        if row.get('visibility', 'public') != 'public' or row.get('kind', 'feed') != 'feed':
            continue
        key = url_key(row['public_url'])
        for path in paths_for_tags(row.get('tags', [])):
            groups[path['group_key']].add(key)
            roots[path['section_key']].add(key)
    return [dict(key=s['key'], label=s['label'], count=len(roots[s['key']]),
                 groups=[dict(key=g['key'], label=g['label'], count=len(groups[g['key']]))
                         for g in s['groups']]) for s in SECTIONS]
