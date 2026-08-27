# NewsHub 启动与运维说明

本文档适用于本地开发、测试和单机部署。除特别说明外，命令均在项目根目录执行：

```bash
cd /path/to/news-aggregator
```

## 1. 项目组成

| 服务 | 技术 | 默认地址 | 用途 |
| --- | --- | --- | --- |
| 后端 | Django + DRF | `http://localhost:9527` | API、管理后台、静态生产页面 |
| 前端 | React + Vite | `http://localhost:5173` | 开发热更新和 `/api` 代理 |
| 生产前端 | Vite build + Waitress | `http://localhost:9527` | 单进程提供静态页面和 API |
| 数据库 | SQLite | `backend/db.sqlite3` | 新闻、用户、会话和任务状态 |
| 向量库 | ChromaDB | `chroma_data/` | 本地语义搜索向量 |

## 2. 环境要求

- Python 3.11 或更高版本
- Node.js 20 或更高版本，npm 9 或更高版本
- 至少一个 LLM Provider API Key 才能使用翻译、聊天和研究功能
- 若使用需要浏览器渲染的抓取链路，需额外安装 Chromium
- Linux/macOS 使用 Bash；Windows 建议通过 WSL 执行脚本

## 3. 首次初始化

### 3.1 获取代码和 Git LFS 数据

```bash
git clone https://github.com/CoderLambert/news-aggregator.git
cd news-aggregator
git lfs install
git lfs pull
```

项目用 Git LFS 管理 `*.sqlite3` 和 `chroma_data/**`。如果没有安装 Git LFS，数据库或向量数据可能只显示为一段 `version https://git-lfs.github.com/spec/v1` 文本。

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

至少填写一个 LLM Key。`.env` 已被 Git 忽略，不要提交真实凭据：

```dotenv
DJANGO_SECRET_KEY=请生成一个稳定的随机密钥
DJANGO_DEBUG=1
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1

VOLCENGINE_API_KEY=
DASHSCOPE_CODING_API_KEY=
JINA_API_KEY=
```

生成 Django 密钥：

```bash
backend/venv/bin/python -c "import secrets; print(secrets.token_urlsafe(60))"
```

Provider 选择规则：

- `VOLCENGINE_API_KEY`：火山引擎 ARK，优先使用
- `DASHSCOPE_CODING_API_KEY`：DashScope，作为备用 Provider
- 两者都配置时，主 Provider 失败会自动切换备用 Provider
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

需要后台管理账号时执行：

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

- 前端：<http://localhost:5173>
- 后端 API：<http://localhost:9527/api/news/>
- Django Admin：<http://localhost:9527/admin/>

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

访问 <http://localhost:9527>。生产环境建议：

- 设置 `DJANGO_DEBUG=0`
- 使用稳定且保密的 `DJANGO_SECRET_KEY`
- 将 `DJANGO_ALLOWED_HOSTS` 改为实际域名
- 在反向代理或防火墙层限制访问来源
- 通过 systemd、容器编排或进程管理器托管 Waitress

## 5. 服务控制和日志

```bash
./scripts/news-server start|stop|restart|status|log
./scripts/news-dev start|stop|restart|status|build|log
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
./scripts/news-cron start     # 启动 crond（系统需提供 crond/crontab）
./scripts/news-cron status
./scripts/news-cron log
```

翻译网络恢复检查：

```bash
./scripts/check_translation_network.sh
```

生产环境应使用系统级 cron 或任务调度器，并确认脚本、Python 环境和日志目录使用绝对路径。

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

检查根目录 `.env` 中至少一个 Provider Key 非空，然后重启后端。环境变量只在进程启动时加载。

### 语义搜索不可用或首次启动很慢

确认可访问 Hugging Face，等待模型下载完成；也可以先使用关键词搜索。模型下载完成后会复用本地缓存。

### `npm ci` 报安全漏洞

先查看：

```bash
cd frontend
npm audit
```

不要在未审阅 lockfile 变化前直接执行 `npm audit fix`。
