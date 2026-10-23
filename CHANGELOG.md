# Changelog

## Unreleased

### 新增
- **统一服务健康检查**
  - 新增只读 `runtime_health` 管理命令和 `news health` 本地入口，汇总数据库、RSS、频道处理、搜索索引、翻译 Redis 与 AI 网关状态
  - 超级管理员可在运行管理页查看同一版本化状态；检查不会调用模型、Provider 或订阅源，已启用服务异常时命令返回非零


- **OPML 批量导入加速**
  - 普通用户公平共享空闲的 12 路突发容量；活跃超级管理员批量导入优先取得槽位
  - 四条远端结果不明操作不再冻结管理员其余批次，安全对账也会借用空闲容量；单 Feed 防重发、同域名冷却、租约和降权 fence 保持不变
- **两级个人频道分组**
  - 个人分组现在使用严格的“根分类 / 子分组 / 频道”结构；现有子分组、成员关系和读取偏好迁移时保持原 ID
  - 分组管理支持根分类与子分组的创建、重命名、移动和安全删除，所有阅读范围与成员操作仍只使用子分组
  - 智能整理分为“整理层级”和“整理频道”；AI 层级移动与新根/子分组路径必须先预览确认，并支持按版本安全撤销
  - OPML 导入导出保留根/子路径；RSS 延迟操作在提交和完成时都重新校验子分组归属
- **AI 自动分组**
  - 批量分析未分组或全部已订阅频道，优先复用已有子分组，并可建议最多八条完整根/子分组路径
  - 所有 AI 建议先集中预览；一次确认后原子创建获批路径和频道归属，支持安全撤销本次新增关系
  - 保留免费规则匹配和固定主题模板；可靠规则可复用已有子分组，AI 和分类创建始终需要确认

### 修复
- **智能频道 Worker 模型授权**
  - 专用 `channel-worker` 现在显式继承 `AI_BYOK_ENABLED`，避免网页已启用个人模型而后台层级整理仍以 `authorization_changed` 失败
- **本地 ChatGPT 订阅入口**
  - 本地授权起始页会采用显式可信的 `127.0.0.1` HTTP 来源，不再把前端入口固定为 5173；OAuth handoff 与 callback 仍固定在受控的 9527 端口

## v0.2.0 (2026-05-31)

### 🎉 新增功能

- **LLM 翻译系统**
  - 集成 DashScope Coding Plan (kimi-k2.5 模型) 进行高质量中文翻译
  - SSE 流式翻译，实时显示翻译进度
  - 支持"重新翻译"按钮，可强制刷新翻译结果
  - 自动扫描文章内的中文翻译链接 (如 README_zh_CN.md)，优先复用

- **AI 聊天助手**
  - 基于文章内容的多轮对话聊天
  - SSE 流式响应，实时显示回答
  - 聊天记录持久化到数据库 (ChatSession 模型)
  - 支持清空聊天历史

- **GitHub 内容清理**
  - 新增 `content_cleaner.py` 专门清理 Jina Reader 抓取的页面噪音
  - 自动去除导航菜单、文件树、侧边栏、Footer 等无关内容
  - FlClash 文章从 31KB 降至 2.2KB (去除 93% 噪音)

- **翻译进度持久化**
  - 翻译过程中每 500 字符自动保存到数据库
  - 页面刷新后自动恢复翻译状态
  - 10 分钟内自动清理过期标记

### 🔧 修复

- **移动端横向滚动问题**
  - 全局添加 `overflow-x-hidden` 和 `break-words`
  - 约束 `markstream-react` 的 NodeRenderer 组件宽度
  - 代码块表格允许内部滚动但不撑破页面

- **代码块样式**
  - 背景色从 `bg-gray-900` (深灰) 改为 `bg-gray-50` (浅灰)
  - 添加细边框和等宽字体
  - 解决深色背景 + 浅色文字看不清的问题

- **useRef 未导入导致的页面崩溃**
  - 修复 `NewsDetail.jsx` 中缺失的 `useRef` import
  - 所有页面现在可以正常加载

- **`undefinedshell` 内容问题**
  - 清理数据库中所有包含 `undefinedshell` 的文章内容
  - Jina Reader 抓取的代码块语言标签错误已修复

### 🧪 测试体系

- **新增 29 个自动化测试**
  - `test_content_cleaner.py` - 13 个测试 (GitHub 内容清理)
  - `test_llm_translator.py` - 10 个测试 (翻译服务)
  - `test_api_views.py` - 6 个测试 (API 端点)
  - `test_spiders.py` - 爬虫测试

- **构建验证脚本**
  - `scripts/validate_build.py` - 前端构建后自动检查
  - 检查 dist 目录、JS 导入、CSS 文件、包大小

- **TDD 开发流程**
  - 安装 `test-driven-development` skill
  - 强制 RED-GREEN-REFACTOR 开发流程
  - 所有新功能必须先写测试

### 📦 其他

- 新增 `ChatSession` 数据库模型 (迁移 0007)
- 新增 `full_content_zh` 字段 (迁移 0006)
- 新增 Waitress WSGI 启动脚本 `start_waitress.py`
- 新增 `TESTING.md` 测试指南
- 新增 `pytest.ini` 测试配置

---

## v0.1.0 (2026-05-30)

- 初始版本：Scrapy 爬虫 + Django 后端 + React 前端
- 支持 Hacker News、BBC、Reuters、GitHub Trending 等 7 个来源
- 向量语义搜索 (嵌入模型)
- 移动端适配
