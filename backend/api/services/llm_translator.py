"""Translation service with dual-provider support: Volcengine (primary) → DashScope (fallback)."""

import logging
import os
import re
import time

from openai import OpenAI

logger = logging.getLogger(__name__)

# ============ Primary Provider: Volcengine ============
VOLCENGINE_BASE_URL = 'https://ark.cn-beijing.volces.com/api/coding/v3'
VOLCENGINE_MODEL = 'doubao-seed-2.0-pro'

# ============ Fallback Provider: DashScope ============
DASHSCOPE_BASE_URL = 'https://coding.dashscope.aliyuncs.com/v1'
DASHSCOPE_MODEL = 'kimi-k2.5'

# ============ Translation Prompt ============
TRANSLATION_SYSTEM = """你是一位资深的中英双语翻译专家，擅长将英文技术文章翻译成地道、流畅的中文。

## 翻译原则：
1. **准确传达原文含义**，不增删原意
2. **中文表达自然流畅**，避免逐字直译的机械感
3. **技术术语**：如果该术语在中文技术社区有通用的英文表达方式（如 API、LLM、RAG、Docker），保持英文原文
4. **人名、品牌名、产品名**：保持原文，首次出现时可在括号内加中文说明
5. **不添加额外内容**：不写译者注、不加"翻译如下"等前缀
6. **语气和风格**：保持原文的语气和写作风格
7. **标点符号**：使用中文全角标点（，。！？：""''——……），但代码和 URL 中保持半角

## 排版优化要求：
翻译时请对 Markdown 排版进行优化，使其在中文阅读场景下更美观易读：

1. **段落分隔**：不同主题/段落之间用空行分隔，保持适当的段落间距
2. **标题层次**：合理使用 `##` 和 `###` 标题，确保层级清晰
3. **分隔线**：在章节之间适当使用 `---` 水平分隔线，增强视觉层次
4. **重点标注**：对关键概念、重要提示使用 **粗体** 标注
5. **引用格式**：对于原文中的提示、注意事项、重要说明，使用 `> 引用块` 格式
6. **列表优化**：将并列的内容转为无序列表（`- `），将步骤转为有序列表（`1. ` `2. `）
7. **代码块**：
   - 务必保留原始代码，不要翻译代码内容
   - 所有代码块必须标注语言类型（如 ```python、```bash、```js）
   - 行内代码用反引号包裹
8. **表格**：如果原文有对比数据，请使用 Markdown 表格呈现
9. **链接**：保留所有原始链接，使用 `[描述](URL)` 格式
10. **图片**：保留 `![描述](URL)` 格式，不要修改图片链接

## 输出格式：
请只返回优化排版后的 Markdown 内容，不要有任何其他文字。"""


def _get_volcengine_key():
    """Get Volcengine ARK API key from environment or Hermes config.

    Volcengine ARK keys start with 'ark-'.  If the key found in Hermes
    config starts with 'ark-', use it as the Volcengine key.
    """
    vk = os.environ.get('VOLCENGINE_API_KEY') or os.environ.get('ARK_API_KEY', '')
    if vk and vk.startswith('ark-'):
        return vk

    # Fallback: read from Hermes config (user's main API key may be an ARK key)
    try:
        import yaml
        config_path = os.path.expanduser('~/.hermes/config.yaml')
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        ark_key = config.get('model', {}).get('api_key', '')
        if ark_key and ark_key.startswith('ark-'):
            return ark_key
    except Exception:
        pass

    return vk


def _get_dashscope_key():
    """Get DashScope Coding API key from environment or Hermes config.

    DashScope keys typically start with 'sk-'.  If the only available key
    starts with 'ark-' (Volcengine ARK format) it is NOT a valid DashScope
    key — return empty so we skip DashScope and avoid a 401 error.
    """
    api_key = os.environ.get('DASHSCOPE_CODING_API_KEY') or os.environ.get('DASHSCOPE_API_KEY')

    # If env var is explicitly empty (user didn't set it), try Hermes config
    if not api_key:
        try:
            import yaml
            config_path = os.path.expanduser('~/.hermes/config.yaml')
            with open(config_path, 'r') as f:
                config = yaml.safe_load(f)
            api_key = config.get('model', {}).get('api_key', '')
        except Exception:
            pass

    # ARK-prefixed keys are for Volcengine, not DashScope
    if api_key and api_key.startswith('ark-'):
        return ''

    return api_key


def get_openai_client():
    """Get an OpenAI-compatible client.

    Returns: tuple (client, model_name). Prefers Volcengine; falls back to DashScope.
    Kept as a single-result API for backward-compat with callers that unpack 1 value:
    callers should switch to get_clients() for full fallback chain.
    """
    clients = get_clients()
    if not clients:
        raise ValueError("未配置 VOLCENGINE_API_KEY 或 DASHSCOPE_CODING_API_KEY")
    return clients[0][0]


def get_clients():
    """Return ordered list of (client, model_name) tuples for failover.

    Order: Volcengine (primary) → DashScope (fallback).
    Skips providers without an API key.
    """
    out = []
    vk = _get_volcengine_key()
    if vk:
        out.append((
            OpenAI(api_key=vk, base_url=VOLCENGINE_BASE_URL),
            VOLCENGINE_MODEL,
        ))
    dk = _get_dashscope_key()
    if dk:
        out.append((
            OpenAI(api_key=dk, base_url=DASHSCOPE_BASE_URL),
            DASHSCOPE_MODEL,
        ))
    return out


# Known Chinese tech blog / translation platform domains
CHINESE_DOMAINS = [
    'juejin.cn', 'juejin.im',
    'csdn.net',
    'mp.weixin.qq.com',
    'zhuanlan.zhihu.com', 'zhihu.com',
    'oschina.net',
    'infoq.cn', 'infoq.com',
    'segmentfault.com',
    'cnblogs.com',
    'ruanyifeng.com',
    'liaoxuefeng.com',
    '36kr.com',
    'tmtpost.com',
    'geekpark.net',
    'qianguyihao.com',
    'github.com',  # may have zh-CN readme or wiki
]

# URL patterns that suggest Chinese content
CHINESE_URL_PATTERNS = ['/zh/', '/zh-cn/', '/cn/', '-zh', '_zh', '?lang=zh', '?locale=zh']

# Markdown patterns that indicate a Chinese translation link
ZH_LINK_PATTERNS = [
    r'\[中文翻译?\]\(([^)]+)\)',
    r'\[中文版\]\(([^)]+)\)',
    r'\[中文\]\(([^)]+)\)',
    r'\[Chinese\]\(([^)]+)\)',
    r'\[译文\]\(([^)]+)\)',
    r'\[翻译\]\(([^)]+)\)',
    r'中文翻译[：:]\s*(https?://[^\s\)]+)',
    r'中文版[：:]\s*(https?://[^\s\)]+)',
    r'原文[：:]\s*(https?://[^\s\)]+)',  # sometimes links to original, skip
]


def _is_chinese_domain(url: str) -> bool:
    """Check if URL points to a known Chinese platform."""
    from urllib.parse import urlparse
    try:
        domain = urlparse(url).netloc.lower()
        for cd in CHINESE_DOMAINS:
            if cd in domain:
                return True
    except Exception:
        pass
    return False


def _is_chinese_url_pattern(url: str) -> bool:
    """Check if URL contains Chinese locale patterns."""
    url_lower = url.lower()
    return any(p in url_lower for p in CHINESE_URL_PATTERNS)


def find_chinese_translation_link(content: str, original_url: str) -> str:
    """Find a Chinese translation link in the article content.
    
    Returns the URL if found, empty string otherwise.
    """
    import re
    
    # 1. Search for explicit Chinese translation link patterns
    for pattern in ZH_LINK_PATTERNS:
        match = re.search(pattern, content)
        if match:
            url = match.group(1).strip()
            # Skip if it's the original URL itself
            if url == original_url:
                continue
            if _is_chinese_domain(url) or _is_chinese_url_pattern(url):
                return url
    
    # 2. Search for any links that might be Chinese versions
    #    Look for markdown links with Chinese descriptions
    zh_link_re = re.compile(r'\[([^\]]{1,20})\]\((https?://[^\)]+)\)')
    for match in zh_link_re.finditer(content):
        desc, url = match.group(1), match.group(2)
        if url == original_url:
            continue
        # Check if description suggests Chinese content
        desc_lower = desc.lower()
        if any(kw in desc_lower for kw in ['中文', '译文', '翻译', 'chinese', '汉化']):
            if _is_chinese_domain(url) or _is_chinese_url_pattern(url):
                return url
    
    return ''


def fetch_and_verify_chinese_content(url: str) -> str:
    """Fetch a potential Chinese translation URL and verify it contains Chinese content.
    
    Returns the Chinese Markdown content if verified, empty string otherwise.
    """
    try:
        import ssl
        import urllib.request
        
        jina_url = f'https://r.jina.ai/{url}'
        req = urllib.request.Request(
            jina_url,
            headers={'Accept': 'text/plain', 'User-Agent': 'Mozilla/5.0'}
        )
        with urllib.request.urlopen(req, timeout=30, context=ssl.create_default_context()) as resp:
            text = resp.read().decode('utf-8')
        
        # Extract markdown content
        markdown_match = re.search(r'Markdown Content:\n([\s\S]+)$', text)
        markdown = markdown_match.group(1).strip() if markdown_match else text.strip()
        
        if not markdown or len(markdown) < 50:
            return ''
        
        # Verify it contains Chinese characters
        zh_chars = sum(1 for c in markdown if '\u4e00' <= c <= '\u9fff')
        total_chars = len(markdown.replace('\n', '').replace(' ', ''))
        if total_chars > 0 and zh_chars / total_chars < 0.1:
            return ''  # Not enough Chinese content
        
        return markdown
        
    except Exception:
        return ''


def _call_llm_stream(prompt: str, max_tokens: int = 32000):
    """Call the LLM API with streaming response, using provider failover.

    Yields chunks of translated text.
    """
    clients = get_clients()
    if not clients:
        yield "未配置 VOLCENGINE_API_KEY 或 DASHSCOPE_CODING_API_KEY"
        return

    last_err = None
    for idx, (client, model) in enumerate(clients):
        try:
            stream = client.chat.completions.create(
                model=model,
                messages=[
                    {'role': 'system', 'content': TRANSLATION_SYSTEM},
                    {'role': 'user', 'content': prompt}
                ],
                temperature=0.3,
                max_tokens=max_tokens,
                stream=True,
            )

            got_any = False
            for chunk in stream:
                delta = chunk.choices[0].delta
                if delta.content:
                    got_any = True
                    yield delta.content
            if got_any:
                return  # success
            # Empty stream — try next provider
            last_err = f"provider#{idx} ({model}) returned empty stream"
        except Exception as e:
            last_err = f"provider#{idx} ({model}) failed: {e}"
            logger.warning(last_err)
            continue

    logger.error(f"All LLM providers failed. Last error: {last_err}")
    yield f"Error: {last_err}"


def _call_llm(prompt: str, max_tokens: int = 32000) -> tuple:
    """Call the LLM API with the given prompt, using provider failover.

    Returns:
        tuple: (response_text, error_message)
    """
    clients = get_clients()
    if not clients:
        return ('', '未配置 VOLCENGINE_API_KEY 或 DASHSCOPE_CODING_API_KEY')

    last_err = None
    for idx, (client, model) in enumerate(clients):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {'role': 'system', 'content': TRANSLATION_SYSTEM},
                    {'role': 'user', 'content': prompt}
                ],
                temperature=0.3,
                max_tokens=max_tokens,
            )
            content = response.choices[0].message.content
            if content:
                return (content.strip(), None)
            last_err = f"provider#{idx} ({model}) returned empty content"
        except Exception as e:
            last_err = f"provider#{idx} ({model}) failed: {e}"
            logger.warning(last_err)
            continue

    logger.error(f'All LLM providers failed. Last error: {last_err}')
    return ('', last_err or '未知错误')


def translate_with_llm(text: str) -> tuple:
    """Translate Markdown text to Chinese using DashScope API.
    
    Args:
        text: The Markdown content to translate
        
    Returns:
        tuple: (translated_text, error_message)
    """
    if not text or not text.strip():
        return ('', '待翻译内容为空')

    # For long content, split into chunks to avoid token limits
    if len(text) > 20000:
        return _translate_chunked(text)

    prompt = f"请将以下 Markdown 文章翻译成中文：\n\n{text}"
    return _call_llm(prompt)


def _translate_chunked(text: str, chunk_size: int = 15000) -> tuple:
    """Split long content into sections by headings and translate each chunk."""
    sections = re.split(r'(\n#{1,4}\s)', text)
    
    chunks = []
    current = ''
    
    for section in sections:
        if len(current) + len(section) <= chunk_size:
            current += section
        else:
            if current:
                chunks.append(current)
            current = section
    
    if current:
        chunks.append(current)
    
    translated_parts = []
    for i, chunk in enumerate(chunks):
        translated, error = translate_with_llm(chunk)
        if error:
            return ('', f'第 {i+1}/{len(chunks)} 段翻译失败: {error}')
        translated_parts.append(translated)
        # Rate limiting between chunks
        if i < len(chunks) - 1:
            time.sleep(2)
    
    return ('\n\n'.join(translated_parts), None)
