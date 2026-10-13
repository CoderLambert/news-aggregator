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

- Python 3.11 或更高版本
- Node.js 20 或更高版本，npm 9 或更高版本
- 至少一个 LLM Provider API Key 才能使用翻译、聊天和研究功能
- 若使用需要浏览器渲染的抓取链路，需额外安装 Chromium
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

# 自动抓取全文后台任务
AUTO_FETCH_INTERVAL=300
AUTO_FETCH_BATCH=10
AUTO_FETCH_THROTTLE=2.0
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

### 4.2 生产模式：Waitress + 静态文件

```bash
cd frontend
npm run build
cd ..
backend/venv/bin/python start_waitress.py
```

访问 <http://127.0.0.1:9527>。生产环境建议：

- 设置 `DJANGO_DEBUG=0`
- 使用稳定且保密的 `DJANGO_SECRET_KEY`
- 将 `DJANGO_ALLOWED_HOSTS` 改为实际域名
- 在反向代理或防火墙层限制访问来源
- 通过 systemd、容器编排或进程管理器托管 Waitress

### 4.3 Docker 单机模式

Compose 启动 Waitress Web 服务、独立 crawler Worker 和独立 indexer Worker。前端会先构建并由 Django 同源提供，crawler 默认启动后抓取一次，之后每小时抓取；indexer 周期核对 SQLite 与 ChromaDB。Web 服务仅绑定到本机 `127.0.0.1:9527`。容器每次启动时会先执行幂等的 `migrate --noinput`，新克隆和代码升级无需单独运行迁移命令。

Web、crawler 与 indexer 共享 `backend/`（包括 SQLite、WAL、SHM、TTS 缓存），并持久化 `chroma_data/`、`logs/` 和 Hugging Face 模型缓存卷。不要让容器和另一套本地后端或爬虫同时写同一份 SQLite 数据。

~~~bash
docker compose up -d --build --wait
docker compose ps
docker compose logs -f app crawler indexer
docker compose down
~~~

访问 <http://127.0.0.1:9527>，创建超级管理员后可进入 <http://127.0.0.1:9527/admin/crawlers>。验证 Web 与 API：

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
docker compose logs --tail=200 app crawler indexer
~~~

`docker compose down` 只删除容器和 Compose 网络，宿主机数据库、ChromaDB、爬虫日志和模型缓存卷仍保留。crawler 服务负责自动调度；需要绕过管理控制台手动执行一次时使用：

~~~bash
docker compose exec app python backend/manage.py crawl all
~~~

Docker 调度参数：

~~~dotenv
CRAWLER_SCHEDULER_ENABLED=1
CRAWL_INTERVAL_SECONDS=3600
CRAWL_RUN_ON_START=1
~~~

管理控制台的调度设置持久化在数据库中；首次初始化读取上述环境变量。宿主机 `news-aggregator-crawl.timer` 或 `scripts/news-cron` 必须保持停止，避免两套调度器同时写入。

若 Docker CLI 提示无法访问 daemon，请先由本机 Docker 管理员恢复该用户已有的访问权限，不要通过项目配置扩大系统权限。

### 4.4 本地 VPN 出口与采集网络

如果宿主机能访问来源，但 crawler/full-content 容器连接超时，先分别检查两边的 DNS 和 HTTPS 连接。在 Linux 上使用 Tailscale 出口节点时，Docker 桥接流量可能没有走通同一条出口路径。本地可使用专用覆盖配置：

```bash
cp compose.host-network.yaml compose.override.yaml
docker compose up -d --no-build --wait app crawler full-content
```

该配置只让没有 HTTP 监听端口的 crawler 和 full-content Worker 使用宿主机网络。app 仍通过 `127.0.0.1:9527` 发布，数据库、任务锁、心跳和请求预算保持共享。`compose.override.yaml` 是忽略提交的本机配置；生产 Compose 不加载它。Docker 的网络行为参见 [host network driver](https://docs.docker.com/engine/network/drivers/host/)。

手动正文获取由 `.env` 中的 `FULL_CONTENT_WORKER_ENABLED=1` 控制，`FULL_CONTENT_AUTO_ENQUEUE_ENABLED=0` 可继续保持关闭。修改后同时重建 app 和 full-content 容器，普通登录用户即可请求正文，不需要超级管理员权限。

采集结果会区分主请求与 robots.txt 辅助请求，并保留入库数量、变化数量和失败原因。Feed 未到下一次轮询时间属于“等待执行”；部分条目入库后其他请求失败属于“部分成功”。源站拒绝或 robots.txt 禁止访问的入口不会反复自动请求；没有受支持入口的渠道会在管理页标明限制并排除出普通批次。

当前使用的官方入口包括 [InfoQ 新闻 RSS](https://feed.infoq.com/news/)、Mistral 页面声明的 [RSS](https://mistral.ai/news/rss)，以及 arXiv 官方说明的 [多分类 Atom 订阅](https://info.arxiv.org/help/rss.html#subscribe-by-multiple-categories)。RSS 描述仍按摘要处理；论文摘要不会作为论文全文。

## 5. 服务控制和日志

推荐使用统一命令，一次管理前端、后端和定时爬虫：

```bash
./scripts/news start
./scripts/news status
./scripts/news stop
```

`start` 默认会立即执行一次全部爬虫，之后每小时执行一次；`stop` 会停止前端、后端、定时器和当前正在运行的爬虫任务。

常用操作：

```bash
./scripts/news restart       # 重启全部服务
./scripts/news build         # 构建前端生产资源
./scripts/news crawl         # 手动执行一次全部爬虫
./scripts/news log crawler   # 查看爬虫日志
./scripts/news log backend   # 查看后端日志
./scripts/news log frontend  # 查看前端日志
```

定时周期可在根目录 `.env` 中调整：

```dotenv
CRAWL_INTERVAL_SECONDS=3600
CRAWL_RUN_ON_START=1
```

其中 `3600` 表示每小时执行一次，`CRAWL_RUN_ON_START=0` 表示启动定时器时不立即抓取。该调度器由项目自身管理，不依赖系统 `crond` 或 `crontab`。

底层脚本仍可单独使用：

```bash
./scripts/news-server start|stop|restart|status|log
./scripts/news-dev start|stop|restart|status|build|log
./scripts/news-cron start|stop|restart|status|run|log
```

日志和 PID 文件位于项目根目录的 `logs/`，该目录被 Git 忽略。若后台脚本不适合当前容器或终端环境，改用 4.1 节的前台命令。

如果需要“构建监听 + 静态预览”而不是 Vite HMR：

```bash
cd frontend
./dev-server.sh start
# 访问 http://localhost:5180
./dev-server.sh stop
```

## 6. 抓取新闻和全文

手动抓取：

```bash
backend/venv/bin/python backend/manage.py crawl all
backend/venv/bin/python backend/manage.py crawl hackernews
```

需要由 systemd 用户服务托管时，可将仓库中的
`scripts/news-aggregator-crawl.service` 和
`scripts/news-aggregator-crawl.timer` 安装到 `~/.config/systemd/user/`。
这套 timer 在上一轮结束一小时后再启动下一轮，并由 `flock` 阻止重叠；
不要同时启用下方的项目级 `news-cron` 调度器。每轮强制设置
`NEWS_CRAWL_ONLY=1`，只保存来源内容，不调用翻译、向量索引或其他 AI 功能。
完成后日志会为每个 spider 输出一行 `爬虫汇总`，包括条目数、响应数、
错误数和 HTTP 状态分布：

```bash
systemctl --user status news-aggregator-crawl.timer
journalctl --user -u news-aggregator-crawl.service -g '爬虫汇总'
```

unit 文件中的项目绝对路径应与实际 checkout 一致。`TimeoutStartSec=2h`
只是单轮最长运行时间，不是调度频率。

全文抓取：

```bash
./scripts/fetch_full_content_cron.sh dry-run
./scripts/fetch_full_content_cron.sh
FULL_CONTENT_FETCH_LIMIT=50 ./scripts/fetch_full_content_cron.sh
```

脚本默认使用 `backend/venv/bin/python`，并把日志写到 `logs/full_content_fetch.log`。

需要 Playwright 浏览器时：

```bash
backend/venv/bin/playwright install chromium
```

定时任务控制：

```bash
./scripts/news-cron run       # 手动抓取一次
./scripts/news-cron start     # 启动项目级定时器，默认每小时执行
./scripts/news-cron stop      # 停止定时器和当前爬虫
./scripts/news-cron status
./scripts/news-cron log
```

翻译网络恢复检查：

```bash
./scripts/check_translation_network.sh
```

本地或开发环境可直接使用 `./scripts/news start`。生产环境建议由 systemd、容器编排或其他进程管理器分别托管 Waitress 服务和 `./scripts/news-cron start`，并将 `CRAWL_INTERVAL_SECONDS` 配置在 `.env` 中。

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
PYTHONPATH="$(pwd)/backend:$(pwd)/crawler" \
  backend/venv/bin/python -m pytest tests/crawler/ -v

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
