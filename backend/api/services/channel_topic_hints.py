"""Conservative title-only hints for manual channel-grouping previews.

Untrusted article titles are evidence, never instructions. These rules neither
persist a source profile nor authorize an automatic subscription/group change.
A candidate must appear in at least half of >=3 distinct recent titles; sparse
and ambiguous sources retain their existing "needs review" behavior.
"""
from __future__ import annotations

import re

# Use precise terms instead of category-wide words such as "new", "market",
# "go" or "model". English tokens use word boundaries to avoid matching
# fragments (e.g. React must not match "reaction").
_TERMS = {
    'frontend': (
        r'\b(?:react(?:\.js)?|vue(?:\.js)?|svelte|angular|typescript|css|html5?|'
        r'next\.?js|vite|webpack|web components?|frontend|webassembly)\b'
        r'|前端|浏览器渲染|网页布局|网页组件'
    ),
    'ai': (
        r'\b(?:llms?|openai|anthropic|deepseek|machine learning|'
        r'large language models?|generative ai|artificial intelligence|'
        r'neural networks?|transformer models?)\b'
        r'|人工智能|大模型|生成式人工智能|机器学习|神经网络'
    ),
    'engineering': (
        r'\b(?:kubernetes|docker|linux kernel|rust lang|golang|'
        r'postgresql|gitops|devops|open source|software architecture)\b'
        r'|开源项目|软件架构|持续集成|容器编排|操作系统内核'
    ),
    'technology': (
        r'\b(?:semiconductors?|chipsets?|processors?|'
        r'quantum computing|consumer electronics|smartphones?)\b'
        r'|半导体|芯片设计|量子计算|消费电子|智能手机'
    ),
    'health': (
        r'\b(?:clinical trials?|medical devices?|public health|'
        r'pharmaceuticals?|healthcare|vaccines?)\b'
        r'|临床试验|医疗器械|公共卫生|药物研发|医疗健康|疫苗'
    ),
    'energy': (
        r'\b(?:solar power|wind power|energy storage|'
        r'electric vehicles?|power grids?|batter(?:y|ies))\b'
        r'|新能源|光伏|储能|电网|电动汽车|动力电池'
    ),
    'science': (
        r'\b(?:astronomy|astrophysics|particle physics|'
        r'space telescope|scientific research|space exploration)\b'
        r'|天文学|粒子物理|太空探索|科研发现|科学研究'
    ),
    'business': (
        r'\b(?:stock markets?|quarterly earnings|mergers? and acquisitions|'
        r'initial public offerings?|ipo|venture capital)\b'
        r'|股票市场|季度财报|上市融资|风险投资|企业并购'
    ),
    'security': (
        r'\b(?:cve-\d{4}-\d+|zero.day|vulnerabilit(?:y|ies)|'
        r'ransomware|cybersecurity|security patches?)\b'
        r'|网络安全|安全漏洞|零日漏洞|勒索软件|漏洞修复'
    ),
}
_MATCHERS = {key: re.compile(expression, re.IGNORECASE) for key, expression in _TERMS.items()}


def infer_title_topics(titles: list[str] | tuple[str, ...]) -> list[dict[str, int | str]]:
    """Return <=3 review-only hints, sorted by independent supporting titles.

    Repeated headlines and repeated keywords within one headline count once;
    no LLM, network request, write, or user-specific data is involved.
    """
    seen: set[str] = set()
    unique: list[str] = []
    for raw in titles:
        if not isinstance(raw, str):
            continue
        title = ' '.join(raw.split())[:180]
        identity = title.casefold()
        if not identity or identity in seen:
            continue
        seen.add(identity)
        unique.append(title)
        if len(unique) == 12:
            break
    total = len(unique)
    if total < 3:
        return []
    minimum = max(2, (total + 1) // 2)
    ranked: list[tuple[str, int]] = []
    for topic, matcher in _MATCHERS.items():
        hits = sum(bool(matcher.search(title)) for title in unique)
        if hits >= minimum:
            ranked.append((topic, hits))
    ranked.sort(key=lambda item: (-item[1], item[0]))
    return [
        {'topic_key': topic, 'matched_titles': hits, 'total_titles': total}
        for topic, hits in ranked[:3]
    ]
