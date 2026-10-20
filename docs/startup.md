# NewsHub 启动与运维说明

本文档适用于本地开发、测试和单机部署。除特别说明外，命令均在项目根目录执行：

```bash
cd /path/to/news-aggregator
```

## 1. 项目组成

| 服务 | 技术 | 默认地址 | 用途 |
| --- | --- | --- | --- |
| 后端 | Django + DRF | `http://127.0.0.1:9527` | API、会话鉴权、静态生产页面 |
| 前端 | React + Vite | `http://127.0.0.1:5173` | 开发热更新和 `/api` 代理 |
| 生产前端 | Vite build + Waitress | `http://127.0.0.1:9527` | 单进程提供静态页面和 API |
| 数据库 | SQLite | `backend/db.sqlite3` | 新闻、用户、会话和任务状态 |
| 向量库 | ChromaDB | `chroma_data/` | 本地语义搜索向量 |

## 2. 环境要求

- Python 3.12（与 CI 一致）
- Node.js 22（与 CI 一致）
- 至少一个 LLM Provider API Key 才能使用翻译、聊天和研究功能
- Chromium 用于浏览器验收；订阅源获取由 Miniflux 处理
- Linux/macOS 使用 Bash；Windows 建议通过 WSL 执行脚本

## 3. 首次初始化

### 3.1 获取代码和数据库 LFS 数据

```bash
git clone https://github.com/CoderLambert/news-aggregator.git
cd news-aggregator
git lfs install
git lfs pull
```

项目通过 Git LFS 管理基线 `*.sqlite3` 数据库。`chroma_data/` 是忽略提交的运行时派生数据，不从 Git 恢复；Docker indexer Worker 会在首次部署后自动建立并持续同步本地语义搜索索引。接管已有实例时按下文的数据迁移步骤复制数据库。

### 3.2 创建 Python 环境并安装依赖

```bash
python3 -m venv backend/venv
backend/venv/bin/python -m pip install --upgrade pip
backend/venv/bin/python -m pip install -r backend/requirements.txt
```

也可以激活虚拟环境后使用普通的 `python` 和 `pip`：

```bash
source backend/venv/bin/activate
pip install -r backend/requirements.txt
```

### 3.3 安装前端依赖

```bash
cd frontend
npm ci
cd ..
```

`npm ci` 会严格按照 `frontend/package-lock.json` 安装依赖。若只修改了 `package.json`，请使用 `npm install` 更新 lockfile 后再提交。

### 3.4 创建环境变量文件

```bash
cp .env.example .env
```

`.env` 已被 Git 忽略，不要提交真实凭据。个人模型 Key 由用户登录后在设置页保存，不放在站点环境变量中：

```dotenv
DJANGO_SECRET_KEY=请生成一个稳定的随机密钥
DJANGO_DEBUG=1
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1

AI_BYOK_GATEWAY_URL=http://127.0.0.1:4000
AI_BYOK_GATEWAY_PROJECT_KEY=本地开发网关签发的受限虚拟Key
JINA_API_KEY=
```

生成 Django 密钥：

```bash
backend/venv/bin/python -c "import secrets; print(secrets.token_urlsafe(60))"
```

Provider 选择规则：

- 登录用户从 OpenAI、Anthropic Claude、DeepSeek、Google Gemini、Qwen、GLM/Z.AI、Kimi/Moonshot、Mistral、Groq、xAI 或 OpenRouter 中选择，并填写厂商 Model ID
- 业务后端按白名单构造 LiteLLM 路由；用户不能设置任意 Base URL
- 不配置站点级厂商 Key，不做跨厂商自动 fallback
- `JINA_API_KEY`：研究 Agent 的联网搜索/抓取 Key，可选
- 未配置 Key 时，基础新闻浏览仍可用，但 AI 功能会返回未配置提示

其他可选配置：

```dotenv
# 低资源设备优化
TERMUX_MODE=0

# Waitress 线程和连接上限；未设置时普通模式为 4/1000，Termux 模式为 2/256
WAITRESS_THREADS=4
WAITRESS_CONN_LIMIT=1000

# RSS 连接与持久身份使用单独的受保护配置，见第 6 节。
```

### 3.5 初始化数据库

```bash
backend/venv/bin/python backend/manage.py migrate
backend/venv/bin/python backend/manage.py check
```

需要前端爬虫管理控制台账号时执行：

```bash
backend/venv/bin/python backend/manage.py createsuperuser
```

首次启动会在后台预加载语义搜索模型 `paraphrase-multilingual-MiniLM-L12-v2`。首次联网启动可能从 Hugging Face 下载模型文件；模型未缓存时，普通 API 仍可启动，但语义搜索需要等待模型加载完成。

### 3.6 构建前端

```bash
cd frontend
npm run build
cd ..
```

生产模式依赖 `frontend/dist/`，没有构建产物时 Django 会提示静态目录不存在。

## 4. 启动方式

### 4.1 开发模式：推荐

使用项目脚本启动后台服务：

```bash
./scripts/news-server start
./scripts/news-dev start
```

访问：

- 前端：<http://127.0.0.1:5173>
- 后端 API：<http://127.0.0.1:9527/api/news/>
- Django Admin：<http://127.0.0.1:9527/admin/>

ChatGPT 订阅授权依赖浏览器在回调端口携带同一主机的本地会话 Cookie。开发模式请使用上述 `127.0.0.1` 地址，不要把入口改写成 `localhost`。

脚本会自动根据自身位置定位项目目录，优先使用 `backend/venv/bin/python` 和本地 Vite，不依赖固定的绝对路径。

手动前台启动（适合容器、IDE 或需要直接查看日志的场景）：

```bash
# 终端 1
backend/venv/bin/python backend/manage.py runserver 0.0.0.0:9527

# 终端 2
cd frontend
npm run dev -- --host 0.0.0.0
```

### 4.2 源码单机模式：Waitress + 静态文件

不使用 Docker 时，前端先执行 `npm ci && npm run build`，再由 Waitress 从源码启动 Django；`frontend/dist/` 和 API 由同一端口提供。已有数据接管、独立 RSS 同步、健康检查及回退步骤见[源码部署说明](deployment/local-source.md)。

```bash
cd frontend
npm run build
cd ..
backend/venv/bin/python start_waitress.py
```

访问 <http://127.0.0.1:9527>。本机长期运行建议设置 `DJANGO_DEBUG=0`、保留稳定的 `DJANGO_SECRET_KEY`，并由进程管理器托管 Waitress 与独立 Worker。直接执行 `start_waitress.py` 会监听所有网卡；仅本机访问时请使用[源码部署说明](deployment/local-source.md)中的 `127.0.0.1` 启动命令。

### 4.3 Docker 单机模式

开发 Compose 启动 Waitress 和 indexer，前端先构建并由 Django 同源提供。Web 绑定本机 `127.0.0.1:9527`，开发入口启动时迁移开发库。RSS 使用单独配置的 Miniflux 和同步进程；生产布局的迁移由受控的一次性服务执行。

Web 与 indexer 共享 `backend/`（包括 SQLite、WAL、SHM、TTS 缓存），并持久化 `chroma_data/`、`logs/` 和 Hugging Face 模型缓存卷。不要让容器和另一套本地后端或爬虫同时写同一份 SQLite 数据。

~~~bash
docker compose up -d --build --wait
docker compose ps
docker compose logs -f app indexer
docker compose down
~~~

访问 <http://127.0.0.1:9527>，创建超级管理员后可进入 <http://127.0.0.1:9527/admin/rss>。验证 Web 与 API：

~~~bash
curl -f http://127.0.0.1:9527/
curl -f http://127.0.0.1:9527/api/news/
~~~

`.env` 会作为容器运行时环境变量注入，但不会进入构建镜像；SQLite 主文件、WAL、SHM 和凭据文件也由 `.dockerignore` 排除。复制 `.env.example` 后按需填写。首次语义搜索可能需要下载嵌入模型。

indexer 会自动补充缺失新闻、更新内容哈希变化的向量并删除孤立向量。超级管理员可以在管理控制台立即同步或执行版本化完整重建；命令行可使用 `python backend/manage.py sync_embeddings --wait`。索引损坏时执行 `sync_embeddings --rebuild --wait`，不要删除 `backend/db.sqlite3`。

接管已有数据库：

1. 先停止原 API、爬虫、定时器和其他 SQLite 写入者。
2. 优先使用 SQLite backup API 生成一致性快照；若直接移动文件，必须在停写后同时移动 `db.sqlite3`、`db.sqlite3-wal` 和 `db.sqlite3-shm`。
3. 将文件放进宿主机 `backend/`，运行 `docker compose up -d --build --wait`。
4. 使用 `docker compose exec -T app python backend/manage.py check` 和 API 健康检查确认运行状态。

ChatGPT 订阅令牌使用 `CHATGPT_TOKEN_ENCRYPTION_KEY` 加密；未单独设置时使用 `DJANGO_SECRET_KEY`。用户自行配置的模型 API Key 使用独立 HKDF 上下文的 AES-GCM 加密，可通过 `PROVIDER_CREDENTIAL_ENCRYPTION_KEY` 单独指定稳定密钥；未指定时依次沿用订阅加密密钥和 `DJANGO_SECRET_KEY`。迁移已有数据库时必须沿用这些稳定密钥，否则已有凭据无法解密，需要用户重新配置或连接。

`backend/.runtime/chatgpt-deployment-id` 是当前部署的非敏感标识。同一部署重启或更新时应保留；迁移到新机器或新 VM 时不要复制。每个部署只有一个稳定的随机 ChatGPT OAuth host ID；不同站内用户的 `client_id`、Token 和连接记录始终分开保存。

完整的登录流程、安全边界与 Cloudflare 超时诊断见 [`docs/chatgpt-subscription-oauth.md`](chatgpt-subscription-oauth.md)。

更新与回滚：

~~~bash
# 更新代码、LFS 数据和镜像；启动时自动应用迁移
git pull --ff-only
git lfs pull
docker compose up -d --build --wait

# 查看新容器状态和日志
docker compose ps
docker compose logs --tail=200 app indexer
~~~

开发 Compose 默认启动 app 和 indexer。生产使用独立迁移、不可变镜像和发布清单；已有部署先完成 [T29/T30 门禁](plans/rss-engine-migration/TASKS.md)，不能用开发版的自动迁移流程接管生产。RSS 使用 [生产布局 overlay](../compose.rss.prod.yaml)，与 Miniflux PostgreSQL 及专用同步进程共享正确的部署身份；不要将此 overlay 叠加到开发版的源码库 bind 上。

若 Docker CLI 提示无法访问 daemon，请先由本机 Docker 管理员恢复该用户已有的访问权限，不要通过项目配置扩大系统权限。

### 4.4 RSS 出口与网络

沿用 RSS 引擎的 URL、DNS、重定向和请求预算限制。网络诊断应检查该进程的实际出口与证书配置，不能通过 host 网络绕过来源准入规则。`compose.host-network.yaml` 仅为保留的索引 worker 提供可选出口；来源同步按 RSS 专用部署配置运行。

## 5. 服务控制和日志

`news` 管理本机前端与后端进程，RSS 引擎和后台 worker 由各自的进程管理器托管：

```bash
./scripts/news start
./scripts/news status
./scripts/news stop
./scripts/news restart
./scripts/news build
./scripts/news log backend
./scripts/news log frontend
```

日志和 PID 文件位于被 Git 忽略的 `logs/`。此命令不再启动宿主爬虫定时器。现有宿主 timer/cron 必须在 [T30](plans/rss-engine-migration/tasks/T30/task.md) 检查中单独停用和验证，删除仓库模板不能替代该检查。

## 6. 订阅源与 RSS 同步

在频道页面添加或选择订阅源。Miniflux 负责获取，NewsHub 通过现有同步进程保存经过校验的内容；翻译、聊天、研究和朗读读取已保存数据。旧 fetch-full、网页 Provider 和 Scrapy 命令已经退役。

RSS 配置需要固定的 `RSS_ENGINE_INSTANCE_UUID`、专用 `RSS_ENGINE_ACCOUNT_ID`、`RSS_ENGINE_BASE_URL`、受保护的 `RSS_ENGINE_TOKEN_FILE` 和持久的 `RSS_RUNTIME_DIR`。保持 Web 与同步进程指向相同 NewsHub 数据库。完整身份和准入要求见 [架构](plans/rss-engine-migration/ARCHITECTURE.md) 与 [Compose](../compose.rss.prod.yaml)。

配置完成后，独立同步入口为：

```bash
NEWSHUB_RUNTIME_ROLE=rss_sync backend/venv/bin/python backend/manage.py rss_sync_worker
# 独立检查同步进程健康；不会把 ORM 可用误报为同步完成。
NEWSHUB_RUNTIME_ROLE=rss_sync backend/venv/bin/python backend/manage.py rss_sync_worker --healthcheck
```

`rss_runtime --once` 保留为轻量 ORM 诊断，不表示同步完成。管理员可在 `/admin/rss` 查看实际连接与同步状态。暂停来源仍保留历史文章，原有来源和正文访问限制继续生效。

## 7. 测试和质量检查

运行项目测试脚本：

```bash
./scripts/run_tests.sh
```

单独运行：

```bash
# 后端基础测试
backend/venv/bin/python -m pytest tests/backend/ -v

# 后端 API 全量测试
backend/venv/bin/python -m pytest backend/api/tests/ -v

# 爬虫测试
PYTHONPATH="$(pwd)/backend" \
  backend/venv/bin/python -m pytest backend/api/tests/rss/ -v

# 前端测试、Lint、构建
cd frontend
npm run test:run
npm run lint
npm run build
cd ..

# 构建产物校验
backend/venv/bin/python scripts/validate_build.py
```

基础健康检查：

```bash
curl -f http://localhost:9527/api/news/
curl -f http://localhost:5173/
```

## 8. 数据和重置

- SQLite 数据库：`backend/db.sqlite3`
- ChromaDB 数据：`chroma_data/`
- 本地环境变量：`.env`
- 运行日志：`logs/`

重置为全新空数据库前，先备份：

```bash
cp backend/db.sqlite3 /tmp/news-aggregator-db.sqlite3.backup
backend/venv/bin/python backend/manage.py migrate
```

如果数据库是 Git LFS 指针而不是 SQLite 文件，优先执行 `git lfs pull`。确认没有可恢复的数据库后，再将无效文件移出项目目录并重新迁移：

```bash
file backend/db.sqlite3
mv backend/db.sqlite3 /tmp/news-aggregator-db.sqlite3.invalid
backend/venv/bin/python backend/manage.py migrate
```

## 9. 常见问题

### `ModuleNotFoundError`

确认命令使用的是项目虚拟环境：

```bash
backend/venv/bin/python -m pip check
backend/venv/bin/python -c "import django, waitress, bs4, chromadb; print('OK')"
```

### 端口已被占用

```bash
lsof -i :9527
lsof -i :5173
```

停止旧服务后再重启；不要在不确认进程归属时使用宽泛的 `pkill`。

### 前端页面打开但 API 失败

确认 Django 已运行，并检查 Vite 代理目标仍为 `http://localhost:9527`。生产模式不经过 Vite，直接访问 `9527`。

### AI 功能提示未配置 Key

先确认当前用户已在「设置」中选择受支持的厂商、填写 Model ID 并保存自己的 API Key。若已配置仍失败，检查 `AI_BYOK_GATEWAY_URL`、项目虚拟 Key 文件与独立 LiteLLM 网关的 readiness；不要改为站点级厂商 Key 或直连 fallback。

### 语义搜索不可用或首次启动很慢

确认 indexer 容器健康并可访问 Hugging Face。模型或索引不可用时语义、混合检索会自动显示关键词结果；模型下载和索引恢复完成后自动恢复语义检索。

```bash
docker compose ps
docker compose logs --tail=200 indexer
docker compose exec -T app python backend/manage.py sync_embeddings --wait
```

### `npm ci` 报安全漏洞

先查看：

```bash
cd frontend
npm audit
```

不要在未审阅 lockfile 变化前直接执行 `npm audit fix`。
