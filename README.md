# NewsHub — 个人新闻聚合与 AI 阅读助手

> 个人订阅、两级频道分组、AI 翻译、文章对话和深度研究。订阅源由 Miniflux 获取，阅读和模型调用留在 NewsHub。

维护者正在运行的站点：<https://news.lambert.host>（示例文章 <https://news.lambert.host/news/30126>）。站点上的账号、订阅和文章属于该部署，不随仓库里的基线数据库分发。

## ✨ 功能概览

| 模块 | 能力 |
|------|------|
| **个人频道** | 账号同步订阅。分组是「根分类 / 子分组 / 频道」：根分类只组织子分组，频道成员和首页范围都落在子分组上。同一频道最多三个子分组 |
| **智能整理** | `/channels/smart` 分「整理层级」和「整理频道」。AI 建议先预览再确认，可按版本撤销。可靠规则可以复用已有子分组；新建路径始终要确认 |
| **OPML** | 导入前预览、确认后写入；导出保留根/子路径。单层文件创建或复用个人分组，文件里已有的两级分类会保留。批量导入在空闲时提高并发 |
| **新闻聚合** | Miniflux 获取订阅源，NewsHub 同步文章。首页支持分类、来源、国内/国际和个人阅读范围，并分页浏览 |
| **AI 翻译** | 登录用户自带 Key，经 LiteLLM 路由到已保存的厂商模型。长文按块翻译，相邻两块可以重叠在途，结果仍按原文顺序拼接；以中文为主的正文跳过模型。本机已授权的 ChatGPT 订阅是另一条路径 |
| **智能助手** | 基于已保存文章的多轮对话，推荐问题可以换一批。不超过 30000 字的正文整篇作为证据，更长正文只发送这一上限内的前缀。摘要类问题使用更短的回答预算；发送被接受后立即清空输入框 |
| **深度研究** | 每次运行都要显式授权个人模型或 ChatGPT 订阅。研究使用本地检索和多步分析；语义搜索未启用时不走向量检索 |
| **本地搜索** | 关键词搜索始终可用。语义和混合模式需要 `SEMANTIC_SEARCH_ENABLED=1`，并且站点处于完整模式、AI 已开启。首页和检索中心都支持分页 |
| **页内搜索** | Ctrl+F 式全文高亮，带上下跳转和计数 |
| **文章目录** | 右侧悬浮目录，用 IntersectionObserver 跟踪当前标题 |
| **语音播报** | 全局播放器。中文音色为云扬、晓晓、云希，英文为 Guy；语速 0.8–2.0；可播全文或摘要，以及中文译文或原文 |
| **代码块复制** | Markdown 代码块一键复制 |
| **吉祥物** | 「小闻」有 idle、think、talk、happy、confused、sleep 六种表情，随对话状态切换 |
| **运行状态** | `news health` 和 `manage.py runtime_health` 汇总数据库、RSS、频道处理、搜索索引、翻译 Redis 与 AI 网关。超级管理员在 `/admin/rss` 看到同一份只读结果。检查不调用模型、Provider 或订阅源 |

## 个人频道与首页阅读范围

首页的「管理频道」打开 `/channels`。登录用户订阅目录中的来源，并只管理自己的分组。结构是根分类、子分组、频道三层。根分类不挂频道，也不能当作首页阅读范围；需要两级分类时再创建根分类，也可以保留不挂根分类的直接分组。名称去掉首尾空格后为 1–40 字。每个账号最多 40 个根分类、200 个子分组，每个频道最多属于 3 个子分组。已经超过 3 个分组的旧订阅仍可读取，新的写入继续执行这个上限。

取消订阅会去掉该频道的全部分组归属。删除子分组或从分组中移出频道时，订阅保留；若被删的子分组正是保存的首页范围，范围回到「我的订阅」。根分类只有在没有子分组时才能删除。停用来源不能新增订阅，已有订阅仍可阅读历史文章。

分组页面在 `/channels/groups`，支持创建、重命名、改挂和删除。结构调整提交当前版本，版本冲突返回 409。首页范围是 `scope=all|subscribed|ungrouped|group`，`group` 必须带子分组的 `group_id`。范围与 `source`、`category`、`region` 以及关键词/语义/混合搜索取交集，空范围保持零结果。切换范围保留搜索与分类、清除临时来源并回到第一页；清除筛选保留个人阅读范围。URL 优先于账号保存的上次范围，刷新和浏览器历史都认 URL。检索中心 `/search` 和收藏页 `/favorites` 保持独立，个人订阅不改变站点采集计划。

迁移 `0039`、`0040` 添加账号配置和缺失的受支持来源。`0085_channel_group_hierarchy` 给已经有分组的账号补一个名为「已有分组」的根分类，原有子分组、成员和阅读偏好的 ID 保持不变；没有分组的账号不创建空根。这些迁移不修改已有文章，也不自动订阅。更新来源元数据后，可执行 `python backend/manage.py sync_channel_catalog` 补充缺失频道；目录 GET 只读。公开只读模式只提供全部资讯和频道目录。

`/channels/smart` 的两次整理都先给出预览，确认后一次写入，并可以撤销本次变更：

- **整理层级**：建议把已有子分组改挂到根分类下。一次最多覆盖 20 个根分类和 200 个子分组。
- **整理频道**：分析未分组频道或全部已订阅频道，优先复用已有子分组，也可以建议最多 8 条新的「根 / 子」路径。一次最多 40 个频道，每个频道仍最多三个子分组。

手动移除的归属不会被自动加回。AI 整理不读取个人阅读记录、收藏、对话或私人分组名称。

OPML 在 `/api/me/rss-imports/preview/` 预览，确认后由 `/api/me/rss-imports/confirm/` 写入，`/api/me/rss-subscriptions/export/` 导出。单层分类创建或复用个人分组；只有文件本身带两级分类时才保留父子路径。导入不调用 AI，也不移动已经手工归好的频道。批量导入空闲时使用更高并发，默认突发上限 12；活跃超级管理员的批次优先取得槽位。单条防重发、同域名冷却和租约保持不变。

个人接口使用会话认证和 CSRF。每个账号只能访问自己的分组，越权返回 404：

| 接口 | 方法与请求 |
| --- | --- |
| `/api/me/channel-subscriptions/` | GET。POST `subscribe` / `unsubscribe` 使用 `source_ids`。`set_groups` 用 `group_ids` 替换全部子分组归属；`add_to_group`、`move_to_group`、`remove_from_group` 使用 `group_id`。新增归属最多三个子分组 |
| `/api/me/channel-group-roots/` | GET。POST `{name}` 创建根分类 |
| `/api/me/channel-group-roots/<id>/` | GET。PATCH `{name, expected_version}` 重命名。DELETE 需要查询参数 `expected_version`，根下仍有子分组时拒绝 |
| `/api/me/channel-groups/` | GET。POST `{name, root_id}` 创建子分组；`root_id` 为 `null` 时是直接分组 |
| `/api/me/channel-groups/<id>/` | GET、DELETE。改名或改挂须带 `expected_version` 和 `name` / `root_id`。成员调整使用 `source_ids`、`add_source_ids` 或 `remove_source_ids` |
| `/api/me/news-preferences/` | GET。PATCH `{scope, group_id}`；`scope=group` 时 `group_id` 必须是自己的子分组 |
| `/api/me/smart-channels/proposals/` | 生成整理预览。`.../apply/` 确认，`.../undo/` 撤销，`.../cancel/` 放弃尚未应用的预览 |

## 新能源、医疗 RSS 与频道地区

频道新增独立的 `region=domestic|international`，按服务市场与版本划分；语言、内容分类和来源类型保持独立。首页、频道管理及检索中心均支持国内／国际筛选，首页地区与个人阅读范围取交集。URL 保存地区；切换地区清除临时来源并重置分页，保留搜索、分类和个人分组；清除筛选保留个人阅读范围。

迁移 `0041/0042` 保留既有频道地区、行业来源及分类。来源替代、连接状态和采集政策以当前 RSS 迁移清单与实际验收为准；历史 XML 解析结果不能证明当前可用。来源元数据保存在 `backend/api/services/sector_feeds.py`。

Energy-Storage.news、Windpower Monthly 和医疗媒体、期刊仅展示 RSS 标题、摘要及真实原文链接，后端禁止正文获取；FDA、NIH 仅使用 RSS 公开提供的内容。未提供摘要时不生成占位内容。医疗资讯和相关 AI 回答标注“新闻资讯，不构成医疗建议”，单篇助手与研究助手使用实际文章 URL 展示来源链接。

`/api/sources/` 支持 `region` 并返回地区和阅读策略；`/api/news/` 支持同名地区参数，并返回 `source_region`、`channel_ids`、`channel_names`、`is_medical`、`reading_policy`。同一文章在多个频道收录时保持主来源和单篇去重，按所有频道归属参与订阅、来源和分类筛选。openFDA、PubMed、ClinicalTrials.gov 数据专题当前不包含在内。

## 🛠 技术栈

```
Frontend:  React 19 + Vite 8 + Tailwind 4 + shadcn/ui + React Compiler
Backend:   Django 6 + DRF + SQLite + Miniflux
AI:        LiteLLM Gateway + 用户自带 API Key（受控的主流厂商白名单）
向量检索:   ChromaDB（语义搜索支持）
测试:      Vitest + Testing Library (前端) | pytest-django (后端)
```

## 📋 环境要求

- **Docker 部署**：Docker Engine + Compose v2 + Git LFS
- **本地开发与 CI**：Python 3.12、Node.js 22（Docker 镜像与 CI 使用这两个版本）
- AI 功能可使用本地 ChatGPT 订阅连接，或由登录用户在设置页配置自己的厂商 API Key 与 Model ID。浏览器不能填写 Base URL 或 LiteLLM 路由前缀

## 🚀 快速开始

> 完整的初始化、开发/生产启动、订阅源同步、测试、数据和故障排查说明见 [启动与运维说明](./docs/startup.md)。

不安装 Docker 的单机部署（前端构建、Waitress、SQLite 数据迁移与 RSS 同步）见 [源码部署说明](./docs/deployment/local-source.md)。

### Docker 一键部署（推荐）

语义索引的同步、恢复和管理方案见 [docs/semantic-index-sync-design.md](docs/semantic-index-sync-design.md)。

从克隆到可访问的服务只需要准备 `.env`。Compose 会构建前端和后端、自动执行开发库迁移，并启动 Waitress 与语义索引容器。语义和混合搜索默认关闭：只有 `SEMANTIC_SEARCH_ENABLED=1`，且站点为完整模式、AI 已开启时，索引 Worker 才会写入 ChromaDB，否则容器保持空闲、不碰索引状态。订阅源获取还需单独配置 Miniflux/RSS runtime：

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
| 后台进程日志 | `./logs/` | `/app/logs/` |
| Hugging Face 模型缓存 | Docker volume `news-aggregator_huggingface-cache` | `/root/.cache/huggingface` |

接管已有数据库时，先停止原后端和爬虫写入者，再把 `db.sqlite3` 及仍存在的 `db.sqlite3-wal`、`db.sqlite3-shm` 一起放入 `backend/`，然后启动 Compose。保存 ChatGPT 订阅连接时还必须沿用原来的 `DJANGO_SECRET_KEY` 或 `CHATGPT_TOKEN_ENCRYPTION_KEY`。如果目标是新机器/新 VM，不要复制 `backend/.runtime/chatgpt-deployment-id`；新部署会生成自己的 OAuth host ID。同一部署内所有站内用户共享这个非敏感 host 标识，但各自的 `client_id` 和 Token 分开保存。

常用维护命令：

```bash
docker compose ps
docker compose logs -f app indexer
docker compose restart app indexer
docker compose down                    # 数据仍保留

# 更新代码和镜像；容器启动时会自动应用新迁移
git pull --ff-only
git lfs pull
docker compose up -d --build --wait
```

语义搜索启用后，indexer Worker 维护向量索引。超级管理员在 <http://127.0.0.1:9527/admin/rss> 查看同一份运行状态、RSS 连接、同步情况，并在启用语义搜索后管理索引。`runtime_health` 与页面上的服务健康状态检查数据库、RSS 同步 Worker、RSS 引擎、频道处理 Worker、搜索索引、翻译 Redis 和 AI 网关；已启用项异常时命令返回非零。公共 `/api/health/ready/` 只表示应用进程就绪，不代替这份运行检查。RSS 引擎使用单独的 PostgreSQL、受保护凭据和持久身份，配置入口为 [RSS Compose](./compose.rss.prod.yaml) 与 [迁移架构](./docs/plans/rss-engine-migration/ARCHITECTURE.md)。此 overlay 使用生产布局，不能直接叠加到开发版的源码数据库 bind 上。创建管理员：

```bash
docker compose exec app python backend/manage.py createsuperuser
```

公开注册只会创建普通用户，不会授予管理权限。管理员使用同一个登录窗口；新管理员可通过上面的 `createsuperuser` 命令创建，已有账号则由部署者在服务端明确授予 `is_staff` 和 `is_superuser` 权限。

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

**启动前端与后端**

```bash
./scripts/news start
# 访问 http://127.0.0.1:5173
```

查看状态、运行健康检查和停止全部服务：

```bash
./scripts/news status
./scripts/news health    # 前端监听，以及 runtime_health 覆盖的已配置依赖
./scripts/news stop
```

`news health` 在已启用的依赖异常时返回非零。它不调用模型、Provider 或订阅源，也不替代 `/api/health/ready/`。

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

订阅源获取由已配置的 Miniflux 与 RSS runtime 负责；已有数据库迁移和端口配置见[源码部署说明](./docs/deployment/local-source.md)。

### 6. 订阅与同步文章

在“频道”页面选择或添加订阅源，文章同步完成后显示在列表中。管理员可在 `/admin/rss` 查看连接和同步状态。研究、翻译和朗读使用已保存内容；历史正文继续保留。

升级到本版本前，必须完成 [T29 来源迁移](./docs/plans/rss-engine-migration/tasks/T29/task.md) 和 [T30 旧运行入口停止验收](./docs/plans/rss-engine-migration/tasks/T30/task.md)。移除仓库里的 timer/cron 模板不会停用主机上已经安装的任务；宿主检查须在原部署环境执行。源码清理候选不代表这些生产门禁已通过。

## 🧪 测试

```bash
# 后端测试（api/tests，不含仓库根目录 tests/ 与 scripts/deploy/tests）
cd backend
python -m pytest api/tests/ -v

# 前端测试
cd frontend
npm run test:run

# 旧的部分入口：tests/backend、构建检查和 RSS 测试。它不代替上面的前端套件或完整后端收集
./scripts/run_tests.sh
```

## 📁 项目结构

```
news-aggregator/
├── backend/                  # Django 后端
│   ├── api/
│   │   ├── models.py         # 文章、来源、频道分组、对话与研究会话等模型
│   │   ├── views.py          # 列表、详情、对话和订阅翻译入口
│   │   ├── channel_views.py  # 个人根分类、子分组、订阅和首页范围
│   │   ├── runtime_health_views.py  # 超级管理员只读运行状态
│   │   ├── services/
│   │   │   ├── ai_private_translation.py  # BYOK 分块翻译
│   │   │   ├── ai_article_chat.py         # 文章对话证据上限与回答预算
│   │   │   ├── runtime_health.py          # 统一健康检查
│   │   │   └── research/                  # Research Agent
│   │   ├── rss/              # Miniflux 同步、OPML 与订阅控制
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
│   │   │   └── Pagination.tsx # 响应式分页组件
│   │   ├── hooks/            # 自定义 Hooks
│   │   ├── services/         # API 服务层
│   │   ├── context/          # React Context（语言、认证、语音播放器）
│   │   └── constants/        # 常量定义（TTS 配置）
│   ├── vite.config.js        # Vite + React Compiler + 代理配置
│   └── package.json
├── backend/db.sqlite3        # Django SQLite 数据库（LFS 管理，路径在 backend/ 下）
├── chroma_data/              # ChromaDB 运行时向量数据（Git 忽略）
├── scripts/                  # 运维脚本
│   ├── news-server           # Django 服务管理，health 调用 runtime_health
│   ├── news-dev              # Vite 开发服务器管理
│   ├── news                  # 前端、后端与 news health
│   └── run_tests.sh          # 旧的部分测试入口
├── start_waitress.py         # Waitress 生产启动脚本
├── .env.example              # 环境变量模板
├── .gitattributes            # Git LFS 追踪规则
└── CHANGELOG.md              # 更新日志
```

## 🔑 API 接口一览

阅读和账号接口仍走会话认证。个人频道、OPML 和整理预览见上一节，这里只列常用入口：

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/news/` | 新闻列表。搜索使用 `search` 与 `mode=keyword\|semantic\|hybrid`；语义模式未启用时拒绝 |
| GET | `/api/news/:id/` | 新闻详情 |
| POST | `/api/news/:id/fetch-full/` | 已退役，返回 410。正文由订阅源引擎更新 |
| POST | `/api/news/:id/byok-translation/` | 创建 BYOK 全文翻译任务 |
| POST | `/api/news/:id/translate/` | ChatGPT 订阅或仍走个人客户端的 SSE 翻译 |
| POST | `/api/news/:id/chat/` | SSE 文章对话 |
| POST | `/api/news/:id/suggested-questions/` | 获取或刷新推荐问题 |
| POST | `/api/news/:id/tts/` | TTS 语音合成 |
| GET | `/api/categories/` | 分类列表 |
| GET | `/api/sources/` | 来源列表，支持 `region` |
| POST | `/api/research/` | 创建研究会话 |
| POST | `/api/research/:id/chat/` | 发送研究问题 |
| GET | `/api/admin/runtime-health/` | 超级管理员只读运行状态 |

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

### 翻译进度

- BYOK 长文最多八块。后一块可以在前一块仍在返回时发出，拼回顺序与原文一致；以中文为主的正文不调用模型
- ChatGPT 订阅和仍使用个人客户端的翻译任务在后台线程运行，大约每 500 字写回一次进度
- 重新打开页面可以接着看尚未完成的译文。连接关闭本身不算翻译成功

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
