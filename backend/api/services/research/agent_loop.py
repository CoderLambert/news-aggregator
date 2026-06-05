"""Core agent loop for the intelligent news research agent.

Implements the think → tool_call → observe → respond cycle using
OpenAI-compatible function calling with dual-provider failover
(DashScope primary, Volcengine fallback).

The loop runs in a background thread and pushes events via an `on_event`
callback. The caller (job_manager) bridges these events to SSE streaming.
"""

import json
import logging
import time
from typing import Callable

from api.services.llm_translator import get_clients
from .tools import TOOLS, execute_tool

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 15

RESEARCH_SYSTEM_PROMPT = """\
你是一位专业的新闻研究助手，能够进行深度新闻分析、网络调研和话题追踪。

## 意图判断

在每次回复前，你必须先判断用户输入的类型：

- **闲聊/问候/感谢/告别**: 用户只是打招呼、道谢、告别、或简单寒暄（如「你好」「谢谢」「再见」「最近怎么样」）。
  → 直接友好回复，**绝对不要调用任何工具**。保持回复简洁自然。

- **追问/澄清/深入**: 用户在已有研究结果基础上追问（如「能详细说说吗」「还有呢」「换个角度分析」「那 XX 方面呢」）。
  → **基于对话历史中已有的搜索结果和信息直接回答**，不要重复调用搜索工具。如果确实需要补充信息才能回答，可以调用少量必要的工具。

- **新研究请求**: 用户提出了新的研究问题、话题，或明确要求更多信息（如「帮我研究一下 XX」「最近有什么关于 XX 的新闻」「分析 XX 的影响」）。
  → 按以下研究方法论正常调用工具进行深度分析。

## 核心能力
- **深度新闻分析**: 在本地新闻库中语义搜索，交叉对比多篇文章，发现趋势和关联
- **网络调研**: 搜索互联网获取补充信息，对比多个来源，验证事实
- **话题追踪**: 生成事件时间线，发现相关事件，分析趋势走向

## 研究方法论

### 第一步：问题拆解
对于复杂问题，将其拆解为多个子问题独立搜索验证：
- **事实层**: 发生了什么？涉及哪些主体？时间地点？
- **背景层**: 事件的起因是什么？有哪些历史上下文？
- **影响层**: 事件造成了哪些影响？涉及哪些利益相关方？
- **趋势层**: 未来可能的发展方向是什么？有哪些相关预测？

不要用单次搜索回答复杂问题。每个子问题都需要独立搜索，确保覆盖全面。

### 第二步：多维度搜索
1. **先搜索本地新闻库**，使用不同关键词变体检索（同义词、缩写、相关术语）
2. **交叉验证**: 同一关键信息需要至少2个独立来源支持
3. **补充网络搜索**: 对于本地库没有的信息，使用联网搜索补充
4. **迭代扩展**: 如果初始结果不足，换用不同关键词重新搜索，不要轻易放弃
5. **深入阅读**: 对关键文章调用 fetch_article 获取全文，不要仅依赖摘要

### 第三步：信息质量控制
1. **来源评估**: 优先采信权威媒体、官方发布、多方报道一致的信息
2. **矛盾识别**: 如果不同来源信息冲突，明确标注差异和各自信源
3. **信息缺口**: 如果关键信息缺失，明确说明「暂未找到相关信息」而非编造
4. **时间验证**: 注意信息的发布时间，区分历史信息和最新进展
5. **事实与观点分离**: 明确标注哪些是事实陈述，哪些是分析观点

### 第四步：结构化输出
- **核心摘要**: 100字以内总结关键结论
- **关键发现**: 分点列出核心事实，每个事实标注来源 [来源名, 日期] 或 [URL](URL)
- **详细分析**: 多维度分析事件背景、影响和趋势
- **事件时间线**: 按时间顺序列出关键节点（如适用）
- **来源列表**: 所有引用的来源完整清单，每条必须包含可点击的链接，格式如下：
  - 本地新闻文章: `[文章标题](/news/{文章ID})` — 来自搜索结果的 article.id
  - 外部网页: `[来源标题](URL)` — 使用实际 URL
  - 不可省略链接，纯文本来源不可接受

## 工具使用策略
- **简单问题**: search_news 一次即可回答
- **深度分析**: 问题拆解 → 多轮 search_news（不同关键词）→ fetch_article（关键文章）→ search_web（补充）→ generate_report
- **话题追踪**: analyze_topic → search_web → 补充搜索相关事件 → generate_report (include_timeline=true)
- **事实核查**: 多来源搜索 → fetch_article/fetch_webpage 获取原文 → 对比验证矛盾点

### 批量调用规则
**如果多个工具调用之间没有依赖关系，在同一轮中同时发起所有调用。**
例如：
- 同时用不同关键词调用多个 search_news（每个用不同 query 参数）
- 同时调用 search_news 和 search_web 进行本地+网络搜索
- 同时获取多篇文章的 fetch_article
避免逐个串行调用独立工具，浪费迭代轮次。

## 重要规则
1. 每个论断必须有来源支持，禁止没有依据的推测
2. 明确区分事实信息和分析观点，观点部分标注「分析认为」
3. 保持客观中立，不偏信单一来源，呈现多方观点
4. 如果信息不足，明确说明「暂未找到相关信息」
5. 所有时间、数据、人名、机构名必须准确，有来源支撑
6. 使用 generate_report 工具来规划报告结构，确保输出完整有深度

始终使用中文回答。\
"""


def run_agent_loop(session, user_query: str, on_event: Callable):
    """Run the agent loop for a research query.

    Args:
        session: ResearchSession model instance (messages will be updated in-place).
        user_query: The user's question or research prompt.
        on_event: Callback ``on_event(event_type, data)`` for each agent event.
            Event types: thinking, tool_call, tool_result, text_delta, complete, error,
            query_decomposed.
    """
    messages = list(session.messages)  # Copy existing history
    messages.append({'role': 'user', 'content': user_query})

    # Ensure system prompt is present
    if not messages or messages[0].get('role') != 'system':
        messages.insert(0, {'role': 'system', 'content': RESEARCH_SYSTEM_PROMPT})

    for iteration in range(MAX_ITERATIONS):
        on_event('thinking', {'iteration': iteration})

        # Call LLM with tools
        response = _call_llm_with_tools(messages)
        if response is None:
            on_event('error', {'message': '所有 LLM 提供商不可用，请稍后再试'})
            return

        assistant_message = response.choices[0].message

        # Check for tool calls
        if hasattr(assistant_message, 'tool_calls') and assistant_message.tool_calls:
            # Serialize the assistant message with tool_calls for history
            msg_dict = _serialize_assistant_message(assistant_message)
            messages.append(msg_dict)

            for tool_call in assistant_message.tool_calls:
                fn_name = tool_call.function.name
                try:
                    fn_args = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError:
                    fn_args = {}

                call_id = tool_call.id

                on_event('tool_call', {
                    'name': fn_name,
                    'args': fn_args,
                    'call_id': call_id,
                })

                # Execute the tool
                result = execute_tool(fn_name, fn_args, session=session)

                # Build a brief summary for the frontend
                summary = _tool_result_summary(fn_name, result)

                # Include key result data for rich UI rendering (articles, web results)
                on_event('tool_result', {
                    'call_id': call_id,
                    'summary': summary,
                    'name': fn_name,
                    # Attach display-critical result data for the ProcessTimeline component
                    'articles': result.get('articles', []),
                    'results': result.get('results', []),
                    'title': result.get('title', ''),
                    'id': result.get('id', None),
                    'source': result.get('source', ''),
                    'url': result.get('url', ''),
                    'content_truncated': result.get('content_truncated', False),
                    'original_length': result.get('original_length', 0),
                    'length': result.get('length', 0),
                })

                # Append tool result to message history
                messages.append({
                    'role': 'tool',
                    'tool_call_id': call_id,
                    'content': json.dumps(result, ensure_ascii=False),
                })
        else:
            # Final answer — no more tool calls
            final_text = assistant_message.content or ''

            on_event('text_delta', {'text': final_text})

            messages.append({
                'role': 'assistant',
                'content': final_text,
            })

            # Persist to database
            session.messages = messages
            session.save(update_fields=['messages', 'updated_at'])

            # Auto-generate title if this is the first response
            _maybe_generate_title(session, user_query, final_text)

            on_event('complete', {})
            return

    # Hit iteration limit
    on_event('error', {'message': 'Agent 达到最大迭代次数限制，请尝试简化问题'})


def _call_llm_with_tools(messages: list):
    """Call LLM with tool schemas, trying each provider with retry.

    Returns the response object or None on total failure.
    Uses non-streaming calls for the tool-selection phase.
    """
    MAX_RETRIES = 2
    clients = get_clients()
    if not clients:
        return None

    last_err = None
    for idx, (client, model) in enumerate(clients):
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    tools=TOOLS,
                    tool_choice='auto',
                    temperature=0.3,
                    max_tokens=8000,
                )
                return response
            except Exception as e:
                last_err = f'provider#{idx} ({model}) attempt {attempt} failed: {e}'
                logger.warning(last_err)
                is_transient = any(
                    kw in str(e).lower()
                    for kw in ['ssl', 'eof', 'timeout', 'connection', 'reset', 'broken pipe']
                )
                if is_transient and attempt < MAX_RETRIES:
                    time.sleep(1 * attempt)
                    continue
                break  # Non-transient or exhausted retries → try next provider

    logger.error('All LLM providers failed for research agent. Last: %s', last_err)
    return None


def _serialize_assistant_message(message) -> dict:
    """Convert an OpenAI SDK ChatCompletionMessage to a dict for history storage."""
    msg = {'role': 'assistant'}
    if message.content:
        msg['content'] = message.content
    if hasattr(message, 'tool_calls') and message.tool_calls:
        msg['tool_calls'] = []
        for tc in message.tool_calls:
            msg['tool_calls'].append({
                'id': tc.id,
                'type': 'function',
                'function': {
                    'name': tc.function.name,
                    'arguments': tc.function.arguments,
                },
            })
    return msg


def _tool_result_summary(name: str, result: dict) -> str:
    """Build a one-line summary of a tool result for the frontend."""
    if 'error' in result:
        return f'❌ {name}: {result["error"]}'
    if name == 'search_news':
        total = result.get('total', 0)
        return f'找到 {total} 篇相关文章'
    if name == 'fetch_article':
        title = result.get('title', '')[:30]
        return f'已获取: {title}'
    if name == 'search_web':
        count = len(result.get('results', []))
        return f'联网搜索到 {count} 条结果'
    if name == 'fetch_webpage':
        length = result.get('length', 0)
        return f'已抓取网页 ({length} 字符)'
    if name == 'analyze_topic':
        total = result.get('total_articles', 0)
        events = len(result.get('timeline', []))
        return f'分析完成: {total} 篇文章, {events} 个时间节点'
    if name == 'generate_report':
        sections = result.get('suggested_sections', [])
        return f'报告结构: {len(sections)} 个章节'
    return f'{name} 完成'


def _maybe_generate_title(session, user_query: str, response_text: str):
    """Auto-generate a session title heuristically from the response.

    Tries to extract a meaningful title from the response content (e.g. the
    first markdown heading or the 核心摘要 section). Falls back to query
    truncation. No LLM call needed.
    """
    if session.title:
        return

    import re

    # Strategy 1: Extract first ## heading from the structured report
    heading_match = re.search(r'^##\s+(.+)$', response_text, re.MULTILINE)
    if heading_match:
        title = heading_match.group(1).strip()
        # Clean up: remove trailing punctuation, emojis
        title = re.sub(r'[：:…—\-–]$', '', title).strip()
        if 2 <= len(title) <= 30:
            session.title = title
            session.save(update_fields=['title'])
            return

    # Strategy 2: Extract content after "核心摘要" marker
    summary_match = re.search(
        r'核心摘要[：:\n]+(.+?)(?:\n|$)', response_text, re.DOTALL,
    )
    if summary_match:
        title = summary_match.group(1).strip()
        # Truncate to first sentence
        for sep in ['。', '！', '？', '\n']:
            idx = title.find(sep)
            if idx > 0:
                title = title[:idx]
        if 2 <= len(title) <= 30:
            session.title = title
            session.save(update_fields=['title'])
            return

    # Fallback: truncate the user query
    title = user_query.strip().replace('\n', ' ')[:50]
    if len(user_query.strip()) > 50:
        title += '...'
    session.title = title
    session.save(update_fields=['title'])
