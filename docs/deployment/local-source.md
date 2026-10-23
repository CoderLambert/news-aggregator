# 本机源码部署：前端、Django 与 RSS 同步

适用于不安装 Docker、只在本机 `127.0.0.1:9527` 提供服务的单机部署。前端用 Vite 构建为 `frontend/dist/`，Waitress 从源码加载 Django 并同源提供页面、静态资源和 API；订阅源由 Miniflux 获取，NewsHub 的独立 RSS 进程同步内容。以下命令在目标代码目录执行。

## 1. 代码、依赖和配置

先确认要部署的提交。已有工作树带有未提交数据时，用独立 checkout 或 `git worktree`，不要在运行中的目录强行切换分支。远程不可达时，本地 `origin/main` 只是上次获取的快照，不能称为最新远程代码。全新克隆若使用仓库自带基线数据库，先运行 `git lfs pull`；接管旧数据时使用下面的备份流程。

```bash
python3 -m venv backend/venv
backend/venv/bin/python -m pip install -r backend/requirements.txt
cd frontend
npm ci
npm run build
cd ..
```

新实例使用本机推荐模板，并将占位密钥替换为命令生成的稳定随机值：

```bash
cp .env.local.example .env
python3 -c "from secrets import token_urlsafe; print(token_urlsafe(60))"
# 把输出填入 .env 的 DJANGO_SECRET_KEY。
```

`.env.local.example` 提供本机站点、索引、智能频道、ChatGPT 本地连接和 TTS 配置。模型调用仍需用户明确配置自己的连接；LiteLLM BYOK 使用原有网关和项目凭据。Miniflux 使用独立的持久身份、专用账号与受保护 Token 文件，按 [RSS 部署配置](../../compose.rss.prod.yaml) 准备；该生产 overlay 不与开发版源码库 bind 混用。

接管旧实例时必须复制旧密钥配置，否则原有会话、订阅令牌或用户提供的模型 Key 可能无法解密。`.env` 不进入 Git。模板中的相对数据、锁和心跳路径要求所有命令都从项目根目录启动；同一数据库的每类 Worker 只运行一个。此处使用 `DJANGO_ENV=development` 配合本机监听；项目的 `production` 配置要求指定正式域名及可信代理，应按容器生产部署文档使用。

## 2. 数据库与前端构建

下面以项目根目录的 `.runtime/` 存放新实例数据。新库可直接迁移。接管正在运行的旧库时，先停旧 Web 服务、爬虫和其他写入者，再用 SQLite backup API 创建一致性快照；保留原库用于回退，不要直接迁移原库。

```bash
mkdir -p .runtime/chroma
export DJANGO_DB_PATH="$PWD/.runtime/live.sqlite3"
export CHROMA_DATA_DIR="$PWD/.runtime/chroma"

# 仅接管旧库时执行；将 SOURCE_DB 指向旧库绝对路径。
SOURCE_DB=/旧实例/backend/db.sqlite3 backend/venv/bin/python - <<'PY'
import os, sqlite3
with sqlite3.connect(f"file:{os.environ['SOURCE_DB']}?mode=ro", uri=True) as source, \
     sqlite3.connect(os.environ['DJANGO_DB_PATH']) as target:
    source.backup(target)
PY

backend/venv/bin/python backend/manage.py migrate --noinput
backend/venv/bin/python backend/manage.py check
```

旧 ChromaDB 如需保留，停旧索引写入者后复制整个目录；其 SQLite 文件也应使用 backup API 取一致快照。新实例可以先使用空目录，之后按项目的索引同步命令重建。

## 3. 启动 Web 与后台进程

两个终端都导出相同的 `DJANGO_DB_PATH` 和 `CHROMA_DATA_DIR`。第一个终端在项目根目录启动 Web 服务，明确绑定本机地址：

```bash
export DJANGO_ENV=development
export DJANGO_DB_PATH="$PWD/.runtime/live.sqlite3"
export CHROMA_DATA_DIR="$PWD/.runtime/chroma"
export PYTHONPATH="$PWD/backend"
export DJANGO_SETTINGS_MODULE=newsaggregator.settings
backend/venv/bin/python -c 'from waitress import serve; from newsaggregator.wsgi import application; serve(application, host="127.0.0.1", port=9527, threads=4)'
```

其他终端使用相同的 `DJANGO_DB_PATH`、`CHROMA_DATA_DIR` 和受保护配置启动所需后台进程：

```bash
backend/venv/bin/python backend/manage.py embedding_worker
NEWS_CRAWL_ONLY=1 backend/venv/bin/python backend/manage.py channel_worker
```

RSS 引擎可单独托管。先按[启动说明](../startup.md#6-订阅源与-rss-同步)配置固定的引擎身份、专用账号、API 地址、Token 文件与持久 runtime 目录，再运行：

```bash
NEWSHUB_RUNTIME_ROLE=rss_sync backend/venv/bin/python backend/manage.py rss_sync_worker
```

每个命令由独立进程管理器托管，保持数据库路径一致。Web 启动后优先运行统一的只读检查：

```bash
backend/venv/bin/python backend/manage.py runtime_health
```

命令覆盖数据库及所有当前已配置的 RSS 同步/引擎、频道 Worker、索引 Worker、翻译 Redis 和 AI 网关；已启用项异常时退出非零。超级管理员可在 `/admin/rss` 查看同一状态。该命令不调用 Provider、模型或订阅源，也不用于阻塞 Web 的数据库就绪探针。排查单个 Worker 容器时仍可使用其更强的进程内检查：

```bash
NEWSHUB_RUNTIME_ROLE=rss_sync backend/venv/bin/python backend/manage.py rss_sync_worker --healthcheck
backend/venv/bin/python backend/manage.py embedding_healthcheck
backend/venv/bin/python backend/manage.py channel_worker_healthcheck
```

## 4. 订阅、状态与升级

用户在频道页面管理订阅，管理员在 `/admin/rss` 查看引擎连接与同步状态。获取正文使用既有 RSS refetch 接口；历史正文继续保留，研究与翻译不启动网页抓取。同步失败由现有控制/对账流程处理，不另开旧采集进程。

旧 `crawl_worker`、全文 worker、宿主 `news-cron` 和 timer 模板已退出新版本。升级前须完成 [T29](../plans/rss-engine-migration/tasks/T29/task.md) 来源迁移和 [T30](../plans/rss-engine-migration/tasks/T30/task.md) 实际运行入口停止检查。不要用候选代码里的 `news stop` 推断旧宿主调度器已停。

更新和回退仍先核对不可变版本、当前迁移、数据库一致性备份和全部写入者。生产布局使用既有发布/回退脚本；历史镜像的兼容角色只有在目标清单明确声明时才加载。代码回退不等于数据库回滚。
