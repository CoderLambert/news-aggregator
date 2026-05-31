# NewsHub — AI 驱动的智能新闻聚合器

> 一站式科技资讯聚合 + AI 翻译 + 智能对话助手，聚焦中文技术社区阅读体验。

## ✨ 功能概览

| 模块 | 能力 |
|------|------|
| **新闻聚合** | Scrapy 爬虫抓取多源科技资讯，自动分类存储 |
| **AI 翻译** | Volcengine/DashScope 双 Provider Failover，SSE 流式输出中文翻译 |
| **智能助手** | 基于文章全文的多轮对话，自动抓取原文，推荐问题一键换批 |
| **页内搜索** | Ctrl+F 式全文高亮 + 上下跳转计数 |
| **文章目录** | 右侧悬浮 TOC 面板，IntersectionObserver 实时追踪当前阅读位置 |
| **代码块复制** | Markdown 代码块一键复制按钮 |
| **吉祥物交互** | "小闻" 小狐狸动画表情，6 种心情状态随对话切换 |

## 🛠 技术栈

```
Frontend:  React 19 + Vite 8 + Tailwind 4 + shadcn/ui + React Compiler
Backend:   Django 6 + DRF + SQLite + Scrapy
AI:        Volcengine ARK (Doubao) / DashScope (Kimi) — 双通道自动切换
测试:      Vitest + Testing Library (前端) | pytest-django (后端)
```

## 📋 环境要求

- **Python** ≥ 3.11
- **Node.js** ≥ 20（推荐 22+）
- **npm** ≥ 9
- 至少一个 LLM API Key（Volcengine 或 DashScope）

## 🚀 快速开始

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

在项目根目录创建 `.env` 文件（参考 `.env.example`）：

```bash
# 必填：Django 密钥（生产环境务必自定义）
# 生成方式：python -c "from secrets import token_urlsafe; print(token_urlsafe(60))"
DJANGO_SECRET_KEY=你的密钥

# 可选：调试模式（默认开启）
DJANGO_DEBUG=1

# 可选：允许的主机（默认 *）
DJANGO_ALLOWED_HOSTS=*

# ====== LLM Provider 配置（至少配一个） ======

# 主 Provider：火山引擎 ARK（推荐，Doubao 模型）
# 获取方式：https://www.volcengine.com/docs/82379
# Key 格式：ark-xxxxxxxx
VOLCENGINE_API_KEY=ark-你的key

# 备用 Provider：阿里云 DashScope Coding
# 获取方式：https://help.aliyun.com/zh/dashscope
# Key 格式：sk-xxxxxxxx
DASHSCOPE_CODING_API_KEY=sk-你的key
```

> **Key 格式说明：** `ark-` 开头的 key 自动走 Volcengine 通道，`sk-` 开头的走 DashScope 通道。系统会自动识别，无需额外配置。如果两个都配了，Volcengine 优先，失败自动切换 DashScope。

> **兼容提示：** 如果未在 `.env` 中配置 API Key，系统会尝试读取 `~/.hermes/config.yaml` 中的 `model.api_key` 字段（Hermes Agent 用户兼容）。

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

**方式 A：开发模式（推荐）**

```bash
# 终端 1 — 启动后端
cd backend
source venv/bin/activate
python manage.py runserver 0.0.0.0:9527

# 终端 2 — 启动前端开发服务器
cd frontend
npm run dev
# 访问 http://localhost:5173
```

**方式 B：生产模式（Waitress + 静态文件）**

```bash
# 构建前端
cd frontend && npm run build

# 启动 Waitress 服务（自动加载前端 dist 目录）
pip install waitress
cd /path/to/news-aggregator
python start_waitress.py
# 访问 http://localhost:9527
```

### 6. 抓取新闻数据

```bash
cd backend
source venv/bin/activate

# 抓取所有源
python manage.py crawl all

# 抓取指定源
python manage.py crawl hackernews
```

也可以设置定时任务：

```bash
# 使用项目提供的 cron 脚本
./scripts/crawl_cron.sh
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
│   │   ├── models.py         # 数据模型（News, Source, Category, ChatSession）
│   │   ├── views.py          # API 视图（CRUD + 翻译 + 聊天）
│   │   ├── serializers.py    # DRF 序列化器
│   │   ├── services/
│   │   │   ├── llm_translator.py    # LLM 翻译 + 双 Provider Failover
│   │   │   └── translation_jobs.py  # 后台翻译 Job 管理
│   │   └── tests/            # pytest 测试
│   ├── newsaggregator/       # Django 项目配置
│   │   └── settings.py
│   └── requirements.txt
├── frontend/                 # React 前端
│   ├── src/
│   │   ├── pages/            # 页面组件（Home, NewsDetail）
│   │   ├── components/       # UI 组件
│   │   │   ├── ui/           # shadcn/ui 基础组件
│   │   │   ├── news-detail/  # 详情页子组件
│   │   │   └── chat/         # AI 聊天组件
│   │   ├── hooks/            # 自定义 Hooks
│   │   ├── services/         # API 服务层
│   │   └── constants/        # 常量定义
│   ├── vite.config.js        # Vite + React Compiler + 代理配置
│   └── package.json
├── crawler/                  # Scrapy 爬虫
│   └── news_crawler/
│       └── spiders/          # 各数据源 Spider
├── scripts/                  # 运维脚本
│   ├── news-server           # Django 服务管理
│   ├── news-dev              # Vite 开发服务器管理
│   ├── crawl_cron.sh         # 定时爬虫
│   └── run_tests.sh          # 全量测试
├── start_waitress.py         # Waitress 生产启动脚本
├── .env.example              # 环境变量模板
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
| GET | `/api/categories/` | 分类列表 |
| GET | `/api/sources/` | 来源列表 |

## ⚙️ 高级配置

### LLM Provider 切换逻辑

```
请求 → Volcengine (Doubao) → 成功 ✓
                           → 失败 → DashScope (Kimi) → 成功 ✓
                                                     → 失败 → 友好 fallback 提示
```

- 翻译和聊天均支持自动 Failover
- `ark-` 前缀 key → Volcengine；`sk-` 前缀 key → DashScope
- 全部失败时返回中文友好提示，不会暴露技术错误

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
