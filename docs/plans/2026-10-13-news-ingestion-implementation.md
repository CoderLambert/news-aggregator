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
| T05 | Feed 解析、条件状态、receipt；失败不推进 checkpoint | 已验证并提交 |
| T06 | DEV/HN/首批全文 Feed；按来源契约 fixtures | 已验证并提交 |
| T07 | TC 与其余来源；31 来源策略及降级 | 已验证并提交 |
| T08 | 常驻 Worker、心跳、队列、旧命令；恢复/取消/无隐式回填 | 已验证并提交 |
| T09 | API、前端、翻译/聊天/研究/TTS；排队与正文可用性 | 已验证并提交 |
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


## T05 实际结果

feedparser 6.x 只解析有界 bytes，不接收 URL；实际验证版本为 6.0.14。公共时间解析保留有时区的发布时间/修改时间，不把缺失时间补成抓取时间，也不让 feedparser 的 published 别名伪造 updated。RSS、Atom 完整枚举，真正空 Feed 与 HTML/损坏 Feed 分开；批准的 HTML/text 正文字段成为类型化候选，media_content 不作为正文。

FeedState 保存策略签名、条件头和经过审核的有效端点。策略/正文准入变化清条件头并重放；添加别的来源不改变当前来源签名。条件头只发给已经提交表示的端点，重定向中跨 URL 移除。304 需要可靠 checkpoint 和本次条件请求，否则清头等待无条件重抓。成功时间、ETag 和 Last-Modified 在全部枚举及 Pipeline 已提交/明确策略跳过后，以 revision CAS 一起保存。

receipt 区分已提交、策略跳过、延期、失败；重复信号不能把延期变成成功。中断、失败、未结算、未完全枚举及 checkpoint CAS 冲突都不会推进表示。Pipeline 通过显式 IngestResult 结算；spider_closed 等待活动 Pipeline 任务。WebKit 首先接入共享生命周期，其余来源在 T06/T07 接入。

实际相关回归 **180 passed**：全部 crawler、feed_state/feed_support、news_ingestion、正文状态服务、article_fetcher/site_rules、迁移。独立 receipt 故障覆盖包含取消、重复信号、正常关闭等待与 CAS 冲突。完整 Scrapy/Pipeline 测试在临时文件数据库与受控本地 HTTP proxy 上证明：第一次第二条目入库失败不保存 ETag，第二次重放补齐且不重复正文 revision，第三次才发送 ETag 并接受 304。没有联系真实发布者。`makemigrations --check --dry-run` 实际 No changes detected；`git diff --check` 通过。

T06–T12 和完整 CI/发布集合仍待完成，未操作生产来源开关、数据或部署。


## T06 实际结果

雷峰网、WebKit、Smashing、V8、Mozilla、Svelte、Angular 使用共同 Feed lifecycle，正文直接成为 Pipeline 候选，不逐条请求文章 HTML。每个来源保持独立字段/格式合同、opaque ID 与链接。七来源 105 个独立本地 fixture 场景验证短正文、长正文尾部、代码/图片/列表/表格、摘要隔离、真实输入身份、日期、截断/挑战/付费墙及页脚处理。测试发现 feedparser 默认清理丢失 data-paywall 证据，已关闭 parser 的提前 sanitize，完整性验证后再执行片段清理；全部场景通过。这些 synthetic fixtures 不冒充生产抽样。

DEV 保留既有选题查询范围，跨标签按数字 ID 去重。发现事务先提交元数据与符合自动准入配置的任务，再最多前移 20 个最近七天、可靠发布时间、需要正文/明确较新 edited_at 的详情请求；其余元数据和任务保留。结构化开关关闭时无详情请求。详情按请求前 URL/revision、数字 ID 验证，完整 Markdown 不截断，失败仍产出列表元数据。只有 edited_at 提供修改证据，published_at 保留发布时间；updated_at/观察时间不代替。字段/ID/路径接口依据 [Forem 官方 API 文档](https://developers.forem.com/api/v1)。

专用 DEV Provider 支持已有来源数字 ID 或官方精确作者/slug 路径接口，验证响应 URL/ID/标题；DEV 默认链只访问 API。HN 自帖仅官方 item.text，短完整文本可写 discussion；外链以原始发布者 URL 保存 article，HN ID/讨论页为发现关系，不以分数或评论填正文。HN Provider 验证响应 ID/type 后再判断外链。GitHub Raw README 成为类型化 readme 候选，成功路径加入 provenance，下次优先复用并重新验证仓库绑定；共享预算和任务请求上限保留。DEV/HN/GitHub 的默认专用链不以通用 HTML 替代其阅读对象。逐篇默认链移除联网 LeiphoneFeedProvider（保留显式只读兼容类）。

实际相关回归 **321 passed**（Python 3.12.14）：全部 crawler、结构化 Providers、Feed 支持/状态、ingestion/正文 CAS、article_fetcher/site_rules、budgeted_safe_http/security。DEV 测试证明 23 条发现只前移 20 详情、跨标签不重复、溢出已排队；原始正文超过 5000 字完整保存；请求前 revision 陈旧不能重写；详情错 ID/URL/429/坏 JSON 保留元数据。`manage.py check` 实际无问题，`git diff --check` 通过。

T07–T12 与整体兼容发布/完整 CI 继续实施；没有真实来源开关变更或生产抽样请求。


## T07 实际结果

其余 15 个 Feed/API-Atom 来源使用共同生命周期，不逐条立即请求 HTML。BBC 保留三个频道与 namespaced thumbnail；InfoQ/DeepMind 的审核跳转关系继续保存。Ars/MIT 等未经逐条完整性与范围准入的正文不提升；即使收到很长 content:encoded 仍仅摘要。arXiv 保存真实 ID/版本/论文链接与 abstract；Product Hunt 为 product；Frontend Focus 的批准字段只绑定该期 newsletter，不能给外链冒充全文。GitHub Trending 保留原选择语义，显式 readme 类型与仓库 ID，观察时刻不充当发布时间。

Anthropic/Meta/Mistral 保留现有 HTML 发现，只跟实际页面链接，最多 20 个且严格域名/文章身份，修正相对链接解析；错误文章重定向不改变身份。只从有时区的机器可读发布时间解析可靠日期，缺失/本地文本日期明确 inferred，摘要有界。未猜 Feed/API。31 来源政策通过独立矩阵 fixtures，其中三隔离源始终 unsupported。

TechCrunchWPProvider 域名限定，独立 TECHCRUNCH_WP_ENABLED 严格 0/1、默认关闭。只请求精确 slug 或已验证 numeric post ID 与必要字段，选择唯一精确 permalink，不使用列表第一项。验证 ID/title/link/protected/片段完整性；date_gmt/modified_gmt 明确按 GMT。接口不支持与已知文章删除区分；429/401/403 结束整个链路。官方 numeric ID 保存正文 provenance，Feed GUID 保留原身份。协议依据 [WordPress 官方 posts 文档](https://developer.wordpress.org/rest-api/reference/posts/)，本地 fixture 结果不代表 TC 承诺的配额/SLA 或本次生产抽样。

通用 HTML 与已审核 Reader 现在也返回类型化候选：复用本条目真实来源映射 ID，实际响应端点、canonical/Reader URL Source 与标题校验，错文章 redirect 不可入库。Reader 保持现有开关/共享预算；抽象/产品描述不能升级为正文。DEV/HN/README 同样记录实际响应端点，不把 API redirect 的响应冒充原始端点。

实际相关回归 **432 passed**：全部 crawler、TechCrunch/结构化 Providers、article_fetcher/security、ingestion/正文 CAS、production_settings、VentureBeat 日期兼容测试。独立 74 个矩阵场景与 12 个 HTML 发现场景全部通过。后续实际响应端点检查补充后再跑 Provider 子集 **73 passed**。`makemigrations --check --dry-run` 实际 No changes detected；`git diff --check` 通过。没有实际 TC/API/新闻站点请求，没有生产开关变更。

T08–T12、Worker/API/UI/发布兼容集合与完整 CI 继续实施；goal 保持 active。


## T08 实际结果

auto_fetch_full_content 成为独立前台常驻进程，默认 disabled 仍存活。WorkerRuntime 的 flock/心跳默认生产共享 logs-data 路径，与容器 /tmp 无关；heartbeat 原子替换，每 10 秒独立写进程 owner、循环进展与 DB 状态。健康检查验证新鲜时间、实际锁持有者、同一 owner、严格布尔字段，禁用/空队列/长冷却仍可健康；不能用旧文件或字符串 false 冒充健康。运行/结构化/自动入队开关与来源白名单通过现有 runtime_config 解析，默认关闭/空集合，未知或隔离源拒绝。没有 ApiConfig/web 内正文 Worker 线程。

只执行 next_attempt_at 明确到期的持久任务，无历史 pending 扫描。每批最多 10 个、按来源循环且每来源优先级排序，保留已有正文的刷新任务。五分钟旧 lease（含无时间戳）通过 URL/revision/时间戳 CAS 恢复，不重置失败数，恢复及取消/新排队不早于持久 host 冷却。SIGTERM 停止领取并在下一 Provider/写正文前检查取消，释放自己的任务为 queued，保留优先级和失败数。预算延期不算真实失败，终止/耗尽不无限自动重试。

fetch_full_content 改为有界 enqueue/dry-run，保留来源、状态、重试、年龄、force 等筛选；force 只增加刷新意图，不改他人 lease 或冷却。backfill_full_content_scrapy 在开发环境为兼容 enqueue 别名；生产明确 CommandError 提示统一命令，没有 subprocess/独立抓取。限额必须 1–500，since/until 必须带时区；recent-only 仅最近七天、可靠来源日期、自动准入、无正文且无任务，过滤在限额前完成。after-id/next_after_id 支持混合历史选择的有限分批继续。未来日期不会前移 DEV 详情或自动排队。

实际相关回归 **436 passed**：Worker/命令、状态/ingestion、全部 crawler、真实进程 Worker、请求预算、production_settings、结构化/TC Providers、FeedState。8 个独立进程场景全部通过，显式临时文件 SQLite 断言 WAL、禁用/空队列心跳、不同 TMPDIR/cwd 的第二进程锁拒绝、损坏/过期/错 owner 心跳、不再持锁时健康失败、SIGTERM 45 秒内退出且不进第二 Provider、取消保留冷却、SIGKILL 后新 owner 与预算/正文 lease 恢复。所有 Provider/网络为受控替身，并禁止 publisher socket connect。后台失去 claim 的独立回归 **1 passed**。

`manage.py check` 实际无问题；`makemigrations --check --dry-run` 实际 No changes detected；`git diff --check` 通过。T09–T12、兼容部署配置及完整 CI 尚需完成，没有操作生产或隐式回填。

T08 旧命令生产分支补充回归实际 **4 passed**（test_backfill_scrapy_command）；生产入口明确拒绝且不创建任务。


## T09 实际结果

fetch-full 保留原鉴权/CSRF，已有可读正文返回 200；合法新请求/复用/刷新返回现有 detail schema 的 202、Location 与 Retry-After；Worker 禁用/不健康 503 不创建任务；身份/来源/阻断不支持 422。force 只提升刷新意图，保留当前 lease、计数和冷却。GET 详情/轮询不入队、不访问来源。

article_content 收口 read/enqueue/context_scope；聊天和研究普通文章工具没有 HTTP 内正文 Provider 链，services 不再反向导入 views。聊天 prompt 与 SSE article_context 范围一致；推荐问题返回 summary/full 范围并保留 revision CAS，缺正文可以使用摘要/既有 fallback。研究最多短等一秒数据库，排队/不可用返回真实 scope/state/next_attempt_at；截取标 excerpt，后续工具总容量截断仍保留范围。后端和前端研究时间线不把摘要/排队称为全文。语义/混合搜索的重新取行复用完整可用性过滤，修复脱离原过滤 queryset 的路径。

普通详情 state=missing 时隐去保留审计的正文/译文，译文 available/active/source/scope 均按当前可用性判断。共享/私人翻译读取、领取、任务当前性、发布与等待同时检查可读 state 和既有 source hash；隔离保留相同 raw/hash 也不能晚发布。原有历史公/私译文、账户代际、SSE 协议与权限不变；未就绪 SSE 增加 full_content_not_ready。TTS 使用同一可读谓词，刷新失败继续使用现有正文及内容绑定缓存。列表增轻量 has_full_content，SQL 仅选择可用布尔值、defer 大正文/证据，不带正文或全 provenance。审核文本重新成为可读正文时清除在 summary 范围产生的问题缓存，即使原始字符串相同。

前端新增字段与可用/任务分离，queued/rate_limited/可重试延期只 GET 轮询，按 next_attempt_at 等待并退避、最多三分钟；停止/离开页面只取消本地等待，服务端共享任务保留。已有正文刷新失败继续显示正文，同时显示本次刷新失败。卡片/搜索/全文区/朗读选项均使用可用性，不再仅看 success。慢旧 revision 的结果不能恢复更高 revision 的隔离文本。翻译的本地所有权包含正文 state/revision，恢复记录绑定 revision，旧正文任务不能恢复到新正文。聊天消费 scope 元数据并显示摘要/节选范围，移除空聊天“已读完文章”的不实文案。

还发现中文来源链接的旧裸 urllib 与研究搜索 HTTP 路径：统一走受控 Reader/安全预算传输；研究搜索一次逻辑上下文共享请求限额，429/预算延期不继续另一个搜索后备。没有将搜索节选存 News.full_content。

实际后端相关回归 **228 passed**：read/queue API、隔离消费者、聊天/问题、共享/订阅翻译、TTS、研究取消/HTTP路由、ingestion/正文 CAS。独立 22 场景证明同 hash 隔离仍拒绝公/私译文暴露/发布、历史保留，以及六种研究搜索组合筛选。旧测试的同步获取断言按新排队合同改写，历史正文 fixtures 显式 legacy 后，既有账户/source hash/权限回归仍通过。

完整前端 Vitest 实际 **481 passed / 66 files**；typecheck、lint（无 warning/error）、production build 全部实际通过。新增 queued/cooling、不重复 POST、局部停止、旧 revision、翻译恢复与聊天 scope 测试。按两份 React 最佳实践技能检查：保留懒加载和请求 owner fencing，effect 使用稳定依赖、取消清理；修复 render 中 Date.now 与缺失 hook dependency。`manage.py check` 实际无问题；`makemigrations --check --dry-run` 实际 No changes detected；`git diff --check` 通过。

T10–T12、既有全部后端 CI/release gates、兼容 Compose 与恢复测试尚需完成，当前还不具备生产发布条件。没有部署/真实开关或数据修改。
