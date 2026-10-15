# NewsHub — AI 驱动的智能新闻聚合器

> 一站式科技资讯聚合 + AI 翻译 + 智能对话 + 深度研究助手，聚焦中文技术社区阅读体验。

## ✨ 功能概览

| 模块 | 能力 |
|------|------|
| **个人频道** | 账号同步订阅与一层分组，支持多组归属、批量操作和首页范围筛选 |
| **新闻聚合** | Scrapy 爬虫抓取多源科技资讯，自动分类存储，支持分页浏览 |
| **AI 翻译** | 用户自带 Key，经 LiteLLM 统一路由到主流模型厂商 |
| **智能助手** | 基于文章全文的多轮对话，自动抓取原文，推荐问题一键换批 |
| **深度研究** | AI Research Agent — LLM 意图分析 + 本地语义搜索 + 多步骤深度分析 |
| **本地搜索** | 关键词 / 语义 / 混合三种模式，支持结果分页 |
| **页内搜索** | Ctrl+F 式全文高亮 + 上下跳转计数 |
| **文章目录** | 右侧悬浮 TOC 面板，IntersectionObserver 实时追踪当前阅读位置 |
| **语音播报** | 全局 TTS 语音播放器，支持多音色、多语速、播放范围选择 |
| **代码块复制** | Markdown 代码块一键复制按钮 |
| **吉祥物交互** | "小闻" 小狐狸动画表情，6 种心情状态随对话切换 |

## 个人频道与首页阅读范围

首页的“管理频道”打开 `/channels`。登录用户可以订阅现有来源，创建 1–40 字的个人分组，同一频道可加入多个分组。取消订阅会移除所有分组归属；删除分组和从分组移除频道均保留订阅。停用来源不能新增订阅，已有订阅仍可阅读历史文章。

首页支持 `scope=all|subscribed|ungrouped|group`，分组范围还需 `group_id`。范围与 `source`、`category` 和关键词/语义/混合搜索取交集，空范围保持零结果。切换范围保留搜索与分类、清除临时来源并回到第一页；清除筛选保留范围。URL 优先于账号保存的上次范围，支持刷新与浏览器历史。检索中心和收藏页保持独立，个人订阅不会改变站点采集计划。

迁移 `0039`、`0040` 添加账号配置和缺失的受支持来源，不修改已有文章、用户或来源属性，也不自动订阅。更新来源策略/爬虫注册目录后，可执行 `python backend/manage.py sync_channel_catalog` 补充缺失频道；目录 GET 只读。公开只读模式仅提供全部资讯与频道目录。

个人 API 使用现有会话认证与 CSRF，每个账号只能访问自己的分组，越权返回 404：

| 接口 | 方法与请求 |
| --- | --- |
| `/api/me/channel-subscriptions/` | GET；POST `{action: "subscribe"|"unsubscribe", source_ids: [来源 ID]}`；POST `{action: "set_groups", source_ids: [...], group_ids: [...]}` 设置频道的全部分组归属 |
| `/api/me/channel-groups/` | GET；POST `{name: "AI"}` |
| `/api/me/channel-groups/<id>/` | GET、DELETE；PATCH `{name?: "新名称", source_ids?: [...]}` 替换成员，或 `{add_source_ids: [...]}` / `{remove_source_ids: [...]}` 批量增减 |
| `/api/me/news-preferences/` | GET；PATCH `{scope: "group", group_id: ID}`，其他范围的 `group_id` 可为 null |

## 新能源、医疗 RSS 与频道地区

频道新增独立的 `region=domestic|international`，按服务市场与版本划分；语言、内容分类和来源类型保持独立。首页、频道管理及检索中心均支持国内／国际筛选，首页地区与个人阅读范围取交集。URL 保存地区；切换地区清除临时来源并重置分页，保留搜索、分类和个人分组；清除筛选保留个人阅读范围。

迁移 `0041/0042` 回填现有频道地区并增加 12 个新能源、14 个医疗来源配置，以及“新能源”“医疗健康”分类。FDA 官方 RSS 当前本机返回 404，作为待验证候选，不注册采集或开放新增订阅；其他 25 个 RSS 已通过独立 XML 解析检查，实际采集状态仍以爬虫结果为准。IT之家与爱范儿仅接收标题、摘要和标签命中新能源规则的条目。各来源的官方地址和规则集中在 `backend/api/services/sector_feeds.py`。

Energy-Storage.news、Windpower Monthly 和医疗媒体、期刊仅展示 RSS 标题、摘要及真实原文链接，后端禁止正文获取；FDA、NIH 仅使用 RSS 公开提供的内容。未提供摘要时不生成占位内容。医疗资讯和相关 AI 回答标注“新闻资讯，不构成医疗建议”，单篇助手与研究助手使用实际文章 URL 展示来源链接。

`/api/sources/` 支持 `region` 并返回地区和阅读策略；`/api/news/` 支持同名地区参数，并返回 `source_region`、`channel_ids`、`channel_names`、`is_medical`、`reading_policy`。同一文章在多个频道收录时保持主来源和单篇去重，按所有频道归属参与订阅、来源和分类筛选。openFDA、PubMed、ClinicalTrials.gov 数据专题不在本轮范围。

## 🛠 技术栈

```
Frontend:  React 19 + Vite 8 + Tailwind 4 + shadcn/ui + React Compiler
Backend:   Django 6 + DRF + SQLite + Scrapy
AI:        LiteLLM Gateway + 用户自带 API Key（受控的主流厂商白名单）
向量检索:   ChromaDB（语义搜索支持）
测试:      Vitest + Testing Library (前端) | pytest-django (后端)
```

## 📋 环境要求

- **Docker 部署**：Docker Engine + Compose v2 + Git LFS
- **本地开发**：Python ≥ 3.11、Node.js ≥ 20（推荐 22+）、npm ≥ 9
- AI 功能可使用本地 ChatGPT 订阅连接，或由登录用户在设置页配置自己的厂商 API Key 与 Model ID

## 🚀 快速开始

> 完整的初始化、开发/生产启动、爬虫、测试、数据和故障排查说明见 [启动与运维说明](./docs/startup.md)。

不安装 Docker 的单机部署（前端构建、Waitress、SQLite 数据迁移与全文 Worker）见 [源码部署说明](./docs/deployment/local-source.md)。

### Docker 一键部署（推荐）

语义索引的同步、恢复和管理方案见 [docs/semantic-index-sync-design.md](docs/semantic-index-sync-design.md)。

从克隆到健康服务只需要准备 `.env`，Compose 会构建前端和后端、自动执行数据库迁移，并启动 Waitress、爬虫 Worker、全文 Worker 与语义索引 Worker：

```bash
git clone https://github.com/CoderLambert/news-aggregator.git
cd news-aggregator
git lfs install
git lfs pull

cp .env.example .env
# 编辑 .env，至少设置一个长期不变的 DJANGO_SECRET_KEY

docker compose up -d --build --wait
curl -f http://127.0.0.1:9527/api/news/
```

访问 <http://127.0.0.1:9527>。Docker 生产构建把 React 页面和 Django API 放在同一个端口，不使用开发端口 `5173`。

数据默认保存在宿主机，不随容器删除：

| 数据 | 宿主机位置 | 容器位置 |
| --- | --- | --- |
| SQLite、WAL、TTS 缓存 | `./backend/` | `/app/backend/` |
| ChatGPT 部署实例标识 | `./backend/.runtime/` | `/app/backend/.runtime/` |
| ChromaDB 向量数据 | `./chroma_data/` | `/app/chroma_data/` |
| 爬虫运行日志 | `./logs/` | `/app/logs/` |
| Hugging Face 模型缓存 | Docker volume `news-aggregator_huggingface-cache` | `/root/.cache/huggingface` |

接管已有数据库时，先停止原后端和爬虫写入者，再把 `db.sqlite3` 及仍存在的 `db.sqlite3-wal`、`db.sqlite3-shm` 一起放入 `backend/`，然后启动 Compose。保存 ChatGPT 订阅连接时还必须沿用原来的 `DJANGO_SECRET_KEY` 或 `CHATGPT_TOKEN_ENCRYPTION_KEY`。如果目标是新机器/新 VM，不要复制 `backend/.runtime/chatgpt-deployment-id`；新部署会生成自己的 OAuth host ID。同一部署内所有站内用户共享这个非敏感 host 标识，但各自的 `client_id` 和 Token 分开保存。

常用维护命令：

```bash
docker compose ps
docker compose logs -f app crawler indexer
docker compose restart app crawler indexer
docker compose down                    # 数据仍保留

# 更新代码和镜像；容器启动时会自动应用新迁移
git pull --ff-only
git lfs pull
docker compose up -d --build --wait
```

Compose 默认在 crawler Worker 启动后抓取一次，之后每小时抓取；indexer Worker 会自动维护语义索引。`.env` 提供首次初始化值，运行后在 <http://127.0.0.1:9527/admin/crawlers> 调整爬虫和索引周期。创建超级管理员后，可在同一页面控制两类任务：

```bash
docker compose exec app python backend/manage.py createsuperuser
```

公开注册只会创建普通用户，不会授予爬虫管理权限。管理员使用同一个登录窗口；新管理员可通过上面的 `createsuperuser` 命令创建，已有账号则由部署者在服务端明确授予 `is_staff` 和 `is_superuser` 权限。

本地 Python/Node 开发方式如下。

### 1. 克隆项目

```bash
git clone https://github.com/CoderLambert/news-aggregator.git
cd news-aggregator
```

### 2. 后端配置

```bash
cd backend

# 创建虚拟环境
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt

# 数据库迁移
python manage.py migrate

# 创建超级用户（可选，用于 admin 后台）
python manage.py createsuperuser
```

### 3. 配置环境变量

本机源码部署推荐直接复制 `.env.local.example`；它默认打开本机支持的功能。通用或容器配置继续参考 `.env.example`：

```bash
cp .env.local.example .env
```

```bash
# 必填：Django 密钥（生产环境务必自定义）
# 生成方式：python -c "from secrets import token_urlsafe; print(token_urlsafe(60))"
DJANGO_SECRET_KEY=你的密钥

# 可选：调试模式（默认开启）
DJANGO_DEBUG=1

# 可选：允许的主机（默认 *）
DJANGO_ALLOWED_HOSTS=*

# ====== LiteLLM BYOK 网关 ======
AI_BYOK_GATEWAY_URL=http://127.0.0.1:4000
AI_BYOK_GATEWAY_PROJECT_KEY=网关为本项目签发的受限虚拟Key
```

登录用户在设置页选择 OpenAI、Anthropic Claude、DeepSeek、Google Gemini、Qwen、GLM/Z.AI、Kimi/Moonshot、Mistral、Groq、xAI 或 OpenRouter，填写厂商 Model ID 和自己的 API Key。浏览器不能设置 Base URL 或 LiteLLM 路由前缀；服务端只允许受信厂商路由，Key 加密保存且不回显。

### 4. 前端构建

```bash
cd frontend

# 安装依赖
npm install

# 开发模式（Vite dev server，自动代理 /api → :9527）
npm run dev

# 或生产构建
npm run build
```

### 5. 启动服务

**一键启动（前端 + 后端 + 定时爬虫）**

```bash
./scripts/news start
# 访问 http://127.0.0.1:5173
```

查看状态和停止全部服务：

```bash
./scripts/news status
./scripts/news stop
```

**方式 A：开发模式（推荐）**

```bash
# 终端 1 — 启动后端
cd backend
source venv/bin/activate
python manage.py runserver 0.0.0.0:9527

# 终端 2 — 启动前端开发服务器
cd frontend
npm run dev
# 访问 http://127.0.0.1:5173
```

**方式 B：本机源码部署（Waitress + 静态文件）**

```bash
# 构建前端
cd frontend && npm run build

# 启动 Waitress 服务（自动加载前端 dist 目录）
pip install waitress
cd /path/to/news-aggregator
python start_waitress.py
# 访问 http://127.0.0.1:9527
```

此方式需要另起一个进程运行全文 Worker；已有数据库的迁移、端口切换和定时爬虫路径见[源码部署说明](./docs/deployment/local-source.md)。

### 6. 抓取新闻数据

```bash
cd backend
source venv/bin/activate

# 抓取所有源
python manage.py crawl all

# 抓取指定源
python manage.py crawl hackernews
```

全量抓取会逐个来源执行并共享持久化请求预算；只有每个来源都得到健康终态时才返回成功。

也可以手动执行一次全部爬虫：

```bash
# 使用项目提供的脚本
./scripts/crawl_cron.sh
```

持续定时抓取请使用统一命令：

```bash
./scripts/news start
```

## 🧪 测试

```bash
# 后端测试
cd backend
python -m pytest api/tests/ -v

# 前端测试
cd frontend
npm test -- --run

# 运行全部测试
./scripts/run_tests.sh
```

## 📁 项目结构

```
news-aggregator/
├── backend/                  # Django 后端
│   ├── api/
│   │   ├── models.py         # 数据模型（News, Source, Category, ChatSession, ResearchSession）
│   │   ├── views.py          # API 视图（CRUD + 翻译 + 聊天 + 研究）
│   │   ├── serializers.py    # DRF 序列化器
│   │   ├── services/
│   │   │   ├── llm_translator.py    # LLM 翻译 + 双 Provider Failover
│   │   │   ├── content_cleaner.py   # 内容清洗
│   │   │   ├── translation_jobs.py  # 后台翻译 Job 管理
│   │   │   └── research/            # Research Agent
│   │   │       ├── tools.py         # 研究工具集
│   │   │       └── __init__.py
│   │   └── tests/            # pytest 测试
│   ├── newsaggregator/       # Django 项目配置
│   │   └── settings.py
│   └── requirements.txt
├── frontend/                 # React 前端
│   ├── src/
│   │   ├── pages/            # 页面组件（Home, NewsDetail, LocalSearch）
│   │   ├── components/       # UI 组件
│   │   │   ├── ui/           # shadcn/ui 基础组件
│   │   │   ├── news-detail/  # 详情页子组件
│   │   │   ├── chat/         # AI 聊天组件
│   │   │   ├── research/     # 深度研究组件（BubbleButton, Header, Timeline）
│   │   │   └── Pagination.jsx # 响应式分页组件
│   │   ├── hooks/            # 自定义 Hooks
│   │   ├── services/         # API 服务层
│   │   ├── context/          # React Context（语言、认证、语音播放器）
│   │   └── constants/        # 常量定义（TTS 配置）
│   ├── vite.config.js        # Vite + React Compiler + 代理配置
│   └── package.json
├── crawler/                  # Scrapy 爬虫
│   └── news_crawler/
│       └── spiders/          # 各数据源 Spider
├── chroma_data/              # ChromaDB 运行时向量数据（Git 忽略）
├── backend/
│   └── db.sqlite3            # Django SQLite 数据库（LFS 管理）
├── scripts/                  # 运维脚本
│   ├── news-server           # Django 服务管理
│   ├── news-dev              # Vite 开发服务器管理
│   ├── news                  # 前端、后端、爬虫统一管理
│   ├── news-cron             # 项目级定时爬虫
│   ├── crawl_cron.sh         # 定时爬虫
│   └── run_tests.sh          # 全量测试
├── start_waitress.py         # Waitress 生产启动脚本
├── .env.example              # 环境变量模板
├── .gitattributes            # Git LFS 追踪规则
└── CHANGELOG.md              # 更新日志
```

## 🔑 API 接口一览

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/news/` | 新闻列表（分页、筛选、搜索） |
| GET | `/api/news/:id/` | 新闻详情 |
| POST | `/api/news/:id/fetch-full/` | 抓取完整原文 |
| POST | `/api/news/:id/translate/` | SSE 流式翻译 |
| POST | `/api/news/:id/chat/` | SSE 流式 AI 对话 |
| POST | `/api/news/:id/suggested-questions/` | 获取/刷新推荐问题 |
| POST | `/api/news/:id/speech/` | TTS 语音合成 |
| GET | `/api/categories/` | 分类列表 |
| GET | `/api/sources/` | 来源列表 |
| POST | `/api/research/` | 创建研究会话 |
| GET | `/api/research/:id/` | 获取研究会话 |
| POST | `/api/research/:id/query/` | 发送研究查询 |
| GET | `/api/search/` | 本地搜索（关键词/语义/混合） |

## ⚙️ 高级配置

### LLM Provider 路由

```
用户请求 → NewsHub 身份/权限检查 → LiteLLM 项目路由 → 用户选择的模型厂商
```

- 不使用站点级厂商 Key，也不跨厂商自动 fallback
- LiteLLM 项目虚拟 Key 与用户厂商 Key 分离
- SDK 与 Proxy 重试均关闭；结果不明时不会静默重复付费请求
- 上游失败返回脱敏提示，不向浏览器暴露技术错误或凭据

### React Compiler

项目已启用 React Compiler（Babel 插件），自动处理：
- 组件/ Hook 的 memoization（无需手写 `useMemo` / `useCallback` / `React.memo`）
- 编译器 Lint 规则：禁止 effect/timeout 内同步 `setState`（需 `queueMicrotask` 包裹）

### 翻译 Job 持久化

- 翻译过程在后台线程运行，页面刷新/关闭不影响
- 每 500 字符自动保存进度到数据库
- 重新打开页面自动恢复翻译状态（localStorage 标记 + 后端 `full_translation_active` 双保险）

## 📄 License

MIT

## 📦 Git LFS

项目使用 Git LFS 管理数据库文件（`*.sqlite3`）。克隆或更新后需要：

```bash
# 首次使用前安装
git lfs install

# 克隆后下载大文件
git lfs pull
```

各平台安装：
```bash
# Ubuntu/Debian
sudo apt install git-lfs

# Arch Linux
sudo pacman -S git-lfs

# macOS
brew install git-lfs
```

## 📝 更新日志

详见 [CHANGELOG.md](./CHANGELOG.md)
