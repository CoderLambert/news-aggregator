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
| T04 | safe_http、Provider、Scrapy handler、诊断/研究；WAL 多进程预算 | 已验证并提交；Feed errback 持久状态在 T05 接入 |
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

## T04 实际结果

新增 request_budget 与执行上下文。所有真实新闻 HTTP 在 safe_http 或 Scrapy 下载 handler 边界领取 host/配额组/Reader 凭据及两个 global slot；任何 scope 失败整笔回滚。SQLite 条件写取得 writer reservation 后刷新时间并续成 30 秒 permit，实际发送前复核 token/剩余期限。忙锁有界等待且 fail closed，不改变应用默认 30 秒超时、数据库路径或 WAL。释放只匹配自己的 token。Jina 的实际主机、不可逆凭据指纹和逻辑文章来源在重定向后仍共享范围。

429、503+Retry-After 与已审核 GitHub 配额头持久延长冷却；秒数/HTTP 日期/非法/过去/极远日期均有测试。成功只重置失败 streak，不清冷却。safe_http 在读取错误页前保存冷却；过大/压缩 429 也不能隐藏状态。保留 DNS/IP 固定、2 MiB 正文响应限制、15 秒总期限和 3 跳上限；DNS 线程仍最多两个，改为 daemon，系统解析阻塞不会阻碍 Worker 退出。

FetchResult/FetchError 新增稳定错误字段。各 Provider 移除即时重试；429、认证、站点阻断、网络及 5xx 停止该链路。跨 Provider 共享 60 秒/5 请求与取消/租约检查，嵌套不重置；额度耗尽不再启动后续 Provider 或 socket。默认链不再使用 Jina-first 或独立 subprocess。comparison、只读 fetch_article_url 和研究 Reader 同样受预算；研究输出标为 excerpt 并复用既有 JinaFallbackPolicy。Reader 不丢业务 query 后冒充相同文章；BBC at_medium 是现有样本明确的跟踪参数。

Scrapy 薄包装维护的 HTTP11 handler，HTTP/HTTPS 均接入，通过异步 ORM 桥接等待并给下载加 15 秒可取消期限。公开 headers_received/bytes_received 与 StopDownload 保留过大错误页的 HTTP 状态后再记冷却；压缩前后响应有界。robots、redirect、retry 都经过 handler。最终礼貌设置在 create_crawler 后应用，429/401/403/503 不立即重试，其他受限重试最多一次。直接 Scrapy CLI 共用 Django 初始化；显式 asyncio reactor，关闭 Scrapy 2.19 新增控制监听器。

接口依据实际安装 Scrapy 2.19.0 及 [官方 download handler 文档](https://docs.scrapy.org/en/latest/topics/download-handlers.html)，使用公开方法/信号，不复制 HTTP 实现。保留旧 handler 的 spider 参数兼容桥接；没有升级全项目依赖约束。

最终相关子集实际 **231 passed**（Python 3.12.14），包括 request_budget、budgeted_safe_http、safe_http、article_fetcher_security、article_fetcher、full_content_status_service、research_tool_cancellation、provider_comparison_service/API/command、tests/crawler、news_ingestion、budgeted_download_handler。独立进程使用临时文件 SQLite，断言 WAL、同主机最大 1/全局最大 2、kill 后预算与 News lease 接管、旧成功/失败/token 不写回、忙锁 fail closed 与连接 timeout 恢复。受控本地滴流 HTTP server 验证总期限、socket 关闭、permit 释放及超大 429 的冷却；没有请求真实站点制造 429。

`manage.py check` 实际无问题；`makemigrations --check --dry-run` 实际 No changes detected；`git diff --check` 通过。直接 `scrapy crawl reuters` 在显式临时 DJANGO_DB_PATH 下退出 0，outcome=unsupported、无 HTTP；没有操作业务库。其 Pipeline spider 参数弃用提示将在 T05 的 from_crawler/receipt 接入一并处理。

T04 的 transport 会返回/传播延期，Feed next_poll_at 与 receipt/checkpoint 尚须 T05 持久结算。新 Worker/API/UI/发布集合、全部现有 CI 与来源启用抽样尚未完成；不具备生产发布条件。

### 后续契约审查

T05/来源适配前补充 T03 的边界：统一 Unicode 空白可用性；已审核短正文与派生摘录相同不能被摘要启发式否定；片段清理只移除非正文元素/指定页脚；DEV canonical 署名证据；矛盾的相同上游版本不能被更新时间放行。随后继续 T05–T12，不缩减原合同。


## T03 合同边界补充

已完成上节契约审查的五项修正。SQL 与 Python 使用相同的 Unicode 空白集合；未上线的 0036 数据迁移同步冻结该集合，并用文件库验证 Unicode 空白历史正文仍 missing/revision=0。审核过的 API/Feed 短正文不会因派生摘录相同而拒收；通用网页/Reader 的摘要诊断保留。HTML 片段只去除脚本、表单等非正文元素与明确指定页脚，保留正文 header、订阅技术演示等语义节点，代码里的订阅提示不当作付费墙。

同一个上游版本的不同正文，即使修改时间更新也拒收；等价时区表示规范为 UTC，不单独触发 revision。合法 DEV 外站 canonical 作为署名证据保存，目标 URL 不变，非法 canonical 拒收。validator_version 为 ingestion-2；证据加入规范 canonical 与内容类型，unknown 可由合法候选确认为实际类型。

实际相关回归 **140 passed**，包括 news_ingestion、状态服务/模型、迁移、crawler、article_fetcher 与 site_rules；`makemigrations --check --dry-run` 实际 No changes detected，`git diff --check` 通过。没有运行生产迁移。

下一步为 T05：feedparser 6.x、公用时区日期解析、策略签名、完整枚举 receipt、Pipeline 提交后结算、FeedState CAS 与异常延期。T06–T12 仍待实施，完整开发完成定义未满足，goal 保持 active。
