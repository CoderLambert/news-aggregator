"""Translation helpers for user-scoped LiteLLM clients."""

import logging
import re
import time

logger = logging.getLogger(__name__)

# ============ Translation Prompt ============
TRANSLATION_SYSTEM = """你是一位资深的中英双语翻译专家，擅长将英文技术文章翻译成地道、流畅的中文。

## 翻译原则：
1. **准确传达原文含义**，不增删原意
2. **中文表达自然流畅**，避免逐字直译的机械感
3. **技术术语**：如果该术语在中文技术社区有通用的英文表达方式（如 API、LLM、RAG、Docker、Python、JavaScript、TypeScript、Go、Rust、Java、Node.js、React、Django），保持英文原文，严禁把编程语言名翻译成中文词义（例如 Python 不能翻译为“蟒蛇”）
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
7. **代码和标识符保护（最高优先级）**：
   - Markdown fenced code block（```...```）必须逐字符原样保留，包括 opening fence、语言标识（如 python/bash/js）、缩进、空行、注释、字符串和 closing fence，严禁翻译、改写、格式化或补全其中任何内容
   - Markdown inline code（`...`）必须逐字符原样保留，严禁翻译其中的 API 名、变量名、命令、路径、包名、错误信息或代码片段
   - 不要把普通正文里的技术标识符翻译成自然语言词义，例如 Python、Java、Go、Rust、Docker、React、Django、FastAPI、API、CLI、SDK、JSON、YAML 均保持英文
   - 如果原文代码块没有语言标识，可以保持原样；不要为了“补全语言类型”而重写代码块 fence
8. **表格**：如果原文有对比数据，请使用 Markdown 表格呈现
9. **链接**：保留所有原始链接，使用 `[描述](URL)` 格式
10. **图片**：保留 `![描述](URL)` 格式，不要修改图片链接

## 输出格式：
请只返回优化排版后的 Markdown 内容，不要有任何其他文字。

## 重要校验：
输出前自检：所有 ``` fenced code block 和所有 `inline code` 必须与原文完全一致；若无法确认，宁可保留原文片段，也不要翻译或改写。"""


def build_translation_prompt(markdown: str) -> str:
    """Build a strict Markdown translation prompt.

    This intentionally relies on prompt constraints only: the model must keep
    protected Markdown/code regions unchanged while translating natural prose.
    """
    return f"""请将下面的英文 Markdown 技术文章翻译成中文。严格遵守以下规则：

1. 只翻译自然语言正文、标题、列表文字、表格中的自然语言说明。
2. 不要翻译、改写或格式化任何 fenced code block：从 opening ``` 到 closing ``` 的全部内容必须逐字符保持原样。
3. 不要翻译任何反引号包裹的 inline code，例如 `Python`、`pip install`、`model.forward()`、`/api/news/` 必须原样输出。
4. 编程语言名、框架名、库名、命令、API、协议、文件名、路径、环境变量、错误码保持英文或原始拼写；尤其 Python 绝不能翻译为“蟒蛇”。
5. 保留所有 Markdown 结构、链接 URL、图片 URL、代码块语言标识和表格结构。
6. 输出只能是翻译后的 Markdown，不要添加解释、校验说明或额外前后缀。

原文开始：
<<<MARKDOWN_ARTICLE>>>
{markdown}
<<<END_MARKDOWN_ARTICLE>>>
"""


def get_openai_client():
    """Return a configured hosted client, when one exists."""
    clients = get_clients()
    if not clients:
        raise ValueError("未配置站点共享模型；请使用用户自己的 LiteLLM API 连接")
    return clients[0][0]


def get_clients():
    """Hosted provider keys are disabled; callers must use owner-scoped BYOK."""
    return []


def _call_llm_stream(prompt: str, max_tokens: int = 32000, *, clients=None):
    """Call the LLM API with streaming response, using provider failover.

    Yields chunks of translated text.
    """
    messages = [
        {'role': 'system', 'content': TRANSLATION_SYSTEM},
        {'role': 'user', 'content': prompt}
    ]
    yield from stream_chat(messages, max_tokens, require_completed=True, clients=clients)


def stream_chat(
    messages: list,
    max_tokens: int = 32000,
    temperature: float = 0.3,
    enable_search: bool = False,
    require_completed: bool = False,
    *,
    clients=None,
):
    """Generic streaming chat with provider failover + per-provider retry.

    Yields chunks of text.  On total failure, yields a single fallback message.
    """
    clients = get_clients() if clients is None else clients
    if not clients:
        yield "抱歉，当前 AI 服务暂时不可用，请稍后再试。"
        return

    last_err = None
    for idx, (client, model) in enumerate(clients):
        configured_attempts = getattr(client, '_newshub_max_attempts', 2)
        max_attempts = configured_attempts if type(configured_attempts) is int else 2
        max_attempts = min(max(max_attempts, 1), 2)
        for attempt in range(1, max_attempts + 1):
            got_any = False
            completed = False
            stream = None
            try:
                stream = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    stream=True,
                )

                for chunk in stream:
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta
                    if getattr(chunk.choices[0], 'finish_reason', None) == 'stop':
                        completed = True
                    if delta.content:
                        got_any = True
                        yield delta.content
                if got_any:
                    if require_completed and not completed:
                        raise ValueError('全文翻译响应未完整完成，请重试。')
                    return  # success
                last_err = f"provider#{idx} ({model}) returned empty stream"
                break  # don't retry empty stream — likely a prompt issue
            except Exception as e:
                if require_completed and got_any:
                    # Never append a second provider's output to a partial article.
                    raise ValueError('全文翻译响应中断或未完整完成，请重试。') from e
                last_err = f"provider#{idx} ({model}) attempt {attempt}/{max_attempts} failed ({type(e).__name__})"
                logger.warning(last_err)
                # Retry on transient errors (SSL, timeout, connection reset)
                is_transient = any(kw in str(e).lower() for kw in [
                    'ssl', 'eof', 'timeout', 'connection', 'reset', 'broken pipe',
                ])
                if is_transient and attempt < max_attempts:
                    time.sleep(1 * attempt)  # simple backoff
                    continue
                break  # non-transient or exhausted retries → try next provider
            finally:
                if stream is not None and hasattr(stream, 'close'):
                    stream.close()

    logger.error("All LLM providers failed. Last error: %s", last_err)
    # Upstream exception text can contain request metadata. Record only its
    # sanitized type above and never stream raw details to the browser.
    yield "抱歉，AI 服务暂时不可用，请稍后再试。"


def _call_llm(prompt: str, max_tokens: int = 32000) -> tuple:
    """Call the LLM API with the given prompt, using provider failover + retry.

    Returns:
        tuple: (response_text, error_message)
    """
    MAX_RETRIES = 2

    clients = get_clients()
    if not clients:
        return ('', '未配置站点共享模型；请使用用户自己的 LiteLLM API 连接')

    last_err = None
    for idx, (client, model) in enumerate(clients):
        for attempt in range(1, MAX_RETRIES + 1):
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
                break  # don't retry empty content
            except Exception as e:
                last_err = f"provider#{idx} ({model}) attempt {attempt}/{MAX_RETRIES} failed ({type(e).__name__})"
                logger.warning(last_err)
                is_transient = any(kw in str(e).lower() for kw in [
                    'ssl', 'eof', 'timeout', 'connection', 'reset', 'broken pipe',
                ])
                if is_transient and attempt < MAX_RETRIES:
                    time.sleep(1 * attempt)
                    continue
                break

    logger.error('All LLM providers failed. Last error: %s', last_err)
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

    prompt = build_translation_prompt(text)
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
