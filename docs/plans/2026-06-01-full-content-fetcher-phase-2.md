# 新闻聚合器全文补抓系统第二阶段实施规划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将第一阶段的真实全文抓取服务扩展为可观测、可重试、可批量运行、可按站点定制规则的全文补抓系统。

**Architecture:** 保持 `fetch_article_markdown()` 作为唯一抓取入口；在模型层增加抓取状态字段；在服务层增加站点规则注册表和质量报告；在管理命令层增加自动补抓、失败重试和统计；前端只展示真实 `full_content`，失败时展示可重试状态，不展示生成降级内容。

**Tech Stack:** Django 5、SQLite、Scrapy/Twisted 子进程边界、BeautifulSoup、pytest、React/Vite 前端、现有 VitePress 文档站。

---

## 非谈判原则

1. `News.full_content` 只能保存真实抓取到的原文正文 Markdown。
2. 失败时不得写入摘要、标题拼接、AI 生成内容或“验证内容”。
3. 所有入口必须走 `api.services.article_fetcher.fetch_article_markdown()`。
4. 批量补抓必须有状态追踪、错误记录、重试控制，不能无限重试同一失败 URL。
5. 每个阶段先写测试，再写实现。

---

## 当前基线

第一阶段已经完成：

```text
JinaProvider
  ↓
ScrapySubprocessProvider
  ↓
ScrapyHTTPProvider
  ↓
FetchError
```

相关路径：

```text
backend/api/services/article_fetcher/
backend/api/management/commands/fetch_article_url.py
backend/api/management/commands/fetch_full_content.py
backend/api/tests/test_article_fetcher.py
backend/api/tests/test_fetch_full.py
backend/api/tests/test_fetch_full_command.py
```

当前验证：

```bash
cd /root/news-aggregator/backend
python -m pytest api/tests -q
python manage.py check
```

预期：

```text
75 passed
System check identified no issues
```

---

## Task 1: 增加全文抓取状态字段

**目标：** 让每篇新闻记录自己的全文抓取状态、失败原因、provider、质量分、重试次数，为批量补抓和前端展示打基础。

**Files:**
- Modify: `backend/api/models.py`
- Modify: `backend/api/serializers.py`
- Create: Django migration under `backend/api/migrations/`
- Test: `backend/api/tests/test_full_content_status_model.py`

**建议字段：**

```python
FULL_CONTENT_STATUS_CHOICES = [
    ('pending', 'Pending'),
    ('fetching', 'Fetching'),
    ('success', 'Success'),
    ('failed', 'Failed'),
    ('network_error', 'Network Error'),
    ('validation_failed', 'Validation Failed'),
]

full_content_fetch_status = models.CharField(
    max_length=32,
    choices=FULL_CONTENT_STATUS_CHOICES,
    default='pending',
)
full_content_fetch_error = models.TextField(blank=True, default='')
full_content_fetch_provider = models.CharField(max_length=64, blank=True, default='')
full_content_quality_score = models.FloatField(null=True, blank=True)
full_content_retry_count = models.PositiveIntegerField(default=0)
last_full_content_attempt = models.DateTimeField(null=True, blank=True)
```

**Step 1: 写失败测试**

测试内容：

```python
def test_news_has_full_content_fetch_status_defaults(db):
    news = News.objects.create(...)
    assert news.full_content_fetch_status == 'pending'
    assert news.full_content_fetch_error == ''
    assert news.full_content_fetch_provider == ''
    assert news.full_content_retry_count == 0
```

**Step 2: 运行测试确认失败**

```bash
cd /root/news-aggregator/backend
python -m pytest api/tests/test_full_content_status_model.py -q
```

预期：字段不存在，测试失败。

**Step 3: 修改模型并生成迁移**

```bash
python manage.py makemigrations api
```

**Step 4: Serializer 暴露字段**

`NewsDetailSerializer` 和列表必要字段中返回：

```python
full_content_fetch_status
full_content_fetch_error
full_content_fetch_provider
full_content_quality_score
full_content_retry_count
last_full_content_attempt
```

**Step 5: 运行测试**

```bash
python -m pytest api/tests/test_full_content_status_model.py -q
python manage.py check
```

---

## Task 2: 抽象状态更新服务

**目标：** 避免 view/command 到处手写状态字段更新。

**Files:**
- Create: `backend/api/services/full_content_status.py`
- Test: `backend/api/tests/test_full_content_status_service.py`

**建议 API：**

```python
def mark_fetching(news): ...
def mark_success(news, result): ...
def mark_failed(news, error, status='failed', provider=''): ...
def classify_fetch_error(error_or_result) -> str: ...
```

**状态语义：**

| 情况 | status |
|---|---|
| 开始抓取 | `fetching` |
| 成功保存 | `success` |
| TCP reset / timeout / DNS / SSL | `network_error` |
| provider 返回短内容 / 摘要 / 标题不匹配 | `validation_failed` |
| 其他异常 | `failed` |

**Step 1: 测试成功状态**

```python
def test_mark_success_records_provider_score_and_timestamp(news):
    result = FetchResult(ok=True, provider='scrapy_cli', markdown='...', quality_score=0.88)
    mark_success(news, result)
    news.refresh_from_db()
    assert news.full_content_fetch_status == 'success'
    assert news.full_content_fetch_provider == 'scrapy_cli'
    assert news.full_content_quality_score == 0.88
```

**Step 2: 测试失败状态**

```python
def test_mark_failed_increments_retry_count(news):
    mark_failed(news, RuntimeError('reset'), status='network_error')
    news.refresh_from_db()
    assert news.full_content_fetch_status == 'network_error'
    assert news.full_content_retry_count == 1
```

**Step 3: 实现服务**

注意：每个函数都应 `save(update_fields=[...])`，避免写入无关字段。

---

## Task 3: 接入状态更新到手动加载原文

**目标：** `POST /api/news/<id>/fetch-full/` 抓取时状态可见。

**Files:**
- Modify: `backend/api/views.py`
- Test: `backend/api/tests/test_fetch_full.py`

**行为：**

1. 开始抓取：`mark_fetching(news)`
2. 成功：写 `full_content`，然后 `mark_success(news, result)`
3. 失败：`mark_failed(news, error, classified_status)`，不写 `full_content`

**Step 1: 写测试**

```python
def test_fetch_full_records_success_status(client, news):
    result = FetchResult(ok=True, provider='scrapy_cli', markdown='REAL BODY', quality_score=0.9)
    with patch('api.views.fetch_article_markdown', return_value=result):
        resp = client.post(f'/api/news/{news.pk}/fetch-full/')
    news.refresh_from_db()
    assert resp.status_code == 200
    assert news.full_content == 'REAL BODY'
    assert news.full_content_fetch_status == 'success'
    assert news.full_content_fetch_provider == 'scrapy_cli'
```

**Step 2: 失败测试**

```python
def test_fetch_full_records_network_error_without_persisting(client, news):
    with patch('api.views.fetch_article_markdown', side_effect=FetchError('reset')):
        resp = client.post(f'/api/news/{news.pk}/fetch-full/')
    news.refresh_from_db()
    assert resp.status_code == 502
    assert news.full_content == ''
    assert news.full_content_fetch_status in ['network_error', 'failed']
    assert news.full_content_retry_count == 1
```

---

## Task 4: 接入状态更新到聊天自动补全文

**目标：** 聊天/推荐问题自动补全文失败也能记录状态，但不能影响聊天可用性。

**Files:**
- Modify: `backend/api/views.py` (`ensure_full_content`)
- Test: `backend/api/tests/test_chat_context.py`

**行为：**

- 成功：保存 `full_content` + 标记 success。
- 失败：标记 failed/network_error，但 `ensure_full_content` 不抛异常。
- `pick_chat_context()` 仍按 `full_content_zh → full_content → content_zh → content`。

**测试重点：**

```python
def test_chat_auto_fetch_failure_records_status_but_still_responds(...):
    ...
```

---

## Task 5: 增强批量补抓命令

**目标：** 批量命令支持状态过滤、错误重试、失败上限。

**Files:**
- Modify: `backend/api/management/commands/fetch_full_content.py`
- Test: `backend/api/tests/test_fetch_full_command.py`

**新增参数：**

```bash
--status pending,network_error,failed,validation_failed
--max-retries 3
--older-than-minutes 30
--source "TechCrunch"
--provider-report
```

**选择逻辑：**

默认处理：

```text
full_content = ''
AND status in ['pending', 'network_error', 'failed']
AND retry_count < max_retries
```

不默认处理：

```text
validation_failed
```

因为 validation_failed 通常是规则问题，不应反复抓同一个错误结果。

**测试：**

1. `--dry-run` 不调用 provider。
2. `--status network_error` 只处理网络错误。
3. `--max-retries 3` 跳过 retry_count >= 3。
4. 成功后状态变 success。
5. 失败后 retry_count +1。

---

## Task 6: 站点规则注册表 v1

**目标：** 为每个网站单独设计正文提取规则，先从重点来源开始。

**Files:**
- Modify/Create: `backend/api/services/article_fetcher/site_rules.py`
- Modify: `backend/api/services/article_fetcher/extractors.py`
- Test: `backend/api/tests/test_article_site_rules.py`

**建议结构：**

```python
@dataclass
class SiteRule:
    domains: list[str]
    selectors: list[str]
    remove_selectors: list[str] = field(default_factory=list)
    min_length: int = 500
    title_selectors: list[str] = field(default_factory=lambda: ['h1'])
```

注册表：

```python
SITE_RULES = [
    SiteRule(
        domains=['theregister.com'],
        selectors=['article', '#body', '.article_body'],
        remove_selectors=['.ad', '.related', '.comments'],
        min_length=800,
    ),
    ...
]
```

**首批站点：**

1. GitHub
2. The Register
3. TechCrunch
4. BBC
5. Dev.to
6. Reuters

**测试方式：**

使用本地 HTML fixture，不依赖外网。

```text
backend/api/tests/fixtures/articles/theregister.html
backend/api/tests/fixtures/articles/techcrunch.html
```

每个 fixture 测试：

- 能提取标题
- 能提取正文
- 不包含 nav/footer/subscribe/cookie
- Markdown 长度超过阈值

---

## Task 7: 保存 provider 和质量报告

**目标：** 后续能统计哪个 provider/站点效果最好。

**Files:**
- Modify: `backend/api/services/article_fetcher/types.py`
- Modify: `backend/api/services/article_fetcher/core.py`
- Modify: `backend/api/services/full_content_status.py`
- Test: `backend/api/tests/test_article_fetcher_quality_report.py`

**建议增强 `FetchResult`:**

```python
@dataclass
class FetchResult:
    ok: bool
    provider: str
    url: str = ''
    title: str = ''
    canonical_url: str = ''
    markdown: str = ''
    quality_score: float = 0.0
    error: str = ''
    validation_reasons: list[str] = field(default_factory=list)
    content_length: int = 0
    extractor: str = ''
```

**持久化到 News：**

- `full_content_fetch_provider`
- `full_content_quality_score`
- `full_content_fetch_error`

后续如果需要完整历史，再新增独立表 `FullContentFetchAttempt`。

---

## Task 8: 可观测统计命令

**目标：** 快速查看全文补抓覆盖率、失败原因、provider 成功率。

**Files:**
- Create: `backend/api/management/commands/full_content_stats.py`
- Test: `backend/api/tests/test_full_content_stats_command.py`

**命令：**

```bash
python manage.py full_content_stats
python manage.py full_content_stats --source "TechCrunch"
python manage.py full_content_stats --json
```

**输出内容：**

- 总文章数
- 已有 full_content 数量/比例
- status 分布
- source 分布
- provider 分布
- top 失败错误
- retry_count 分布

**JSON 输出示例：**

```json
{
  "total": 5120,
  "with_full_content": 840,
  "coverage": 0.164,
  "status": {
    "pending": 3000,
    "success": 840,
    "network_error": 200,
    "validation_failed": 80
  },
  "providers": {
    "jina": 600,
    "scrapy_cli": 220,
    "scrapy_http": 20
  }
}
```

---

## Task 9: 自动补抓调度脚本

**目标：** 为 cron/手动运行提供安全入口。

**Files:**
- Create: `scripts/fetch_full_content_cron.sh`
- Test manually with dry-run

**脚本行为：**

1. 检测网络。
2. 限流执行 `fetch_full_content`。
3. 输出日志到：

```text
logs/full_content_fetch.log
```

**脚本草案：**

```bash
#!/usr/bin/env bash
set -euo pipefail
cd /root/news-aggregator/backend
mkdir -p ../logs
python manage.py fetch_full_content \
  --limit "${FULL_CONTENT_FETCH_LIMIT:-20}" \
  --max-retries "${FULL_CONTENT_MAX_RETRIES:-3}" \
  2>&1 | tee -a ../logs/full_content_fetch.log
```

**注意：** 第一版不必马上创建 cronjob；先保证脚本可手动运行。

---

## Task 10: 前端状态展示

**目标：** 用户知道“加载原文”失败原因和是否可重试，但不会看到伪原文。

**Files:**
- Modify: `frontend/src/components/news-detail/FullContentSection.jsx` 或对应组件
- Modify: `frontend/src/hooks/useFullArticle.js`
- Test: frontend Vitest

**显示逻辑：**

| status | UI |
|---|---|
| `pending` | 显示“加载原文”按钮 |
| `fetching` | 显示 loading |
| `success` | 显示全文 |
| `network_error` | 显示“网络/源站暂不可达，可稍后重试” |
| `validation_failed` | 显示“抓取内容未通过真实性校验，等待规则优化” |
| `failed` | 显示通用失败和重试按钮 |

**重要：** 页面摘要区域仍然可以显示 `content/content_zh`，但全文区域不能把摘要渲染成原文。

---

## Task 11: 站点规则迭代流程

**目标：** 建立后续“每个网站一个规则”的工作流。

**流程：**

1. 从 `full_content_stats` 找出失败率高的 source/domain。
2. 保存 2-3 个失败 HTML fixture。
3. 写 `test_article_site_rules.py` 失败测试。
4. 增加/调整 `SiteRule`。
5. 跑测试确认 Markdown 提取准确。
6. 用 `fetch_full_content --source X --limit 10 --force` 小批验证。
7. 检查 `full_content_quality_score` 和人工抽查 1-2 篇。

**首批优先级：**

1. GitHub Trending：README 提取质量和代码块清理。
2. The Register：正文 selector 和广告/相关链接清理。
3. TechCrunch：文章正文和 newsletter 清理。
4. Dev.to：正文 + code block 保留。
5. BBC：正文段落 + media caption 处理。
6. Reuters：正文段落和 paywall/blocked 提示识别。

---

## Task 12: 最终验证清单

每次阶段完成后运行：

```bash
cd /root/news-aggregator/backend
python -m pytest api/tests -q
python manage.py check
python manage.py fetch_full_content --limit 3 --dry-run
python manage.py full_content_stats --json
```

如果改了前端：

```bash
cd /root/news-aggregator/frontend
npx eslint src --max-warnings=0
npx vitest run
npm run build
```

重启：

```bash
kill -9 $(lsof -ti:9527) 2>/dev/null
sleep 2
cd /root/news-aggregator/backend
python manage.py runserver 0.0.0.0:9527
```

Termux 打开：

```bash
aopen 9527
```

---

## 推荐提交拆分

1. `feat: 增加全文抓取状态字段`
2. `refactor: 统一全文抓取状态更新服务`
3. `feat: 批量全文补抓支持状态过滤和重试`
4. `feat: 增加站点规则注册表和首批规则`
5. `feat: 增加全文抓取统计命令`
6. `feat: 前端展示全文抓取状态`
7. `docs: 更新全文补抓系统规划文档`

---

## 成功标准

第二阶段完成后应达到：

1. 每篇文章有明确全文抓取状态。
2. 批量补抓可安全运行，不污染数据库。
3. 抓取失败可分类、可统计、可重试。
4. 重点站点有独立正文提取规则。
5. 前端能显示抓取状态和可重试错误。
6. 后续可以通过统计数据驱动站点规则优化。
7. 所有测试通过，Django check 通过。
