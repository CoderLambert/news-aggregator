# 新闻获取实施记录

## T00 实施基线

- 2026-10-13 在干净工作区读取仓库、设计合同、现有 CI、全文历史文档与相关实现后，执行 `git fetch origin main`。
- 实际最新 `origin/main`：`7990f7c3733ed90b67d3f69a51395f0385eb22fa`。
- 初始本地 main：`1b9d33eeb8c74cc0df9946a2b1a7f776a06e3e7a`，只增加本设计文档；没有回退或覆盖 TTS/UI 改动。
- 仓库及已检查的上级目录没有 AGENTS.md/CLAUDE.md。设计原文件移到合同指定的 plans 路径，原路径保留导航。
- 已有状态字段、safe_http 地址固定/响应限制、时间租约 fencing、翻译 source hash、ArticleFetchEvent、JinaFallbackPolicy、crawler 调度和发布门禁继续复用。没有发现本方案的身份、FeedState、RequestBudget 或持久正文队列实现。
- 最新迁移为 `0035_article_fetch_monitoring`，下一编号以实际生成结果为准。
- 初始本地环境：Python 3.14.8、Django 6.1、Scrapy 2.18.0；feedparser 未安装。另建 Python 3.12 验证环境，版本与结果待运行后补记。
- 历史文档中的 Jina-first、无租约正文写入示例和历史测试数字不作为本次行为或验证证据。

## 改动与验证映射

| 阶段 | 路径与验证边界 | 进度 |
| --- | --- | --- |
| T01 | 伪来源、雷峰网、Pipeline、crawler_control；身份与并发字段保护 | 已验证并提交 |
| T02 | News 七字段、三表、迁移；空库与历史数据 | 待实施 |
| T03 | ingestion、候选验证、正文 CAS、admin、可用性；版本及 lease 竞态 | 待实施 |
| T04 | safe_http、Provider、Scrapy handler、诊断/研究；WAL 多进程预算 | 待实施 |
| T05 | Feed 解析、条件状态、receipt；失败不推进 checkpoint | 待实施 |
| T06 | DEV/HN/首批全文 Feed；按来源契约 fixtures | 待实施 |
| T07 | TC 与其余来源；31 来源策略及降级 | 待实施 |
| T08 | 常驻 Worker、心跳、队列、旧命令；恢复/取消/无隐式回填 | 待实施 |
| T09 | API、前端、翻译/聊天/研究/TTS；排队与正文可用性 | 待实施 |
| T10 | Compose、发布/恢复/旧版本；现有 release gates | 待实施 |
| T11 | 有证据的修复与有限补排；dry-run/冲突/反向 CAS | 待实施 |
| T12 | 指标、完整 CI 与完成定义审计 | 待实施 |

未部署生产，未修改真实 scheduler/来源开关，未修复线上数据或触发回填。当前记录不代表开发完成或生产来源启用验收。

## T01 实际结果

删除 Reuters 搜索 URL、机器之心标题 slug 和无效 36kr Feed 获取/解析路径；运行代码报告 unsupported，不发这些入口的 HTTP。新建目标默认隔离，已有目标开关不修改。新雷峰网条目与目标显示名为雷峰网，历史来源未改。

Pipeline 不再以 title_hash 合并文章，不再按摘要长度决定更新，不再整行保存 News。精确 URL 元数据更新保留并发正文、译文、状态和推荐问题；缺失发布时间不覆盖旧值。NEWS_CRAWL_ONLY 约定保留。

验证命令：`PYTHONPATH=backend:crawler RUN_MAIN=true DJANGO_ENV=development DJANGO_DB_PATH=/tmp/newshub-ingestion-t01-py312.sqlite3 /tmp/newshub-ingestion-venv/bin/python -m pytest -q tests/crawler/`，实际 **20 passed**。首次运行发现 Scrapy 只在启动后提供 stats，已改为 spider_opened 信号记录并重跑通过。

隔离验证环境按 CI 先安装 CPU Torch 2.14.1+cpu，再安装 requirements：Python 3.12.14、Django 6.1.2、Scrapy 2.19.0、pytest 9.1.1。没有升级仓库虚拟环境或依赖约束。后续完整 CI 尚未运行。
