# 新闻聚合平台 - 开发记录

## 项目概述

基于 Scrapy + Django + React 的全栈新闻聚合平台，支持8个新闻源爬取、向量语义搜索、定时调度和开机自启。

---

## 技术栈

| 层级 | 技术 | 说明 |
|------|------|------|
| 爬虫 | Scrapy | 8个新闻源，RSS/JSON API方式 |
| 后端 | Django 4.2 + DRF | REST API，SQLite3存储 |
| 向量搜索 | sentence-transformers + ChromaDB | 多语言语义检索，384维向量 |
| 前端 | React + Vite + TailwindCSS | 无限滚动、搜索模式切换 |
| 定时调度 | cron | 每天8-23点每2小时执行 |
| 服务端口 | 9527 | 避免常用端口冲突 |

---

## 新闻源

| 源 | 爬取方式 | 数据格式 | 分类逻辑 |
|----|----------|----------|----------|
| 新浪新闻 | JSON API (`feed.mix.sina.com.cn`) | JSON | 按lid: 国内/国际/社会 |
| BBC | RSS (`feeds.bbci.co.uk`) | XML | 按feed URL分类 |
| 路透社 | Google News RSS (`site:reuters.com`) | XML | 统一为"国际" |
| Hacker News | Firebase API (`hacker-news.firebaseio.com`) | JSON | 科技/创业/招聘/问答 |
| GitHub Trending | 静态HTML (`github.com/trending`) | HTML | 按语言分类 |
| Dev.to | REST API (`dev.to/api/articles`) | JSON | 前端/后端/DevOps/AI |
| TechCrunch | RSS (`techcrunch.com/feed/`) | XML | AI/创业/安全/区块链/产品 |
| ProductHunt | Atom Feed (`producthunt.com/feed`) | XML | 产品/AI/开发工具/SaaS |

---

## 数据库模型

```
Category: name, slug, description, created_at
Source:   name, url, logo, country, language, created_at
News:     title, content, author, publish_time,
          source(FK), category(FK), url(unique), cover_image, created_at
```

---

## API 端点

| 端点 | 方法 | 功能 | 参数 |
|------|------|------|------|
| `/api/news/` | GET | 新闻列表(分页) | page, page_size, search, mode, category, source |
| `/api/news/<id>/` | GET | 新闻详情 | - |
| `/api/categories/` | GET | 分类列表 | - |
| `/api/sources/` | GET | 来源列表 | - |

### 搜索模式

| mode | 说明 |
|------|------|
| `keyword` | 关键词搜索 (DRF icontains) |
| `semantic` | 语义搜索 (ChromaDB向量匹配) |
| `hybrid` | 混合搜索 (RRF融合，默认) |

---

## 向量语义搜索

### 架构

```
用户搜索 "AI安全风险"
       │
       ▼
  Django API (NewsListView)
       │
       ├── 关键词搜索 (icontains) ──→ 排序 A
       ├── 语义搜索 (ChromaDB)   ──→ 排序 B
       │
       ▼
  RRF融合排序 (Reciprocal Rank Fusion)
       │
       ▼
  返回排序后的News列表
```

### 关键组件

- **EmbeddingService** (`api/services/embedding.py`): 单例，加载 `paraphrase-multilingual-MiniLM-L12-v2` 模型，支持中英文，输出384维向量
- **VectorStoreService** (`api/services/vector_store.py`): ChromaDB持久化存储，cosine相似度，支持add/search/delete/batch
- **Pipeline集成** (`pipelines.py`): 新闻保存后自动生成向量写入ChromaDB
- **回填命令**: `python manage.py backfill_embeddings --batch-size=50`

### RRF融合算法

```python
def reciprocal_rank_fusion(keyword_ids, semantic_ids, k=60):
    scores = {}
    for rank, nid in enumerate(keyword_ids):
        scores[nid] = scores.get(nid, 0) + 1.0 / (k + rank + 1)
    for rank, nid in enumerate(semantic_ids):
        scores[nid] = scores.get(nid, 0) + 1.0 / (k + rank + 1)
    return sorted(scores, key=scores.get, reverse=True)
```

---

## 定时调度

### Cron配置

```
# 每天8~23点，每2小时执行一次
0 8,10,12,14,16,18,20,22 * * * /root/news-aggregator/scripts/crawl_cron.sh
```

### 爬取脚本 (`scripts/crawl_cron.sh`)

- 执行 `python manage.py crawl all`
- 日志写入 `logs/crawl.log`
- 检测Django服务存活，挂了自动拉起

### 管理命令

```bash
python manage.py crawl          # 爬取所有源
python manage.py crawl sina     # 爬取指定源
python manage.py backfill_embeddings  # 回填向量数据
```

---

## 开机自启

通过 `~/.zshrc` 实现，打开Termux时自动：

1. 启动 `crond` 守护进程
2. 检测Django是否在运行，未运行则自动拉起 (端口9527)

---

## 前端功能

- **新闻列表**: 无限滚动加载，3列网格布局
- **搜索**: 防抖300ms，支持关键词/语义/混合三种模式切换
- **分类筛选**: 蓝色pill按钮
- **来源筛选**: 绿色pill按钮
- **新闻详情**: 标题、内容、来源、时间、封面图、原文链接

---

## 遇到的问题及解决方案

| 问题 | 原因 | 解决方案 |
|------|------|----------|
| Django ORM在Scrapy中报 `SynchronousOnlyOperation` | Scrapy异步上下文调用同步ORM | 用 `@sync_to_async` 包装 |
| Playwright系统依赖无法安装 | root环境下apt-get受限 | 改用RSS/JSON API替代页面爬取 |
| Vite `ERR_SYSTEM_ERROR` | `--host 0.0.0.0` 触发网络接口检测失败 | 改用 `--host 127.0.0.1` |
| ProductHunt 403 | 页面/非官方API均被拦截 | 发现Atom Feed `/feed` 端点可用 |
| Scrapy `no active project` | 运行目录不对 | 从 `crawler/` 目录运行，设置 `PYTHONPATH=.` |

---

## 项目结构

```
news-aggregator/
├── backend/
│   ├── newsaggregator/          # Django项目配置
│   ├── api/
│   │   ├── models.py            # Category, Source, News
│   │   ├── serializers.py       # DRF序列化器
│   │   ├── views.py             # API视图 + 混合搜索
│   │   ├── urls.py
│   │   ├── admin.py
│   │   ├── services/
│   │   │   ├── embedding.py     # EmbeddingService (sentence-transformers)
│   │   │   └── vector_store.py  # VectorStoreService (ChromaDB)
│   │   └── management/commands/
│   │       ├── crawl.py         # 爬虫管理命令
│   │       └── backfill_embeddings.py  # 向量回填命令
│   ├── manage.py
│   └── requirements.txt
├── crawler/
│   ├── scrapy.cfg
│   └── news_crawler/
│       ├── items.py
│       ├── pipelines.py         # Django ORM存储 + 向量写入
│       ├── settings.py
│       └── spiders/
│           ├── sina_spider.py
│           ├── bbc_spider.py
│           ├── reuters_spider.py
│           ├── hackernews_spider.py
│           ├── github_spider.py
│           ├── devto_spider.py
│           ├── techcrunch_spider.py
│           └── producthunt_spider.py
├── frontend/
│   └── src/
│       ├── components/          # Header, SearchBar, NewsCard, CategoryFilter, SourceFilter, LoadingSpinner
│       ├── pages/               # NewsList, NewsDetail
│       ├── services/api.js
│       └── App.jsx
├── scripts/
│   └── crawl_cron.sh            # 定时爬取脚本
├── chroma_data/                  # ChromaDB向量数据 (gitignore)
├── logs/                         # 运行日志 (gitignore)
└── .gitignore
```

---

## GitHub仓库

https://github.com/CoderLambert/news-aggregator
