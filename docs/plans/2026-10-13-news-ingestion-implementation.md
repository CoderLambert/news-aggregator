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
| T02 | News 七字段、三表、迁移；空库与历史数据 | 已验证并提交 |
| T03 | ingestion、候选验证、正文 CAS、admin、可用性；版本及 lease 竞态 | 核心合同已验证并提交；适配器后续接入 |
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

## T02 实际结果

迁移为 `0036_news_ingestion_contract`：News 七字段、四种兼容任务状态、status/next_attempt_at 复合索引，以及 NewsSourceItem、FeedState、RequestBudget。历史非空正文标记 legacy/revision=1，空或常见空白正文 missing/revision=0；不提升为 complete、不建立任务、不修改调度/来源开关。列表只增加轻量状态字段，证据和正文仍不进列表。

统一 Python/数据库可用性 helper 按 state 与去空白正文判断，刷新失败或冷却不影响可读正文；success + 空白正文不可用。

实际验证：Python 3.12 环境运行 `test_ingestion_migration.py`、`test_full_content_status_model.py` 和 `tests/crawler/` 共 **27 passed**。两个迁移场景由独立子进程使用新建临时文件库，并断言 WAL、正文/译文/收藏/聊天保留、无隐式任务、开关未变。`makemigrations --check --dry-run` 返回 **No changes detected**；`git diff --check` 通过。所有迁移命令均显式设置临时 DJANGO_DB_PATH，没有访问随带业务库。

## T03 实际结果

新增 article_identity、source_policy、news_ingestion。SourcePolicy 明确列出 31 个来源，字段/端点/格式准入不由响应中的 trusted 标志决定。不可变 FullContentCandidate 仍验证运行时字段类型、目标 URL、来源 ID、字段契约、完整性和容量。HTML 片段公开转换函数保留代码、图片、列表、表格；网页提取先选站点节点，再考虑通用节点，不回退整页 body。

身份依来源 ID、规范真实 URL 定位；多来源映射保留主来源；只定向更新元数据。正文写入集中在 commit_candidate：URL/revision 条件更新，Worker 额外匹配 claimed_at lease；无租约 mark_success/mark_failed 不再写穿。Feed 有意义的新证据可以 fence 当前 Worker，纯同正文/证据重放不取消刷新。旧版本、同版本异内容和无序版本冲突拒收；有比较依据的新版本可变短；观察时间不触发 revision。正文变更原子清当前 legacy 译文与推荐问题，正文相同保留译文。推荐问题保存新增 revision CAS。身份修正保留旧文本供审计并标记 missing，旧执行者不能写回。

正文 admin 字段及 URL 只读。enqueue/claim/release 的服务合同先建立：只领取明确、到期任务；取消返回 queued 并保留意图；force 不取消其他 lease。预算冷却、常驻 Worker、API/消费者尚需 T04/T08/T09 接入，**本阶段不是可发布的兼容集合**。旧 Provider/CLI 尚未全部产出类型化候选，未经候选验证的结果现在不能保存；将在 T04–T07/T08 完成适配，不使用不安全兼容写穿。

最终相关子集实际 **140 passed**（Python 3.12.14）：test_news_ingestion、test_full_content_status_service、tests/crawler、test_full_content_status_model、test_ingestion_migration、test_article_fetcher、test_article_site_rules、test_suggested_questions。覆盖结构化短正文、长截断/挑战文本、真实 ID 冲突、同域错误路径、批准的主机别名、多来源发现、URL/revision/lease 旧结果、同正文刷新、翻译保留、慢推荐问题 fencing 和迁移。未声称这些内存库测试证明多进程预算；真实文件 WAL 多进程预算/租约测试将在 T04 增加。

`manage.py check` 实际无问题；`makemigrations --check --dry-run` 实际 No changes detected；`git diff --check` 通过。初次网页提取回归发现旧雷峰 Provider 把片段送网页选择器，已改用片段函数并重跑。完整 CI、前端、发布门禁、生产来源抽样均尚未完成。

后续先做 T04：类型化失败、原子共享预算、safe_http 每跳及 Scrapy handler 的真实传输准入；再推进 Feed receipt/checkpoint。保持目标 active，完成定义八项尚未全部满足。
