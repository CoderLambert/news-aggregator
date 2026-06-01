# 新闻聚合器：全文抓取第一阶段实现总结

> 项目：`/root/news-aggregator`  
> 主题：Scrapy-backed 真实全文抓取 API、Markdown 转换、批量补抓基础设施  
> 状态：第一阶段已完成，后续进入“站点规则 + 状态追踪 + 自动批量补抓”阶段

## 1. 背景

此前“加载原文”主要依赖 Jina Reader：

```text
https://r.jina.ai/{source_url}
```

当外部站点或 Jina 到源站链路出现 `Connection reset by peer`、timeout、TLS reset 等问题时，页面会出现“获取失败”。

曾经短暂尝试过“用标题/摘要生成降级内容并写入 `full_content`”，但这个方案已经被废弃，因为它会污染 `full_content` 的语义。

现在的原则是：

> `News.full_content` 只能保存真实抓取到的原文正文 Markdown。摘要、标题拼接、AI 生成内容、验证内容都不能作为全文降级写入。

## 2. 第一阶段目标

第一阶段目标是搭建一套可扩展的真实全文抓取架构：

1. 统一所有全文抓取入口。
2. 优先 Jina Reader，失败后使用自有 Scrapy/HTTP 抓取链路。
3. 将 HTML 正文转为 Markdown。
4. 增加质量校验，防止误抓导航、页脚、摘要、广告内容。
5. 提供单 URL 爬虫 API。
6. 提供批量补抓命令。
7. 所有失败都保持 `full_content` 为空，方便后续重试。

## 3. 当前实现架构

统一入口：

```python
from api.services.article_fetcher import fetch_article_markdown

result = fetch_article_markdown(
    news.url,
    expected_title=news.title,
    summary=news.content,
)
```

返回：

```python
FetchResult(
    ok=True,
    provider='jina' | 'scrapy_cli' | 'scrapy_http',
    url='...',
    title='...',
    canonical_url='...',
    markdown='...',
    quality_score=0.86,
    error='',
)
```

失败时抛出：

```python
FetchError
```

调用方必须遵守：

```python
try:
    result = fetch_article_markdown(...)
    news.full_content = result.markdown
    news.save(...)
except FetchError:
    # 返回错误 / 记录日志，但不要写 fake full_content
```

## 4. 新增文件

### 4.1 服务层

```text
backend/api/services/article_fetcher/
├── __init__.py
├── core.py
├── types.py
├── providers.py
├── extractors.py
└── validators.py
```

职责：

| 文件 | 作用 |
|---|---|
| `types.py` | `FetchResult`、`FetchError`、Provider Protocol |
| `core.py` | provider chain 编排、统一入口 `fetch_article_markdown()` |
| `providers.py` | `JinaProvider`、`ScrapySubprocessProvider`、`ScrapyHTTPProvider` |
| `extractors.py` | HTML 正文提取、站点选择器、HTML → Markdown |
| `validators.py` | 标题、长度、域名、摘要相似度、噪音比例校验 |

### 4.2 管理命令

```text
backend/api/management/commands/fetch_article_url.py
backend/api/management/commands/fetch_full_content.py
```

| 命令 | 作用 |
|---|---|
| `fetch_article_url` | 单 URL 爬虫 API，输出 JSON |
| `fetch_full_content` | 批量补抓缺失的全文 |

### 4.3 测试

```text
backend/api/tests/test_article_fetcher.py
backend/api/tests/test_fetch_full.py
backend/api/tests/test_fetch_full_command.py
backend/api/tests/test_chat_context.py
backend/api/tests/test_suggested_questions.py
```

覆盖内容包括：

- provider chain fallback
- 全部失败时不写 `full_content`
- HTML 正文提取和 Markdown 转换
- 摘要型内容拒绝保存
- 手动加载原文接口
- 批量补抓命令
- 聊天/推荐问题自动补全文
- Scrapy 子进程 JSON 解析

## 5. Provider Chain

当前顺序：

```text
JinaProvider
  ↓ 失败
ScrapySubprocessProvider
  ↓ 失败
ScrapyHTTPProvider
  ↓ 失败
FetchError
```

### 5.1 JinaProvider

职责：

- 请求 `https://r.jina.ai/{url}`
- 带重试
- 提取 `Markdown Content:`
- 调用现有 `clean_content(markdown, url)` 清理 GitHub/Jina 噪音
- 通过质量校验后返回

优点：

- 对很多新闻站可直接返回 Markdown
- 不需要自己解析复杂 HTML
- 对 GitHub README 等页面通常效果不错

限制：

- Jina 到源站链路可能被 reset
- 某些站点会返回过多页面 chrome
- 对源站限制无控制能力

### 5.2 ScrapySubprocessProvider

职责：

- 通过子进程调用爬虫 API：

```bash
python manage.py fetch_article_url "https://example.com/article" --expected-title "Article title"
```

- 解析 JSON 输出
- 将结果作为 provider 返回

为什么用子进程：

Scrapy 基于 Twisted reactor。不要在 Django 长期运行进程里直接调用：

```python
CrawlerProcess().start()
```

否则容易遇到：

```text
reactor cannot be restarted
```

子进程边界的好处：

- Django 主进程稳定
- Scrapy/Twisted 生命周期独立
- 子进程崩溃不会拖垮 API
- 后续可以替换为真正 Scrapy spider/worker

### 5.3 ScrapyHTTPProvider

职责：

- 作为 in-process fallback
- 使用 crawler-like headers 直连源站 HTML
- 复用 `extractors.py` 和 `validators.py`

它不是最终形态，但提供一个轻量 fallback。后续可以逐步把重点站点迁移到真正 Scrapy spider 或 domain-specific extractor。

## 6. HTML → Markdown 提取逻辑

文件：

```text
backend/api/services/article_fetcher/extractors.py
```

主要逻辑：

1. 用 BeautifulSoup 解析 HTML。
2. 删除噪音节点：
   - `script`
   - `style`
   - `nav`
   - `footer`
   - `header`
   - `aside`
   - newsletter
   - subscribe
   - cookie
   - related/recommended
   - comments
3. 选择正文节点：
   - 站点专用 selector
   - `article`
   - `main`
   - `[role="main"]`
   - `.article-content`
   - `.entry-content`
   - `.post-content`
4. 转 Markdown：
   - h1-h6
   - p
   - a
   - strong/em/code
   - ul/ol/li
   - blockquote
   - pre/code block
   - table

当前已预置站点规则：

```python
ARTICLE_SELECTORS_BY_DOMAIN = {
    'theregister.com': ['article', '#body', '.article_body', '.body'],
    'techcrunch.com': ['article', '.article-content', '.entry-content'],
    'bbc.com': ['article', 'main'],
    'bbc.co.uk': ['article', 'main'],
    'dev.to': ['article', '#article-body', '.crayons-article__body'],
}
```

后续站点专项优化就从这里扩展。

## 7. 质量校验

文件：

```text
backend/api/services/article_fetcher/validators.py
```

校验项：

1. 正文长度不能太短。
2. 内容不能和列表摘要高度相似。
3. 正文必须明显长于摘要。
4. canonical URL 不能明显跨域。
5. 标题/H1 和数据库标题要有相似度，或标题关键词出现在正文中。
6. 页面 chrome / 噪音比例不能太高。

校验失败的 provider 结果会被拒绝，并继续尝试下一个 provider。

如果所有 provider 都失败，则抛 `FetchError`。

## 8. API 接入点

### 8.1 手动加载原文

接口：

```text
POST /api/news/<id>/fetch-full/
```

行为：

1. 如果已有 `full_content`，直接返回缓存。
2. 否则调用 `fetch_article_markdown()`。
3. 成功后写入 `news.full_content`。
4. 失败返回 502，且不写 `full_content`。

### 8.2 AI 聊天自动补全文

`ensure_full_content(news)` 也改为使用 `fetch_article_markdown()`。

这意味着用户不需要先点“加载原文”，聊天和推荐问题会先尝试自动获取真实全文。

如果自动抓取失败：

- 记录 warning
- 不写 `full_content`
- 聊天仍然可以用 `content/content_zh` 作为临时上下文
- 摘要不会冒充全文

### 8.3 推荐问题自动补全文

推荐问题也走同样的 `ensure_full_content(news)` 逻辑。

## 9. 命令使用

### 9.1 单 URL 爬虫 API

```bash
cd /root/news-aggregator/backend
python manage.py fetch_article_url "https://example.com/article" --expected-title "Article title"
```

输出 JSON：

```json
{
  "ok": true,
  "provider": "scrapy_cli",
  "url": "https://example.com/article",
  "canonical_url": "https://example.com/article",
  "title": "Article title",
  "markdown": "...",
  "quality_score": 0.86,
  "error": ""
}
```

### 9.2 批量全文补抓

```bash
cd /root/news-aggregator/backend
python manage.py fetch_full_content --limit 20
python manage.py fetch_full_content --limit 20 --source "GitHub Trending"
python manage.py fetch_full_content --limit 20 --dry-run
python manage.py fetch_full_content --limit 20 --force
```

说明：

| 参数 | 作用 |
|---|---|
| `--limit 20` | 最多处理 20 篇 |
| `--source "GitHub Trending"` | 只处理某个来源 |
| `--dry-run` | 只显示候选，不抓取、不保存 |
| `--force` | 即使已有 `full_content` 也重新抓 |

## 10. 验证结果

后端测试：

```text
75 passed
```

Django check：

```text
System check identified no issues
```

实际验证：

1. `fetch_article_url` 可对 GitHub repo 页面提取约 46KB Markdown。
2. `fetch_full_content --limit 1` 可成功写入真实 Markdown。
3. 失败路径不会污染 `full_content`。

## 11. 当前限制

第一阶段仍有这些限制：

1. 还没有数据库级抓取状态字段。
2. 批量补抓还不是后台自动调度。
3. 站点专用提取规则还比较初始。
4. 还没有可视化抓取失败原因。
5. 还没有按来源统计 provider 成功率。
6. 还没有对 JS-heavy 页面接入远程浏览器/第三方抓取服务。

这些就是下一阶段的重点。
