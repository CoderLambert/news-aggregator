ALL_CATEGORIES = {
    '科技': {'slug': 'tech', 'keywords': []},
    '国际': {'slug': 'world', 'keywords': []},
    '财经': {'slug': 'finance', 'keywords': []},
    'AI': {'slug': 'ai', 'keywords': []},
    '创业': {'slug': 'startup', 'keywords': []},
    '产品': {'slug': 'product', 'keywords': []},
    '安全': {'slug': 'security', 'keywords': []},
    '区块链': {'slug': 'blockchain', 'keywords': []},
    '前端': {'slug': 'frontend', 'keywords': []},
    '后端': {'slug': 'backend', 'keywords': []},
    'DevOps': {'slug': 'devops', 'keywords': []},
    '开发工具': {'slug': 'devtools', 'keywords': []},
    'SaaS': {'slug': 'saas', 'keywords': []},
    '问答': {'slug': 'qa', 'keywords': []},
    '招聘': {'slug': 'jobs', 'keywords': []},
}

KEYWORD_MAP = {
    'AI': ['ai', 'llm', 'gpt', 'artificial intelligence', 'machine learning', 'deep learning', 'agent'],
    '科技': ['tech', 'technology', 'software', 'computer', 'digital', 'internet', 'cyber'],
    '创业': ['startup', 'venture', 'funding', 'fundraising', 'launch', 'ipo', 'acquisition'],
    '安全': ['security', 'privacy', 'vulnerability', 'hack', 'breach', 'malware', 'exploit'],
    '区块链': ['crypto', 'blockchain', 'web3', 'bitcoin', 'ethereum', 'nft', 'defi'],
    '产品': ['product', 'app', 'mobile', 'gadgets', 'design', 'ux', 'ui'],
    '前端': ['webdev', 'javascript', 'typescript', 'react', 'vue', 'css', 'html', 'frontend'],
    '后端': ['python', 'go', 'rust', 'java', 'backend', 'api', 'server', 'database'],
    'DevOps': ['devops', 'cloud', 'aws', 'docker', 'kubernetes', 'ci/cd', 'infrastructure'],
    '开发工具': ['developer', 'api', 'code', 'open source', 'tool', 'cli', 'sdk'],
    'SaaS': ['saas', 'productivity', 'workflow', 'platform', 'service', 'cloud'],
    '财经': ['finance', 'business', 'market', 'economy', 'stock', 'trading', 'invest'],
    '招聘': ['hire', 'job', 'hiring', 'career', 'recruiting'],
    '问答': ['ask', 'question', 'how to', 'tutorial', 'explain'],
}

DEFAULT_CATEGORY = '科技'


def classify(title, description=''):
    text = f'{title} {description}'.lower()
    for category, keywords in KEYWORD_MAP.items():
        if any(kw in text for kw in keywords):
            return category
    return DEFAULT_CATEGORY
