# 本机源码部署：前端构建、Django 与全文获取

适用于不安装 Docker、只在本机 `127.0.0.1:9527` 提供服务的单机部署。前端用 Vite 构建为 `frontend/dist/`，Waitress 从源码加载 Django 并同源提供页面、静态资源和 API；全文获取由独立进程处理持久队列。以下命令在目标代码目录执行。

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

`.env.local.example` 默认开启本机完整站点、注册、AI 入口、ChatGPT 本地授权、全文获取、结构化正文、爬虫调度、语义索引、智能频道后台任务和 TTS，并使用本机已验证的 `EDGE_TTS_ENDPOINT=msedgeservices`。ChatGPT 或其他模型功能仍需要各用户连接自己的订阅，或者通过设置页提供自己的厂商 Key；使用厂商 Key 时还需运行 `.env` 中配置的 LiteLLM BYOK 网关。Jina Key 可选。

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

第二个终端在相同目录启动全文 Worker：

```bash
export DJANGO_ENV=development
export DJANGO_DB_PATH="$PWD/.runtime/live.sqlite3"
export CHROMA_DATA_DIR="$PWD/.runtime/chroma"
export NEWS_CRAWL_ONLY=1
backend/venv/bin/python backend/manage.py auto_fetch_full_content --foreground
```

推荐模板同时开启爬虫调度、语义索引和智能频道任务。分别再启动三个常驻进程：

```bash
NEWS_CRAWL_ONLY=1 backend/venv/bin/python backend/manage.py crawl_worker
backend/venv/bin/python backend/manage.py embedding_worker
NEWS_CRAWL_ONLY=1 backend/venv/bin/python backend/manage.py channel_worker
```

Worker 和爬虫需要访问来源站点。若进程继承的代理地址不可达，先确认目标站点可直连，再在这两个进程的启动命令中清除失效的 `http_proxy`、`https_proxy`、`HTTP_PROXY`、`HTTPS_PROXY` 和 `ALL_PROXY`；保留 TLS 证书校验。本机当前实例采用直连运行这两个进程。

可用现有进程管理器托管这两个前台命令，并设置故障重启。启动后验证：

```bash
curl -f http://127.0.0.1:9527/
curl -f http://127.0.0.1:9527/api/health/ready/
backend/venv/bin/python backend/manage.py full_content_healthcheck
backend/venv/bin/python backend/manage.py crawler_healthcheck
backend/venv/bin/python backend/manage.py embedding_healthcheck
backend/venv/bin/python backend/manage.py channel_worker_healthcheck
```

## 4. 入队、进度和定时爬虫

自动入队仅覆盖新采集、时间可靠且符合来源规则的文章。历史文章需显式入队；命令最多选 500 条，建议先小批量确认质量。`--since` 使用带时区的 ISO 时间；再次运行时用输出的 `next_after_id` 作为 `--after-id` 继续翻页。

```bash
backend/venv/bin/python backend/manage.py fetch_full_content --since 2026-10-01T00:00:00+08:00 --limit 100 --dry-run
backend/venv/bin/python backend/manage.py fetch_full_content --since 2026-10-01T00:00:00+08:00 --limit 100
backend/venv/bin/python backend/manage.py full_content_stats --json
```

Worker 会按来源公平轮询，并保留限流、重试和正文校验状态。不要对全部历史文章使用 `--force`；已得到可读正文的文章会跳过。来源不允许抓取、被站点拦截、只提供摘要，或原文内容无法通过校验时，正文可能仍为空。

如果使用推荐的 `crawl_worker`，不要再同时保留 cron 爬虫。若改用已有 cron，更新其代码目录及 `DJANGO_DB_PATH`，确保与 Web 和 Worker 使用同一数据库，并停用 `crawl_worker`。手动运行新代码的爬虫可使用 `NEWS_CRAWL_ONLY=1 backend/venv/bin/python backend/manage.py crawl all`。这种模式跳过 AI 侧效应，但经校验的结构化正文仍可写入。只保留一套定时调度，并用 `flock -n` 防止相邻轮次重叠。更新时先备份数据库，再停止 Web 和全部 Worker、构建前端、执行迁移并重启；回退代码前核对迁移版本，不能把已升级的数据库直接交给旧代码。
