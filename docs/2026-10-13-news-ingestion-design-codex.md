# NewsHub 新闻来源与正文可靠获取设计及 Codex 执行方案

本方案用于实施 news-aggregator 的新闻获取改造：优先使用发布者提供的 API、RSS 和 Atom，直接保存已经取得且通过校验的完整正文；只有缺少可信正文时才安排受限流约束的补抓。重点解决错误文章链接、摘要冒充正文、重复访问、429 重试放大、并发覆盖以及正文任务无法恢复的问题。

**设计结论：可以按本文分阶段实施。** 保留 Django、Scrapy、当前 SQLite 部署、现有抓取调度和全文状态服务。新增三个用途明确的小表，扩展 News 的正文状态，使用成熟 Feed 解析库和少量传输适配代码，不建设新的通用任务平台。

建议存入仓库：docs/plans/2026-10-13-news-ingestion-design-codex.md。

## 1 基线与执行范围

### 1.1 代码基线

| 项目 | 值 |
| --- | --- |
| 仓库 | [CoderLambert/news-aggregator][C00] |
| 关联需求 | [Issue 52][I52] |
| 核对日期 | 2026 年 10 月 13 日，Asia/Shanghai |
| main 提交 | 7990f7c3733ed90b67d3f69a51395f0385eb22fa |
| 提交说明 | ui: tighten assistant message spacing |
| 与上一轮 cf069a2 的差异 | 3 个提交，主要为 TTS 和界面；采集、正文校验、正文状态服务没有完成本需求的改造 |
| 仓库指令 | 此基线递归树中没有 AGENTS.md；实施前仍应检查届时最新仓库 |

以上基线来自 GitHub 分支和提交对比。[C00][C01]

本方案中的“现有”均指上述提交；“新增”“改为”“必须”描述待实施要求。端点样本来自同日上一轮的低频只读探测，说明接口类型与候选字段，不代表生产出口 IP 的成功率或长期 SLA。

Codex 开始工作时先 fetch 最新 main，再比较本方案涉及的路径。若只是无关 TTS/UI 变化，可保留它们继续实施；若已有同类实现，复用和补齐，不能重复创建模型、重复 Worker 或覆盖新修复。不得为了对齐此文档把仓库回退到旧提交。

### 1.2 与旧文档的关系

本文作为本需求的主实施设计。以下历史文档保留，但对来源优先级、正文入库入口、任务生命周期和本次实施顺序，以本文及最新代码为准：

- docs/full-content/phase-1-summary.md
- docs/plans/2026-06-01-full-content-fetcher-phase-2.md
- docs/plans/2026-06-01-scrapy-full-content-api.md

旧文档中的 Jina-first、历史工具流程、旧版本和旧测试通过数不能作为本次实施事实。可信 API/Feed 正文应经过共享验证及提交服务，无需为了满足旧流程再发一次网络请求。[C02]

### 1.3 本轮实施边界

实施新闻发现、来源身份、正文候选、正文验证、持久任务、共享请求预算、前端状态兼容以及必要的发布脚本适配。保留用户鉴权、BYOK、共享与私人翻译隔离、收藏、聊天历史、当前发布门禁。

当前阶段不引入 Celery、Redis、Kafka、浏览器集群、代理池或通用采集插件平台；不改推荐排序、向量模型或 TTS 传输；不把部署迁移等同于自动打开线上调度或历史回填。

## 2 必须解决的现有问题

| 代码事实 | 直接影响 | 设计中的修复 |
| --- | --- | --- |
| Reuters 从 Google News RSS 读标题后拼接 Reuters 搜索 URL；机器之心按标题猜文章路径 | 文章身份不真实，后续无法稳定得到对应正文 | 阻断伪 URL；只接收真实条目 URL/ID；不明记录隔离 |
| NewsItem 只有 content；Pipeline 不写可信全文；DEV 正文截断为 5000 字符 | 已拿到正文仍再次访问原站 | 类型化正文候选、共享校验和原子入库 |
| Pipeline 更新旧 News 时调用整行 save，元数据更新依赖内容变长 | 可能覆盖其他进程的全文或翻译；URL 修正可能被跳过 | 元数据定向更新；正文统一 CAS 提交 |
| Provider 内部立即重试，错误后继续下一个 Provider；没有共享的主机/配额预算 | 多入口叠加，429 后继续产生请求 | 真实 HTTP 边界统一准入，持久冷却，终止不合适的 fallback |
| 当前验证主要看长度、摘要相似度、宽松标题与 canonical 域名 | 同域错文章、长登录页、长截断页可能通过 | 来源字段契约、文章身份与完整性分别校验 |
| 多个 Feed 每轮逐条再抓 HTML；雷峰网 Provider 每篇再下载整个 Feed | 相同内容反复访问，旧文章离开 Feed 后还会补抓失败 | Feed 正文前移，ETag/Last-Modified，提交后推进 checkpoint |
| fetch-full 主要同步执行；Compose 没有常驻正文 Worker | Web 请求耗时，崩溃后恢复不可靠 | 持久排队、POST 202、受控常驻 Worker |
| 全文筛选依赖最近抓取状态 success | 未来刷新失败会让已有正文被误判不可用 | 正文可用性与任务状态分离 |
| 雷峰网写成“量子位”；多处日期解析失败后用当前时间 | 来源归属和新闻时间错误 | 稳定 source_key、正确映射、带时区日期及推断标记 |
| 新 Worker 不在现有发布脚本的进程清单中 | 迁移和恢复可能遗漏数据库写入者 | Compose、健康检查、发布/恢复流程同批适配 |

证据位置：Spider 与 Pipeline [C03][C04][C05]；正文 Provider、验证及状态 [C06][C07][C08]；API 和 Worker [C09][C10]；部署 [C11][C12]。

现有能力需要继续使用：生产 safe_http 的地址校验与固定、2 MiB 正文响应上限、15 秒总时限及最多 3 次跳转；正文租约 fencing；翻译 source hash；ArticleFetchEvent 和 JinaFallbackPolicy；CrawlerSettings/CrawlRun；robots 与 AutoThrottle。[C06][C08][C13][C14]

**不要写成“项目没有限流或安全 HTTP”。现有机制存在，缺口在跨入口协调、内容身份和完成语义。**

## 3 总体设计

~~~mermaid
flowchart TD
    A["官方 API 与发布者 Feed"] --> B["真实条目身份与版本"]
    B --> C{"已有完整正文候选"}
    C -->|有| D["共享正文验证"]
    C -->|无| E["News 持久正文任务"]
    D -->|通过| F["CAS 提交正文"]
    D -->|需要补齐| E
    E --> G["共享预算与安全 HTTP"]
    G --> H["专用 API 或正文 HTML"]
    H --> D
    F --> I["阅读 翻译 语音 研究"]
~~~ 

### 3.1 固定职责

| 模块 | 职责 |
| --- | --- |
| 现有 Spider | 发现真实条目；解析来源元数据；提交已有候选；不自行判定“可信即入库” |
| source_policy.py，新增 | 普通 Python 配置，描述已审核来源、正文字段、URL 范围、限流组和轮询规则 |
| feed_support.py / feed_state.py，新增 | Feed 解析和本轮完成计数；持久条件请求状态 |
| news_ingestion.py，新增 | 真实身份去重、元数据定向更新、正文候选与任务意图持久化 |
| article_fetcher 的 types / extractors / validators | 候选格式、HTML 清理、文章身份及正文完整性验证 |
| full_content_status.py，扩展 | 排队、领取、租约、提交、失败、过期恢复；唯一正文状态修改入口 |
| request_budget.py，新增 | SQLite 上的短事务准入、在途租约、服务端冷却 |
| 传输适配层 | Scrapy HTTP handler 薄包装；safe_http 每个实际请求都取得预算 |
| auto_fetch_full_content，改造 | 常驻正文任务消费者；按到期时间、来源和优先级执行 |
| API 与前端 | 读取已保存内容、请求排队、展示明确的状态和重试时间 |

正文网络抓取、正文候选验证、正文提交是三个边界。验证成功不能直接等同于数据库保存成功。

### 3.2 最小依赖原则

新增 Feed 解析依赖 feedparser，限定经 CI 验证的 6.x 版本范围，并在实施记录中写实际安装版本。由 Scrapy 获取响应，再调用 feedparser.parse(response.body)；禁止向 feedparser 传 URL 让它自行联网。其日期与条件请求文档可作为实现参考，但 HTTP 状态仍由项目控制。[D01]

HTML 清理先复用项目现有 BeautifulSoup 与 Markdown 转换代码。为 API/Feed 的 HTML 片段提取一个公开转换函数，避免正则去标签。Trafilatura 等额外提取器不作为本次基础改造的前置条件。

当前 requirements 只约束 scrapy>=2.11。下载 handler 的签名应按实施环境实际安装版本及对应官方文档实现；测试记录版本，不直接绑定某个新版本私有方法，也不顺手升级全项目依赖。[C15][D02]

## 4 来源接入矩阵

表中的“正文候选”表示该字段可以进入校验，不能直接承诺每条完整。全部沿用当前 spider.name 作为 source_key，避免来源改名后丢失身份。

### 4.1 首批来源

| source_key | 来源与入口性质 | 候选字段 | 接入规则 |
| --- | --- | --- | --- |
| devto | [DEV/Forem 文档化 API][D03] | 详情 body_markdown，或 body_html | 数字 ID；列表只发现；保留完整正文；详情去重和版本判断 |
| leiphone | [雷峰网发布者 Feed][S01] | description | 修正来源为雷峰网；仅该契约允许 description 作正文候选 |
| webkit | [WebKit Feed][S02] | content:encoded | 与 RSS 条目真实链接绑定 |
| smashing_magazine | [Smashing Feed][S03] | content:encoded | 去页脚；保留图片、列表及代码；不使用不存在的假定 WP API |
| v8 | [V8 Atom][S04] | Atom content | 保留 Atom 类型和更新时间；低发文频率不自动判定故障 |
| mozilla_hacks | [Mozilla Hacks Feed][S05] | content:encoded | 原摘要与正文分别处理 |
| svelte_blog | [Svelte Feed][S06] | description | 样本 Feed 接近 2 MiB，使用单独 Feed 大小上限 |
| angular_blog | [Angular 发布者 Feed][S07] | content:encoded | 清理 Medium 页脚与跟踪元素；GUID 与链接分别保存 |

同日样本确认这些入口存在结构化长正文。首个生产小范围启用选择 DEV、雷峰网、WebKit、Smashing、V8、Mozilla；Svelte、Angular 在各自契约测试和样本检查通过后加入。样本不能代替逐条验证，也不能保证已离开 Feed 的所有历史文章仍可恢复。

DEV 官方说明详情接口返回包含 HTML/Markdown 的文章对象；列表 API 不能代替详情 API。[D03]

### 4.2 其余来源逐项处理

| source_key | 来源 / 当前入口 | 正文策略 |
| --- | --- | --- |
| bbc | [BBC 官方 RSS][S08] | Feed 发现与摘要；有真实文章 URL 时按来源策略进入 HTML 队列 |
| techcrunch | [TC Feed][S09] + 发布者公开 WordPress REST 端点 | Feed 主要摘要；专用 WP Provider 先小范围开启，不能泛化扫描其他站点 wp-json |
| css_tricks | [CSS-Tricks Feed][S10] | 样本为摘要；不因其采用 WordPress 就假设全文 API 可用 |
| webdev | [web.dev Feed][S11] | 发现与摘要，正文按 HTML 策略 |
| chrome_dev | [Chrome Developers Feed][S12] | 发现与摘要 |
| react_blog | [React 官方 RSS][S13] | 发现与摘要 |
| openai_blog | [OpenAI News RSS][S14] | 发现与摘要；首次历史条目较多，禁止逐条立即补抓全库 |
| deepmind | [DeepMind RSS][S15] | 条目可能无摘要，不能因此抓取失败或伪造正文 |
| infoq | [InfoQ Feed][S16] | 发现与摘要；保存并验证入口到 feed.infoq.com 的跳转关系 |
| ars_technica_ai | [Ars AI Feed][S17] | 即使有 content:encoded 也按条目检查截断；未证明完整的只作摘要 |
| mit_tech_review_ai | [MIT Technology Review Feed][S18] | 样本有长正文候选；逐条完整性及使用范围审核，默认不承诺全站全文 |
| hackernews | [HN 官方 Firebase API][D04] | self-post text 可作 discussion 正文；外链条目正文来自原发布者，保留 HN 发现关系 |
| github | GitHub Trending HTML + 现有 README Provider | 阅读对象为 readme；保留 Trending 语义。README 官方接口是后续减少路径探测的独立优化，不以 REST 星标搜索替换 Trending |
| arxiv_ai | [arXiv 官方 API][D05] | content_kind=abstract，存摘要、论文 ID/版本及论文链接；不写 full_content、不自动抓论文 PDF |
| producthunt | [Product Hunt Feed][S19] | content_kind=product；产品简介与讨论链接不冒充新闻全文 |
| frontend_focus | [Frontend Focus RSS][S20] | content_kind=newsletter；可验证保存整期正文，不能当作本期每个外链的全文 |
| anthropic | 当前官网 HTML 列表 | 保留有界 HTML 发现；本轮未验证可替代的官方 Feed/API，不猜接口 |
| meta_ai | 当前官网 HTML 列表 | 同上 |
| mistral | 当前官网 HTML 列表 | 同上 |
| venturebeat_ai | [现有 VentureBeat AI Feed][S21] | 本轮未独立确认 Feed 正文字段；先发现和样本校验，不把 WP 端点的失败推导为 Feed 失败 |
| reuters | 当前 Google News RSS + 拼造搜索链接 | 暂停此实现；只有真实文章身份及有授权的 Reuters 官方交付渠道满足后重新接入 |
| jiqizhixin | 当前列表 API | 样本缺文章 ID/真实 URL/正文；停止按标题拼接 URL，在可靠接口出现前隔离 |
| sanliu_kr | 当前 36kr /feed | 样本为 HTML 而非有效 Feed；暂停该入口，不能把 200 HTML 标成成功 RSS |

这一矩阵覆盖当前 31 个 Spider。[C03] 正文覆盖率按 content_kind 和获取资格统计：discussion、abstract、product、readme、newsletter 不计入普通新闻正文覆盖率；HN 发现的外链媒体文章属于 article，可以计入。

Reuters 有正式 API、RSS/XML 等交付产品，接入需满足其授权条件；本方案不声称 Reuters 没有官方 RSS。[D06] TechCrunch 的公开 CMS 端点曾返回 content.rendered，但本轮没有证实它是对外承诺配额和 SLA 的开发者产品。WordPress 字段定义只说明协议，不证明某媒体保证开放。[D07]

## 5 数据模型和服务契约

### 5.1 News 新增七个字段

| 字段 | 类型 / 默认值 | 语义 |
| --- | --- | --- |
| content_kind | CharField(32)，unknown | unknown / article / discussion / readme / newsletter / abstract / product |
| full_content_state | CharField(16)，missing | missing / legacy / complete，与任务状态独立 |
| full_content_revision | PositiveBigIntegerField，0 | 已接受正文及身份/版本证据的 CAS 修订号 |
| full_content_provenance | JSONField，dict | 只保存已接受正文的来源与验证证据 |
| full_content_next_attempt_at | 可空 DateTimeField，索引 | NULL 表示未安排执行；有值表示到期可执行或等待重试 |
| full_content_priority | SmallIntegerField，0 | 用户显式请求高于普通后台任务；不能绕过限流 |
| full_content_error_code | CharField(64)，空字符串 | 稳定、可枚举的程序错误码 |

继续使用现有 full_content_fetch_status、retry_count、provider、quality_score、last_full_content_attempt 和全文/译文字段。增加必要 choices：queued、rate_limited、blocked、unsupported；保留旧 choices 兼容。

新增复合索引覆盖任务选择的 status 与 next_attempt_at；是否把 priority 加入同一索引由实际查询计划决定，不预建无用途索引。

统一正文可用谓词：

~~~python
state in {"legacy", "complete"} and trimmed(full_content) != ""
~~~

数据库侧复用 trimmed_text_expression，不在 Python 中逐条扫描。全文筛选暂保持“已有可阅读正文”的语义，包含 legacy；正文验证覆盖率只统计 complete。summary/partial 不写入 full_content。[C08]

revision 在接受新正文、提升 legacy 为 complete、改变已接受的上游版本证据或纠正目标身份时递增；完全相同正文及稳定证据为幂等 no-op。比较稳定证据时只看身份、body hash、来源字段、可比较的上游版本与 validator_version；accepted_at、fetched_at、last_seen_at、request_started_at 等观察时间不能单独触发修订。**正文 hash 用于内容相等，revision 用于并发顺序，两者不能混用。**

### 5.2 NewsSourceItem 身份映射表

新增一张小型来源身份索引，支持 DEV 多标签重复、HN 与发布者 Feed 指向同一 URL 等已有真实场景。

| 字段 | 用途 |
| --- | --- |
| source_key，CharField(64) | 当前 spider.name 或明确定义的专用 Provider 来源键 |
| upstream_id，CharField(1024) | 发布者 ID / GUID / 规范化真实 URL；不得截断 |
| news，ForeignKey(News, CASCADE) | 对应已有 News |
| discovery_url，URLField(1024) | 来源给出的条目/讨论链接 |
| first_seen_at / last_seen_at | 发现时间，不能冒充发布时间 |
| metadata，JSONField | feed_url、观察到的版本、源发布时间及其是否推断等少量元数据 |

唯一约束为 (source_key, upstream_id)。过长或缺失的身份拒收并计数，不截断后碰撞。没有 GUID 时以规范化真实文章 URL 作为上游身份；不要回退到标题 MD5。

保留 News.url 当前唯一约束。顺序固定为：来源 ID 映射 → 精确规范 URL → 创建 News + 映射。相同 URL 来自不同来源时增加映射，保留现有 News.source 作为主来源；未经明确证据不改它。来源 ID 相同但目标 URL 变化走身份修正，不另建重复 News。

创建竞争触发 IntegrityError 后，只重新读取冲突键并核对真实身份；不得把数据库重试扩展为再发网络请求。title_hash 可保留兼容，但不再据其直接合并或修正文章；跨源标题相似度只用于 related_to。

### 5.3 FeedState 条件请求表

字段：source_key、feed_url、etag、last_modified、revision、policy_version、last_checked_at、last_success_at、next_poll_at、validated_effective_url。

FeedState.policy_version 使用固定长度的有效策略签名：对来源契约版本、相关正文开关、来源准入和接收窗口等影响条目处理的配置规范序列化后求 hash。它不是只会手动增加的代码版本号；只改变网络间隔等不影响条目语义的配置不必触发重放。

唯一约束 (source_key, feed_url)。ETag/Last-Modified 只对应成功提交的那份 Feed 和响应 URL；保留原始 header 值，不把 Last-Modified 当成某篇文章发布时间。

只有确实经历批准的重定向，才保存 validated_effective_url。入口或有效 URL 变化时清除条件请求状态，不能把旧端点验证头发送给新域名。

### 5.4 RequestBudget 请求预算表

字段：key 主键、next_allowed_at、cooldown_until、lease_token、lease_expires_at、consecutive_failures。

采用单主机/配额组并发 1、两个共享全局 slot 的明确实现。全局行固定为 global:0 和 global:1；其他键按已审核来源创建，例如 host:dev.to、group:arxiv、credential:jina:configured-key-id。

凭据键只用内部 ID 或不可还原的指纹，不存密钥、完整 Authorization 或带敏感参数的 URL。策略放代码配置，表只保存运行状态。

这三个表各负责身份、Feed 进度、网络配额。不要额外创建通用 Job 表、候选队列表、缓存平台或 Feed 原始响应仓库。

### 5.5 正文候选

在 article_fetcher/types.py 定义不可变 FullContentCandidate，至少包括：

~~~python
source_key: str
source_item_id: str
target_url: str
retrieved_from_url: str
declared_canonical_url: str | None
title: str
content_kind: str
body_field: str
content_format: str              # markdown / html / text
declared_completeness: str       # full / partial / unknown
raw_content: str
source_modified_at: datetime | None
source_version: str | None
request_started_at: datetime
expected_revision: int | None
~~~

NewsItem 增加来源身份、内容类型、独立摘要、可选 body_candidate 和临时 feed_receipt_id。字段名统一，不同时创建 full_content、trusted_content、candidate_body 三套等价字段。

外部响应中的 trusted=true 或 declared_completeness=full 不能授予信任。只有 source_policy 中批准的“来源 + 端点 + 字段 + 内容类型”允许进入完整正文校验。Feed entry 内的 media:content 是媒体资源，不能与文章正文 content 混淆。

### 5.6 稳定错误契约

扩展 FetchResult / FetchError，使失败携带 error_code、http_status、retry_after_at、retryable、scope_keys；已有 provider/error/validation_reasons 保留兼容。控制逻辑不再从长字符串猜 429 或认证错误。

至少区分：not_applicable、rate_limited、budget_deferred、network_timeout、upstream_5xx、auth_required、access_blocked、not_found、invalid_identity、invalid_feed、body_partial、body_mismatch、body_empty、source_version_conflict、unsupported、persistence_conflict。另有 superseded 执行结果，表示任务已被更新的有效提交取代；它不是上游失败，不增加重试计数或触发 Jina 故障策略。

内部 budget_deferred / 取消异常必须跨 Provider catch-all 正确传播，不能被转换为普通失败后继续请求下一个 Provider。

## 6 真实身份与幂等入库

### 6.1 URL 与元数据规则

1. 文章 URL 必须来自发布者条目、官方 API 详情或验证过的跳转；拒绝搜索页、分类页、登录页以及按标题合成的路径。超过 News.url 现有长度限制时报告错误，不能截断。
2. URL 规范化只做确定安全的变化：scheme/host 大小写、默认端口、fragment，以及明确列出的 utm、fbclid 等追踪参数。保留业务 query、路径大小写和编码斜杠；尾斜杠、AMP、www 别名和 HTTP→HTTPS 只按站点规则或实际验证的跳转处理。
3. 文章身份比较必须包含路径/稳定 ID，不能只判断 canonical 同域名。DEV 的转载 canonical 可能指向另一发布者：把它保存为署名证据，不自动把 News.url 改到外站或立即跟抓外站。
4. 标题相似是辅助证据。HN 编辑过的标题不能否定一个已被官方条目及目标 URL 精确绑定的外链；反过来，同域同标题也不能证明 URL 是同一篇文章。
5. RFC 822 和 ISO 8601 日期保持时区并统一到 UTC。可复用 VentureBeat 已有 parsedate_to_datetime 逻辑。[C16]
6. 缺失/非法发布时间时，News.publish_time 因现有非空约束可暂取 first_seen_at，同时在 NewsSourceItem.metadata 记录 publish_time_inferred=true。前端详情显示“发现时间”；该值不作为自动补抓“近期新闻”的充分依据。
7. 不在重复采集时把发布时间重写为当前时间。上游明确修正时间时才能定向更新，并记录来源值。

摘要字段保持摘要、abstract 或产品简介语义。来源没有摘要但已取得完整正文时，可取正文首个有效段落形成有长度上限的列表摘录；不能用该摘录反过来否定同一候选的完整性。旧 News.content 角色不明时，不无条件作为“独立摘要”传给 summary_sized 校验。

### 6.2 入库事务

news_ingestion 接收一个来源条目，按以下顺序执行：

1. 在事务外完成格式、身份和正文候选的纯计算校验。
2. 根据 source_key/upstream_id 与规范 URL 解析 News 身份，处理唯一键竞争。
3. 在短事务中创建/更新身份映射，定向更新明确允许的元数据。
4. 有可接受候选时调用统一正文 CAS；没有候选但符合准入时持久化正文任务意图。
5. 事务提交后，才报告该条目 committed，供 Feed receipt 结算。

正文与候选入库应同属这一事务边界。一个无正文但任务已持久化的条目可以完成 Feed 接收；仅生成了临时 Python 对象、尚未提交任务字段则不算完成。

服务返回轻量 IngestResult，包含 news_id、receipt_outcome、reason。receipt_outcome 为 committed / policy_skip / deferred；未能处理的异常向上传播为 failed。Pipeline 在事务提交后按这一显式结果结算 receipt，signals 仅补充异常与一致性检查，不能把 item_scraped 无条件改写为 committed。

定向更新不得携带 full_content、全文状态、译文或用户关系的陈旧值。移除 Pipeline 的整行 news.save() 和“只有更长才更新”条件。保留 NEWS_CRAWL_ONLY=1 隔离翻译/embedding 的现有约定。[C04]

## 7 正文完整性与并发提交

### 7.1 校验顺序

| 检查层 | 通过条件 | 失败处理 |
| --- | --- | --- |
| 来源契约 | 来源、端点、body_field、格式和类型属于审核配置 | 不得升级为正文 |
| 文章身份 | 稳定 ID/目标 URL 精确绑定；标题及 canonical 无矛盾 | body_mismatch |
| 响应结构 | JSON/XML/HTML 类型正确；不是 200 的登录或错误页面 | invalid_feed / access_blocked |
| 正文结构 | 保留段落、标题、列表、代码、图片及有意义链接 | 无有效主体则 body_empty |
| 完整性 | 无付费截断、阅读剩余内容提示、漏页或明显摘要；符合该来源字段契约 | body_partial / unsupported |
| 安全与容量 | 大小、协议、跳转和内容清洗满足既有边界 | 拒收并记录稳定原因 |

长度和启发式质量分只提供诊断，不能作为“完整”的证明。真实短文可按已审核的结构化契约通过，长摘要/长登录页仍拒绝。不要用全局 subscribe 单词计数决定付费墙：结合页面结构和截断上下文，避免拒绝讨论订阅技术的正常文章。

API/Feed 的 HTML 片段直接进入片段转换器，不先套通用网页容器提取。已经是 Markdown 的 DEV 正文不再按 HTML 清洗。去除脚本、表单、跟踪像素和指定页脚，保留代码块、表格、图片说明、正文链接。

网页补抓先选择站点规则中的正文节点并验证，失败后才尝试通用选择器。不能把站点节点与整个 main 混在一起，再选“文字最多”的容器。缺标题、canonical 冲突或分页不完整时保守失败；不通过 AI 补写或生成摘要伪装为正文。[C07]

### 7.2 Worker lease snapshot

claim_fetch 返回不可变的内存快照：

~~~python
news_id
claimed_at
expected_url
expected_revision
~~~

领取条件包括：任务已安排且到期、来源允许、无有效 fetching lease、URL 和 revision 与读取的快照一致。已有正文且明确排队刷新的任务也可领取。

完成成功或失败时同时匹配：

~~~sql
WHERE id = :news_id
  AND url = :expected_url
  AND full_content_revision = :expected_revision
  AND full_content_fetch_status = 'fetching'
  AND last_full_content_attempt = :claimed_at
~~~

只有匹配一行才是有效提交。0 行表示租约或版本已改变，重新读取并报告 persistence_conflict；不能无条件再 save。保留当前时间租约 fencing，并增加 URL/revision fencing。移除 mark_success/mark_failed 没有 lease 也可直接保存的业务分支；Feed 走独立的显式 CAS 入口，不能伪造 Worker lease。[C08]

已有 News 的 API/HTML 异步请求必须在发出请求前绑定 expected_url/revision。不能响应回来后读取最新 revision 并冒充该响应属于新版本。纯 Feed 候选在入库读取版本后做 CAS，并执行下节的上游版本比较；它不能靠晚收到的时间覆盖已有正文。

### 7.3 候选与已有正文的更新矩阵

| 当前情况 | 处理 |
| --- | --- |
| 没有当前可用正文，候选完整且身份正确 | 原子写正文、state=complete、provenance，revision + 1 |
| 正文与已接受证据完全一致 | 幂等 no-op；不改译文，不刷新正文时间 |
| 内容 hash 相同，验证升级或可比较的上游版本更新 | 只更新必要证据及 state，revision + 1；保留译文 |
| 同一来源的可比较修改时间/版本明确更新，正文不同 | CAS 替换正文与证据，revision + 1 |
| 更旧版本，或相同上游版本却正文不同 | 保留当前正文，记录版本冲突 |
| 没有可比较版本，内容不同 | 自动采集不覆盖已有正文；由明确刷新任务重新获取并以其请求前快照提交 |
| 验证失败、429、超时、认证或站点阻断 | 保留当前正文、state、译文；只更新本次尝试信息 |

ETag、正文 hash、抓到的时间都不提供上游版本大小关系。相同正文 hash 也不能把更旧的 upstream_modified_at 写回 provenance。结构化来源允许的完整正文修订可以变短，不使用“变长才更新”的规则。

“没有可用正文”以 has_full_content=False 判定，包含 state=missing 但数据库为审计保留旧文本的情况。保留的隔离文本不能阻止合法候选重新建立正文。

no-op 只针对正文、稳定 provenance、revision、正文时间和译文。Worker 有效刷新得到同一正文时，仍必须带原 lease/URL/revision CAS 将 fetching 结束为 success，清除错误、next_attempt_at 和本轮失败计数；不能直接返回后留着 fetching。Feed 的纯幂等重放不擅自取消已有 queued/fetching 刷新意图。

provenance 至少保存 provider、source_key、source_item_id、target_url、body_field、source_version、source_modified_at、body_sha256、validator_version、accepted_at；只保存有明确用途的非敏感字段。

full_content_fetch_provider 表示最近尝试的 Provider；展示已接受正文来源时读取 provenance.provider，避免刷新在 Jina 失败后把旧正文误标为 Jina 提供。full_content_quality_score 保留为已接受正文的检查分数，失败候选分数只进事件诊断。

### 7.4 Feed 候选与正在执行的 Worker

滚动 Feed 可能移除已观察到的条目。旧 ETag 不能要求源站重发旧表示，因此不能把已有完整候选留在内存、等待 Worker lease 到期后再指望重新抓到。

本期采用同一 revision 的原子竞争，不增加候选队列表：

1. 候选先通过来源、身份、完整性及第 7.3 节版本规则；只有确实允许接受变更时才尝试提交。
2. Feed 以读取到的 URL/revision 做条件 UPDATE。即使当前有 fetching lease，也可以原子接受这次新正文/有效证据，revision + 1，任务状态转为 success，并清除 next_attempt_at、任务错误及本轮失败计数；正文 hash 相同则保留译文。不能只改变 revision 后留下 fetching。
3. 该写入自然使旧 Worker 的 lease/URL/revision 完成条件失效。旧 HTTP 正常结束并只释放它自己的 RequestBudget token；旧 Worker 记录 superseded，success/failed 均不得再写 News，也不计上游失败。进入下一 Provider 或可检查的重定向/后续实际请求前检查任务是否仍属于自己，避免继续无效外呼。
4. Worker 先提交导致 Feed CAS 失败时，重新读取并重新评估来源版本；不能只拿最新 revision 重试原 UPDATE。有限数据库重试仍未解决时返回 deferred，保留旧 checkpoint。
5. 完全相同正文和证据的 Feed no-op 不结束已有刷新任务；对旧版本/冲突候选按版本规则明确拒收并计数。

Feed 接受成功与对应元数据属于同一短事务；事务提交后才能结算 committed。不依赖未来 Feed 重放保全已经成功接收的候选。数据库提交前进程崩溃仍只能重拉上游；本方案不承诺恢复发布者已撤回且从未成功持久化的正文。

### 7.5 翻译与派生缓存

正文 hash 真正变化时，正文提交同一写入中清除 legacy News.full_content_zh 及时间，清除该正文生成的推荐问题缓存。内容相同、候选失败或刷新失败时均保留。

共享/私人全文翻译保留现有 source hash 查询和历史记录，不删除翻译表或用户数据。推荐问题生成结束时按开始时的 revision CAS 保存，旧摘要或旧正文的慢结果不能晚到覆盖新缓存。TTS 延续现有内容绑定缓存，不改本次 main 新增的传输修复。[C14][C17]

## 8 共享请求预算和异常策略

### 8.1 初始参数

下面是本项目的保守初始配置，不是发布者承诺的配额。已知官方配额和响应头始终优先。

| 参数 | 初值 |
| --- | --- |
| 全部署实际抓取 HTTP 并发 | 2，共享两个 global slot |
| 单主机 / 受控配额组并发 | 1 |
| 未明确规定的新闻站请求间隔 | 请求完成后至少 3 秒，再允许同范围下一请求 |
| DEV 详情间隔 | 至少 1 秒；服务端冷却和配额头优先 |
| HN API 间隔 | 至少 0.5 秒，并发 1；不把“当前未限流”当成无限请求许可 |
| arXiv legacy API / RSS | 本部署 group:arxiv 单连接且至少 3 秒；其他受控机器也必须计入同一官方总预算 |
| 正文安全 HTTP | 保留 15 秒总期限、2 MiB、最多 3 跳 |
| Scrapy 单次实际下载 | 15 秒硬上限；不能只有无限延长的空闲超时 |
| Feed 响应体 | 默认 8 MiB，压缩前后均有界；按来源审核更小上限，不全局放开正文上限 |
| 单篇正文任务 | 最多 60 秒或 5 个实际 HTTP 请求，先到者结束；预算等待过长则延期 |
| permit 租约 | 30 秒；必须大于所包裹单次下载硬期限，异常取消要能关闭连接 |
| News fetching lease | 复用统一 5 分钟 TTL；移除 Worker 自己另设的 10 分钟恢复规则 |
| 无 Retry-After 的 429 | 60 秒起，指数增加至 1 小时，加正向抖动 |
| 可重试网络失败 | 60 秒起有界指数退避，默认最多 5 次真实失败尝试 |

arXiv 官方要求所有受控机器合计满足速率限制，不能分散到多个独立数据库或不同机器规避。本方案的 SQLite 预算只能协调共享这一数据库的进程；扩容前需要统一配额存储或单独的来源执行者。[D05]

每个逻辑任务创建一个只在内存存在的 execution context，包含 monotonic 总截止时间、剩余物理请求数和执行取消/租约检查。所有 Provider、fallback、redirect、重试复用它，在每次实际发送前扣减请求数；嵌套调用不能重置。传输 timeout 取单次硬上限与逻辑剩余时间的较小值，耗尽后不再启动后续 Provider。

### 8.2 原子领取与释放

1. 在预算事务外幂等建立缺失 scope 行。
2. 生成一次请求专用的 lease_token。
3. 开始短事务，第一项操作用条件 UPDATE 尝试一个 global slot，再按稳定排序领取所有 host/配额组行。
4. 条件要求冷却到期、间隔到期、租约空闲或已过期；任意一步失败，整笔回滚，不持有半套 permit 等待。
5. 事务提交后发 HTTP；事务内不解析响应、不执行网络、不 sleep。
6. 得到响应后按 scope 原子延长 cooldown，释放时必须匹配自己的 token；下一允许时间至少是完成时间加间隔。
7. 失败/取消也 finally 释放；旧 token 不能释放或缩短新 token 的租约。

429 的冷却取当前值和新截止时间的最大值，不被另一条成功响应清空。对迟到的 429 可以保守延长 scope 冷却，但不能借此释放新请求的 token。

permit 时间必须来自成功领取时的新鲜数据库时间或等价的短事务实现，不能使用可能经历 SQLite 30 秒 busy 等待之前的时间。真正发 HTTP 前确认 token 仍拥有全部 scope，且剩余租期足以覆盖下载硬期限和余量；不足则重新领取或延期，绝不使用已经过期的 permit。测试要覆盖“锁等待跨过旧时间戳 TTL”。

SQLite 的 select_for_update 不提供所需行锁保证。使用条件写和短事务；BUSY/LOCKED 仅有界重试数据库操作，达到上限后 fail closed 并延期，不能“拿不到预算就直接请求”。要用真实文件 WAL、多进程验证，而非只用内存 SQLite。[D08]

### 8.3 接到实际传输边界

**Scrapy：** 新增薄 BudgetedHTTPDownloadHandler，HTTP 和 HTTPS 都接入；在调用内置 handler 前领取，在响应/异常返回给中间件前写冷却并释放。不复制 Scrapy 的 HTTP 实现。短等待用异步计时，ORM 用线程桥接；长冷却抛出 BudgetDeferred，该异常不属于 RetryMiddleware 默认重试类型。Feed/API Request 的 errback 持久化 next_poll_at 或 next_attempt_at 并记录 deferred；handler 不返回 FetchResult，也不伪造成功 Response。[D02]

不在普通 downloader middleware 的 process_request 中提前占有有限租约后任其在 Scrapy 内部下载队列里等待，否则可能在真正发送前过期。handler 本身还应给底层下载加可取消硬期限，验证 cancel 后 socket/Deferred 结束；不能只依赖一个不断刷新期限的空闲计时器。

retry、redirect、robots 都重新经过真实 handler 并计费。生产 RetryMiddleware 不立即重试 429/401/403；5xx/瞬时网络重试最多一次，仍走预算。有 Retry-After 的 503 也先持久延期。

**正文 Provider：** 在 safe_urlopen 的重定向循环内包住每一次实际 _fetch_one；每跳重新计算 scope、验证目标，保留原有 DNS/IP 固定及安全限制。预算等待不可悄悄延长 safe_http 原有总期限；拿不到可及时执行的预算就返回 deferred。

**第三方 Reader：** Jina 请求同时受实际 r.jina.ai/凭据范围与逻辑文章来源预算约束。原站 429 后本轮链路停止，不立即换 Jina 重试原站；只在策略允许且当前没有站点阻断/冷却时作为提取失败后的后备方式。

**所有入口：** 覆盖 Provider comparison、fetch_article_url 的裸 urllib、旧 CLI 和研究读取网页。研究 tools._tool_fetch_webpage 当前直接请求 Jina，必须复用现有 Jina 域策略与安全预算，返回 excerpt/scope；它不写 News.full_content。Wikipedia/DDG 搜索等不属于本次新闻正文传输改造范围。[C18]

Scrapy 发现阶段只使用审核的 Feed/API/列表主机与声明的跳转关系；不能把任意 Feed href 直接派给 Spider 下载。用户可控及外部文章正文 URL 交给保留地址固定的安全 HTTP 链路。生产不启用新的浏览器或未经预算接管的下载 handler。

### 8.4 HTTP 与 fallback 决策

| 结果 | 行为 | 自动重试 |
| --- | --- | --- |
| 200 且契约正确 | 解析/验证；持久成功后才记完成 | 不重复请求相同版本 |
| 304 | 只在已有可靠 checkpoint 时 unchanged | 到下个 poll |
| 429 | 解析 Retry-After；共享 scope 冷却；停止本轮链路 | 到期后有界重试 |
| 503 + Retry-After | 同样持久延期 | 到期后 |
| 401 | auth_required，停相关凭据/Provider | 修正配置后 |
| 403 / 挑战页 | access_blocked，不反复重试或切代理 | 修正来源策略后 |
| 404 / 410 真实文章不存在 | not_found；不根据标题换 URL | 默认不重试 |
| API 端点本身不支持 | 专用 Provider 明确区分 not_applicable 与文章不存在 | 可转批准的 HTML 路径 |
| 超时、连接重置、普通 5xx | 有界退避，不在各层叠加 retry | 按 attempt 上限 |
| 完整性/身份验证失败 | 保留旧正文；只在允许的其他提取方式上尝试 | 不无限重抓相同候选 |
| 预算暂不可用 | 持久 next_attempt_at | 不增加真实 HTTP 失败计数 |

先按来源定义解析配额响应头，再判断状态码。例如某 API 用 403 搭配明确的配额耗尽/重置头表达限流，应映射为 rate_limited；没有这种证据的 403 才按访问阻断处理。不能依赖“所有限流一定返回 429”的假设。

Retry-After 支持秒数和 HTTP 日期。未来有效日期即使很长也不能向下截短为更早重试；记录运维提示。缺失、非法或过去日期使用本地保守退避。恢复重启不能清掉冷却；force 不绕过冷却。[D09][D10]

Provider 内的直接 sleep + catch-all 重试改为统一决策。用“物理请求次数”和“逻辑任务尝试次数”分别监控；一篇文章的各种 Provider 不应各自耗尽 5 次再叠加一层 Worker 5 次。

## 9 Feed 增量与断点正确性

### 9.1 本轮 receipt

使用进程内 receipt，无需保存完整 Feed blob。每个 Feed 响应有 receipt_id、expected_revision、响应验证头、完整枚举计数和每个条目的终态。

条目终态只能是：

- committed：数据事务已经提交，包括幂等无变化，或元数据加补抓任务已经持久化。
- policy_skip：明确的年龄窗口排除、无合法身份等拒收，有稳定原因和计数。
- deferred：预算不足或有界 CAS 重试后仍无法闭合接收。
- failed：解析、数据库或未分类处理失败。

使用已提交的 IngestResult 结算条目；item_scraped 只证明 Pipeline 返回，不得覆盖已标记的 deferred。item_error、明确原因的 item_dropped 用于错误及拒收，不重复结算同一条目。未知异常不能伪装成 policy_skip。spider_closed 的异步回调必须等 Pipeline 完成，且仅在正常结束、枚举完成、没有 failed/deferred/未完成项时 CAS 更新 FeedState。

预算错误发生在拿到 Feed 响应之前时，不创建虚假条目 receipt；直接记录来源 deferred、持久 next_poll_at，并保留旧 checkpoint。

~~~text
收到响应
→ 完整枚举条目
→ 各条目提交或明确拒收
→ 确认本轮结算完整
→ WHERE FeedState.revision = expected_revision
→ 保存 ETag/Last-Modified 并 revision + 1
~~~

正文后续网络任务不需要在这一刻完成，但任务必须已入库。不能在收到 200 或 parse 返回时提前推进 ETag。[D01]

### 9.2 异常矩阵

| 故障点 | 下轮处理 |
| --- | --- |
| 收到 200 后解析失败 | 保留旧 checkpoint，按错误退避重拉 |
| 一部分 News 入库后进程退出 | 保留旧 checkpoint，重复条目幂等处理 |
| 条目全部入库后、checkpoint 写入前退出 | 重放不产生重复新闻或二次正文下载 |
| checkpoint CAS 失败 | 不覆盖其他运行的新进度，下轮读取当前状态 |
| 无有效本地 checkpoint 却收到 304 | 清验证状态，下次无条件获取；不报成功同步 |
| parser/source policy 或相关启用开关改变 | 有效 policy_version 签名变化，失效旧条件头，重新读取 Feed |
| 200 返回 HTML 登录页或超过大小上限 | invalid_feed / oversize；不推进 checkpoint |
| Feed 中确实没有条目 | 只有结构正确且正常解析的空 Feed 才算 valid_empty |

更新请求头只对应已提交的表示；304 无正文，不能作为未持久化条目的恢复来源。

### 9.3 窗口与轮询

初始配置：新闻 Feed 每 30 分钟、低频官方博客每 60 分钟检查一次，可在样本与响应缓存提示基础上调整。沿用现有 crawler 调度，FeedState.next_poll_at 在不需要网络时跳过。不能只把 Feed interval 设为 15 分钟，却保留 60 分钟的全局调度后宣称已达到 15 分钟时效。

首次发现默认 30 天窗口；完整解析 Feed 后再按明确规则排除过旧的新条目，记录 older_window。已有条目出现上游更新时不因原始发布时间早而跳过。绝不能先 entries[:N] 再提交整个 Feed 的 ETag。

自动正文补齐仅面向有可靠发布时间、最近 7 天且来源准入通过的文章。Worker 每批最多 10 个，分来源轮转后再按优先级处理；容量限制是延期，不是丢任务。显式用户阅读请求可处理更早文章，仍遵守来源、预算及冷却。

历史回填另用带 source、时间范围和 limit 的命令，不在 schema migration、容器启动或重试次数清零时隐式扫全库。

## 10 专用来源的实现细节

### 10.1 DEV

保留当前选题/标签查询范围，先不重做推荐策略。跨列表以数字 ID 去重；只有新条目、缺正文或详情版本明确需要更新时获取详情。对一次爬取最多前移 20 篇近期文章详情，余下符合准入的条目持久排队，不丢元数据。

Scrapy 已取得详情时，直接产生完整 body_candidate，不截断 body_markdown，也不把它塞进列表 content。详情请求失败的 errback 仍提交合法列表元数据和到期任务，避免文章随详情失败一起消失。

为 Worker 增加仅限 dev.to 的专用详情 Provider，使用官方按 ID/路径查询，验证响应 ID、url 和标题。不要再用 HTML 抓取代替已经可用的 API。新候选的 expected_revision 在该详情请求发出前读取；将官方 edited_at 映射为修改时间证据，与已接受正文版本比较。edited_at 可空，不能假定一定存在 updated_at，也不能用 last_seen_at/抓取时间伪造修改版本；published_at 仍是发布时间。用实际列表/详情 fixtures 确认映射。[D03]

### 10.2 HN 和 GitHub

HN self-post 仅使用官方 item.text，类型 discussion；外链 News 以实际目标文章 URL 标识、类型 article，HN item ID 和讨论页作为发现关系。不能用分数、评论数或 HN 讨论线程填外部文章正文。[D04]

GitHub 继续保留 Trending HTML 的发现语义和 README 阅读对象。现有 Raw README Provider 纳入预算及单任务请求上限，成功的 README 路径保存在 provenance 便于复用，避免每次从所有文件名/分支组合重试。官方 README REST API 可作为后续单独优化，经配额和身份契约测试后接入；本期不把它设为全站基础改造的阻塞项。[D11]

### 10.3 雷峰网和其他全文 Feed

将 Feed 正文直接带到 Pipeline，停止逐篇 HTML 请求。从逐篇默认 Provider 链移除会联网下载 Feed 的 LeiphoneFeedProvider；正文 Worker 不反向触发另一轮 crawler 任务。历史修复流程先显式完成一次来源级 Feed 同步，之后仍缺正文的记录才进入允许的 HTML 补抓，或明确不可恢复。

同一 Feed 响应解决多个条目，不能为每个 News 单独下载一份。首批八个结构化来源共享 Feed support；保留各自 source_policy 和少量确有必要的字段处理。

### 10.4 TechCrunch

新增域名限定、默认关闭的 TechCrunchWPProvider，只调用 techcrunch.com 的已验证 WordPress posts 端点。优先使用已知 post ID；用 slug 查询时只能请求精确 slug，并要求返回条目的 link 与规范目标 URL 精确匹配。不能把列表第一项当成任意待抓文章。

只请求必要字段：id、link、date_gmt、modified_gmt、title、content、excerpt；检查 content.protected、身份、HTML 清理、完整性与响应大小。日期使用明确的 GMT 字段，避免把站点本地时间误当 UTC。

404/405 的接口不支持与文章删除分别处理；429/401/403 按统一错误策略结束，不继续扫其他路径。未通过验证时保存摘要或等待允许的 HTML 补齐。[D07]

## 11 持久正文任务和接口兼容

### 11.1 状态机

~~~mermaid
stateDiagram-v2
    [*] --> pending
    pending --> queued: 合法入队
    queued --> fetching: 到期并取得租约
    fetching --> success: 验证及 CAS 成功
    fetching --> rate_limited: 429 冷却
    fetching --> network_error: 可重试异常
    rate_limited --> fetching: 到期再领取
    network_error --> fetching: 到期且次数未满
    fetching --> blocked: 认证或访问阻断
    fetching --> validation_failed: 无可接受正文
    success --> queued: 明确刷新或上游新版本
~~~

pending 表示没有安排任务。queued/可重试失败必须有 next_attempt_at；终止失败、unsupported、blocked 的 next_attempt_at 为 NULL。只有任务状态变为 fetching 才拥有租约；排队时间不能写入 last_full_content_attempt 伪装为执行时间。

本文状态图只表示任务；正文 state 仍独立。例如 full_content_state=complete 与 full_content_fetch_status=rate_limited 可以同时成立，含义是已有正文可读、刷新正在等待。

过期任务恢复统一到 full_content_status 服务。没有时间戳的 fetching 也应被识别为不完整旧状态，经过条件更新恢复；不保留按命令不同而不同的 5/10 分钟 TTL。

预算延期、SIGTERM、可恢复取消和过期 lease 恢复必须保留任务意图：回到 queued，保留优先级，next_attempt_at 不早于 now 与当前冷却。不能沿用旧 release_fetch_claim 回到 pending 的行为而丢任务。它们不增加真实失败计数；只有明确撤销任务意图才可设 pending。

retry_count 计算当前逻辑获取周期的真实失败次数。新建获取周期或成功后的新刷新从 0 开始；有效成功清为 0。重复 POST、预算延期、进程恢复不重置计数。5 次用尽后终止自动重试；若是适配器已修复或允许的显式重试，可开始新周期，但不得越过仍有效的冷却/阻断。

### 11.2 Worker

复用 auto_fetch_full_content，新增独立进程 flock 和定期健康心跳。锁、心跳放在共享 logs-data 的固定路径，不能使用容器各自 /tmp；文件原子替换，健康输出不包含密钥。

Worker 只执行已安排的任务，不把所有历史 pending 自动当队列。默认每批最多 10 个，优先级有界、按来源轮转，避免一个大 Feed 或不断出现的新文章使其他来源永远等不到执行。初始实现允许单正文任务顺序执行，两个全局 HTTP slot 仍可同时容纳 crawler 与正文流量，无需为了“并发 2”强行增加线程池。

禁用、空队列、429 冷却期间仍每 10 秒更新存活心跳。健康检查关注进程/循环存活与数据库连接；来源数小时没新文章不等于 Worker 不健康。

SIGTERM 停止领取，当前请求受硬期限约束，进入下一 Provider 前检查停止标记；释放自己的 permit/lease，45 秒停止宽限应能覆盖剩余单次请求和数据库提交。不要收到 SIGTERM 后仍跑完剩余 60 秒 Provider 链。[C10][C11]

### 11.3 配置开关

通过现有 runtime_config/settings 机制解析，不再新增另一套配置加载器：

| 配置 | 默认 | 语义 |
| --- | --- | --- |
| STRUCTURED_BODY_INGEST_ENABLED | false | 启用通过验证的 API/Feed 正文写入 |
| STRUCTURED_BODY_SOURCE_KEYS | 空集合 | 本次允许结构化正文写入的来源白名单，空集合不表示全部 |
| FULL_CONTENT_WORKER_ENABLED | false | 正文 Worker 可执行及 API 可接收新手动任务 |
| FULL_CONTENT_AUTO_ENQUEUE_ENABLED | false | 允许近期新文章自动排队，与手动阅读请求分开 |
| FULL_CONTENT_AUTO_SOURCE_KEYS | 空集合 | 自动补齐来源白名单，空集合不表示全部 |
| TECHCRUNCH_WP_ENABLED | false | TC 专用 CMS Provider 单独启用 |
| FULL_CONTENT_WORKER_LOCK / HEARTBEAT | 共享日志卷中的固定路径 | 进程互斥与健康检查 |

生产共享预算不提供给用户的 bypass 开关。测试使用独立测试数据库、时钟与传输替身，不修改真实配额状态。

app、crawler、正文 Worker 需要读取一致的相关开关。新 Worker 可以常驻但 disabled；不得在 ApiConfig.ready 或 web 请求中再启动后台线程。

来源白名单取已审核 source_policy 的子集，解析时拒绝未知 source_key；可只启用 devto、leiphone 做首批检查。结构化写入关闭/未准入时不额外前移 DEV 详情请求。手动阅读补抓仍按目标发布者及来源策略判断，不由自动补齐白名单扩大权限。

关闭结构化正文/自动入队期间，合法元数据仍可 committed，关闭的动作记录为明确 policy_skip，并允许提交与当前有效策略签名绑定的 Feed checkpoint。off→on 或来源准入变化时签名失效，下一次无条件重读 Feed；不能沿用旧 ETag 一直 304。

自动入队从关闭到开启，还需执行一次有界的近期补排：仅最近 7 天、日期可靠、来源合格、没有可用正文且尚未有任务的记录，按 source/limit 分批幂等入队。可以复用 fetch_full_content 增加相应筛选，不新增常驻历史扫描器。容量到达时保留后续批次进度，不假定未来 Feed 会再次出现这些条目。

### 11.4 fetch-full API

继续使用现有 POST /api/news/{id}/fetch-full/ 和现有鉴权/CSRF。

| 条件 | HTTP | 响应 |
| --- | --- | --- |
| 已有正文，非 force | 200 | 当前 News detail，即使 Worker 禁用也可返回缓存 |
| URL/身份无效或来源明确不支持 | 422 | 稳定 error_code 与可理解原因 |
| Worker 禁用或心跳过期 | 503 | full_content_worker_unavailable；当前内容/状态仍可读，不接受无执行者的新任务 |
| 新排队、已排队、正在执行或处于持久冷却 | 202 | 当前 News detail 加队列状态和 next_attempt_at |
| 原有鉴权/CSRF 不满足 | 现有 401/403 语义 | 不扩大权限 |

202 仍返回现有 News detail schema，增加 has_full_content、content_kind、full_content_state、revision、next_attempt_at、error_code；不改成只有 job_id 的不兼容响应。用 Location 指向可轮询的详情 GET，可附合理 Retry-After。

force=true 表示刷新意图和较高优先级；不能取消别人的有效 lease、清除站点冷却、绕过认证或准入。重复 POST 复用同一任务，不增加多个执行实体。

### 11.5 所有消费者的迁移清单

| 现有路径 | 改动 |
| --- | --- |
| views.py::NewsFetchFullView.post | 从同步网络抓取改为排队/复用与 200/202/503 |
| views.py::ensure_full_content | 将 enqueue/read 能力移到服务层，移除 service import views 的正文获取依赖 |
| views.py 聊天入口 | 不在 HTTP 请求里抓外站；只有摘要时 context_scope=summary，提示词及 SSE 元数据保持一致 |
| views.py 推荐问题 | 缺正文时返回明确的摘要/现有 fallback 问题；正文完成后按 revision 更新缓存 |
| research/tools.py::_tool_fetch_article | 读取已有正文或入队；最多短时等待数据库，并检查取消；超时返回 scope/state/next_attempt_at |
| research/tools.py::_tool_fetch_webpage | 受控 Reader 诊断获取，复用 Jina 策略、safe_http、预算；截取的工具上下文标为 excerpt，不存 full_content |
| research/agent_loop.py 及前端研究时间线 | 排队或摘要结果不能显示“已获取全文” |
| 公共/BYOK/订阅翻译 | 无正文时保留已有 SSE 错误协议，增加 full_content_not_ready 信息；不自己再创建抓取链 |
| tts_service.py | 按正文可用性读取；刷新失败继续使用已有正文和内容绑定缓存 |
| views.py 的两处全文筛选、research/tools.py 搜索 | 共用数据库可用谓词；不再以 status=success 代替有正文 |
| serializers / 前端 types | 新增状态字段，列表保持轻量，不把全文正文/全部 provenance 加进列表 |
| NewsAdmin | 正文、状态、revision 及证据字段只读；URL 纠正走审计服务而非表单直接写穿 |
| full_content_stats / article_fetch_monitor | 尝试结果、已保存正文、legacy 分开统计 |

隔离正文的内部检查也必须收口：views.pick_chat_context；serializer 的译文读取及 available/active/source/scope；shared_translations 的读取、task_is_running 与 publish_translation；chatgpt_subscription_jobs 中领取、当前正文判断和发布前检查。它们必须同时满足正文可用性与已有 source hash 条件，不能因隔离操作保留了相同字符串/hash，就允许旧翻译任务继续发布为当前文章译文。

普通详情在 state=missing 时输出空 full_content/full_content_zh，当前译文 available/active=false；旧文本与历史译文保留在数据库供管理审计，不向普通读者暴露为当前原文。这一规则也覆盖旧前端只判断字符串非空的兼容情况。新增通用 get_readable_full_content/has_full_content helper，并与数据库谓词保持一致。

当前调用点可在上述文件和测试中核对。[C09][C17][C18][C19]

前端至少覆盖：newsWorkflowApi.ts、types/news.ts、useFullArticle.ts、FullContentFetchStatus.jsx、FullContentSection.tsx、NewsDetail.tsx、NewsCard.tsx、LocalSearch.tsx，以及研究状态展示。[C21]

轮询 GET 保持只读。queued/rate_limited 不自动反复 POST；遵守 next_attempt_at，轮询退避并设等待上限。用户关闭详情页只停止当前页面轮询，不能取消所有用户共享的任务。

### 11.6 旧命令收口

| 命令 / 入口 | 最终行为 |
| --- | --- |
| fetch_full_content | enqueue-only；保留 source/status/limit/force/dry-run 等筛选，输出 queued/reused/deferred/rejected |
| fetch_full_content --wait，可新增 | 只轮询数据库，不再独立请求 Provider |
| backfill_full_content_scrapy | 生产明确报 CommandError 并提示使用统一命令；不保留第二个正文写入器 |
| fetch_article_url | 只读 JSON 诊断；裸 urllib 改安全预算传输，不写 News |
| Provider comparison API/CLI | 继续比较诊断，不写 News；每个真实请求仍需预算 |
| auto_fetch_full_content | 唯一常规正文网络任务消费者 |

命令 force 的默认筛选不能继续排除已有 success，导致“刷新”实际上匹配不到数据；但 force 也不能改变来源策略。旧测试应验证新语义，不机械保留同步抓取断言。[C18][C20]

## 12 Codex 分阶段实施任务

每项完成后跑相关测试、形成独立提交，再进入下一项。以下是逻辑任务边界，不要求为了名称机械创建 12 个 PR；同一兼容发布所必需的前后端和 Worker 改动可以组成一组提交。

### T00 固定实施基线

**范围：** 最新 main、本文、现有 CI、相关旧文档。

记录实际 SHA、是否已有相同实现、Django/Scrapy/feedparser 版本。检查工作区改动和 AGENTS.md。检查现有 migrations，使用实际下一个编号，不在文档中猜编号。记录待改路径；无关 TTS/UI 改动保持。

**验收：** 有明确基线和改动映射；旧文档不会使 Codex 重建已有全文字段或重新启用 Jina-first。

### T01 阻断伪来源并修复 Pipeline 定向更新

**范围：** reuters_spider.py、jiqizhixin_spider.py、sanliu_kr_spider.py、leiphone_spider.py、pipelines.py、crawler_control 的来源同步。

删除标题拼 URL 路径；对异常入口返回明确 disabled/unsupported，不生成假 News；修正新雷峰网条目名称；旧 News 更新只操作允许字段。已有目标禁用状态保持，运行代码本身也阻断伪入口，不能只依赖 CrawlerTarget.enabled。

**不包含：** 删除历史来源或文章、批量合并、自动开启调度。

**验收：** Reuters 搜索 URL、机器之心猜测 slug、36kr HTML Feed 均不能生成有效文章；同标题不同 URL 不误合并；旧正文/译文不被 Pipeline 覆盖。

### T02 模型与迁移

**范围：** models.py、migrations、schema/serializer 基础测试。

新增第 5 节三个表和七字段；旧非空正文标记 legacy、revision=1，空正文 missing、revision=0；不宣称 legacy 已验证。保持旧正文、译文及用户关系。新增状态 choices、任务索引。

**验收：** 空库/已有数据两种迁移通过；迁移不发外网、不改调度；success + 空白正文不再被视为有全文。

### T03 统一身份与正文 CAS

**范围：** news_ingestion.py、full_content_status.py、article_fetcher/types.py、validators.py、extractors.py、Pipeline、NewsAdmin、全文可用性 helper。

实现真实身份映射、候选校验、request 前版本快照、带 URL/revision/lease 的成功及失败写入。清理无租约写穿和整行保存；处理旧记录缺少独立摘要的问题。

**验收：** 同 URL/来源 ID 并发幂等；旧 Worker、旧候选、旧推荐问题均不能覆盖新正文；无效候选不删旧文；正文 hash 不变保留译文。

### T04 共享预算及类型化错误

**范围：** request_budget.py、safe_http.py、providers/core/types、Scrapy download_handlers/settings、fetch_article_url、comparison、研究 Reader 边界。

实现条件领取、全局与域/组预算、Retry-After、取消和真实请求计费；关闭多层即时重试；修复 create_crawler 之后的最终礼貌配置约束，避免 Spider.custom_settings 覆盖。

**验收：** 多进程同域在途最多 1、全局最多 2；冷却重启保留；redirect/robots/retry/诊断均计费；reactor 不因等待阻塞；429 后本轮不继续原站或 Jina；保留安全 HTTP 防护。

**依赖：** T02。线上打开新增来源/自动抓取前必须完成这一项。

### T05 Feed 支持与提交后 checkpoint

**范围：** feed_support.py、feed_state.py、feedparser 依赖、Pipeline receipts、相关 Spider、公用日期解析。

实现条件请求、完整枚举、事务后 receipt、policy_version 重放、有效空 Feed 与错误 HTML 区分。新增来源契约不采用通用“description 即正文”判断。

**验收：** 部分入库失败、取消、进程退出不推进 ETag；重放幂等；304 不丢条目；源码没有在枚举前截断后仍提交整个响应的路径。

### T06 首批 API 与正文 Feed

**范围：** DEV、HN、雷峰网、WebKit、Smashing、V8、Mozilla；随后 Svelte、Angular；专用 DEV Provider。

按照第 10 节改造。Feed 不再逐篇发 HTML；DEV 保留完整正文且跨标签去重；HN 自帖/外链明确类型。逐篇默认链移除联网 LeiphoneFeedProvider。

**验收：** 已得到的可信完整正文首次接收即可写 full_content；下一轮相同版本不再抓文章页；每个来源通过契约 fixtures；正文候选失败时仍保存真实元数据。

### T07 TC 与剩余来源分级迁移

**范围：** TechCrunchWPProvider 及独立开关；其余 Feed 接入公用解析；现有 HTML 来源仅做必要准入/日期修复。

TC 使用精确身份对应的 CMS 响应，不扫描任意 wp-json。其余来源按矩阵保持摘要/特殊类型或等待逐站验证，不以“迁移完成率”强行启用。

**验收：** TC 错文章/受保护/429 响应不写正文；MIT/Ars 截断样本不升级；arXiv/Product Hunt 不写假全文；31 来源均有明确策略与错误结果。

### T08 常驻 Worker 与队列命令

**范围：** auto_fetch_full_content、full_content_status、healthcheck、runtime_config/settings、旧 CLI。

实现 enabled/auto-enqueue 分离、共享锁/心跳、due query、来源轮转、5 分钟租约恢复、SIGTERM。旧命令转排队或只读诊断。

**验收：** disabled/空队列/长冷却仍健康；kill 后可恢复；没有历史全库自动扫描；所有普通正文任务只由该 Worker 执行。

### T09 API 前端与内容消费者

**范围：** 第 11.5 节所有调用点、frontend 对应测试。

实现 200/202/503、queued/cooling 轮询、context_scope、可用性筛选；移除聊天与普通研究文章工具在 Web 请求内的同步外站抓取。研究网页诊断保持受预算与策略控制的单独语义。

**验收：** 202 被正确附着；Worker 不可用不制造无限等待；旧正文刷新失败仍可阅读、筛选和使用；摘要不会显示成已获取全文；关闭页面不取消共享任务。

**发布约束：** T08、T09、T10 必须组成兼容的发布集合。不能先发布 enqueue-only API 而没有可配置运行的 Worker。

### T10 Compose 与完整发布生命周期

**范围：** compose.prod.yaml、按需 compose.yaml、env example、runtime_config、部署脚本和已有 release tests。

新增名为 full-content 的服务，运行 auto_fetch_full_content，复用当前不可变镜像、db-data 与 logs-data、非 root 用户、init、健康检查和 45 秒停止宽限。

同步修改 deploy/rollback/restore 的服务识别与校验、失败后的停机，以及现有 mocked 与 volume/local-domain 测试。备份继续复用现有 SQLite online backup，验证其与新写入者共存和快照一致性，不再新写备份系统。

**验收：** 迁移前停止所有本项目写入者；遗漏新 Worker 时门禁能发现；新 Worker 不健康不切静态版本；失败时能停止它；回退到无此服务的旧版本不会启动不存在的命令；不操作其他 Compose 项目。

### T11 数据修复及有限历史回填

**范围：** 新增 repair_news_sources 命令、fetch_full_content 的范围筛选、审计输出及本文操作说明。

默认 dry-run，逐条输出 News.id、旧值、新值、证据和冲突；按第 13 节规则应用可证明修复。对剩余缺正文先来源级同步，再限量排队。

**验收：** News.id、收藏、聊天、翻译历史保持；Source/URL 冲突不自动合并；重跑幂等；反向修复只在当前值仍等于此次写入值时执行。

### T12 验收与运营指标

**范围：** 现有 ArticleFetchEvent、full_content_stats、CrawlRun.stats、必要的管理端展示和验收记录。

分别记录候选验证、数据库提交、HTTP 响应和逻辑任务结果。统一 crawler 的机器可读 outcome；完成下节所有关键故障测试及 CI 现有门禁，填入真实结果。

**验收：** 不把退出码 0、HTTP 200、validated result、无新增条目四件事混成同一种成功；能定位来源、错误码、冷却、积压和持久化冲突。

## 13 迁移 上线与回滚

### 13.1 数据迁移

结构迁移只新增字段、表及初始化状态，不执行外网、不重抓正文、不开启 scheduler。不全量推断来源 GUID；新抓取按精确 URL 与旧 News 接上，再补身份映射。

旧非空正文标记 legacy，不自动断言已满足新验证规则。旧空白正文标记 missing，即使历史 status=success 也不算已有全文。已接受 body 只有从新验证写入器产生时才是 complete。

历史来源修复遵守以下条件：

- 雷峰网旧 Source URL 确实为 leiphone、所有相关归属一致且目标“雷峰网”不存在时，可以原位改名，保留 Source.id。
- 目标来源已存在或旧来源混有其他文章时，只按已验证 News.id 定向改 FK；不删除旧 Source，因为 News.source 是 CASCADE。
- Reuters/机器之心没有真实文章 URL 证据的记录保留摘要，标为 invalid_identity/unsupported。原文跳转与补抓入口显示“链接待核验”，不得再次按标题猜链接。
- 已有目标 URL 被另一 News 占用时输出冲突，保留两条及用户关系，不自动删行或合并。
- 修正来源/URL 不顺便重写发布时间、正文文本、译文或用户关系。
- URL 确认只是同一文章的等价链接时，更新身份证据与 revision，保持内容。若无法证明已有正文属于纠正后的文章，保留旧文本但将正文 state 降为 missing，停止把它作为可用原文；记录旧状态并排队验证新 URL。所有消费者必须使用统一可用性判断，不能只看字符串非空。
- URL 修正以 CAS 增加 revision，并使旧 fetching lease 失效，旧执行者成功或失败均不得再落库。该受审计身份修正不同于普通 force 刷新。
- 应用修复及反向恢复都比较预期旧值，不能撤销其他人或后续抓取的新改动。

默认 dry-run；apply 输入应是带明确证据与预期旧值的映射，不接受“所有 Reuters 按标题生成 URL”一类批处理。[C04][C23]

### 13.2 分阶段开启

1. 使用现有备份流程生成并验证迁移前 SQLite 快照、manifest，记录部署 SHA、迁移集合、CrawlerSettings 与所有 target.enabled。
2. 停止现有写入进程，部署包含 T08/T09/T10 的兼容集合，执行迁移；新增开关保持 false。
3. 确认 app、crawler、full-content 使用同一个数据库目录卷和配置，Worker disabled 状态健康。
4. 在隔离环境完成契约及故障测试；生产先小范围打开结构化正文写入，选 2–3 个已通过校验的来源做人工抽样。
5. 打开正文 Worker，先保持自动补齐关闭，用少量明确 ID 验证排队、冷却和正文读取。
6. 打开最近 7 天的自动补齐，执行有来源和 limit 限制的近期 missing 补排，并验证策略签名变化后的 Feed 重读；按已通过来源扩大，TC 单独启用。
7. 最后执行带范围和 limit 的历史修复/回填；持续观察 7 天，不把等待 7 天作为写代码和离线验收的前置阻塞。

CrawlerSettings 已有数据库行是调度开关的权威值。get_or_create 的环境默认值不会覆盖已有 scheduler_enabled；CRAWLER_SCHEDULER_ENABLED=0 不能保证线上已停止调度。迁移期间确实停止 Worker，恢复时保持记录的开关状态，不静默开启。[C13]

同时核对数据库的 interval_seconds。要达到 30 分钟检查周期，必须通过现有配置路径调整实际周期并计入运行耗时，不能只改环境默认值；调整周期不隐式改变 scheduler_enabled。

### 13.3 进程与版本兼容

当前 deploy/rollback 脚本显式处理 crawler、indexer、app，并会检查数据库卷还有没有其他容器使用。新增服务必须进入本项目的服务识别、停止、健康和失败清理流程。[C12]

对目标版本不含 full-content 服务的情况按目标版本能力处理，不能机械把新服务名添加到所有旧版本启动命令。既有停止所有 DB 写入者、卷归属、静态版本切换等检查继续生效。

### 13.4 三种回退方式

| 情况 | 正确处理 |
| --- | --- |
| 新来源/自动补齐出现问题 | 关闭对应功能或暂停 Worker，保留 schema、有效正文与冷却，优先向前修复 |
| 代码回退，数据库迁移集合与目标 manifest 完全相同 | 使用现有 rollback 流程 |
| 新 migration 已执行，需要恢复旧 schema | 停止全部写入者，先保全当前快照，再按现有 restore 流程恢复迁移前快照；明确处理恢复点后新增的用户数据 |

现有 rollback 要求迁移集合精确匹配，不能因为 migration 是 additive 就承诺旧镜像可直接回滚；--compatible 不应绕过现有门禁。[C24]

恢复旧快照不是无损回滚，会涉及快照之后的收藏、聊天、翻译等数据；使用当前 manifest 和快照流程处理。不得用直接复制主 db.sqlite3、删除 WAL/SHM 或 down -v 代替恢复。

## 14 测试与验收

### 14.1 必须通过的实质场景

| 组 | 必须验证 |
| --- | --- |
| 身份 | 标题相同不同文章不合并；同域另一路径拒收；真实别名通过；多来源同 URL 保留发现关系；唯一约束竞争幂等 |
| 正文 | 真实短文通过；长摘要/截断页/挑战页拒绝；Markdown、代码、图片、表格结构保留；media:content 不当正文 |
| 上游版本 | 更新后正文变短可接受；旧版本和同版本异内容不覆盖；opaque ETag 不用作大小顺序 |
| 写入竞态 | Pipeline 不覆盖其他字段；Feed 与 Worker 任一先提交均正确；旧 lease/旧 URL/旧 revision 的成功和失败均不写回；同正文新证据也 fence 旧写入 |
| 派生内容 | body hash 不变保留译文；改变后清 legacy 译文；私人/共享历史保留；旧推荐问题不能覆盖 |
| 请求预算 | 同域最大 1、全局最大 2；所有 scope 一起取得或全部回滚；重试/跳转/robots/Reader/诊断每次计费 |
| 429 | 秒数和日期 Retry-After；过去/非法值；重启保留；force 不绕过；429 不立即切 Jina |
| 连接生命周期 | 下载硬期限、取消关闭连接、异常 finally、租约过期接管、旧 token 不释放新租约、DB 锁等待后不用过期 permit |
| Feed 进度 | Pipeline 未完成/失败/取消不提交 ETag；重放幂等；首次 304；policy_version 失效；真实空 Feed |
| Worker | 禁用/空队列/冷却保持心跳；SIGTERM 停领取并保留任务；同正文刷新正常完成；kill 后恢复；只处理明确任务；无全库隐式回填 |
| API 与 UI | 200/202/503；queued/cooling 轮询；Worker 不可用；保留旧正文；关闭页面不取消共享任务 |
| 聊天与研究 | 只有摘要时 scope 正确；研究取消退出等待；截取工具内容不称完整正文 |
| 运维 | 新服务发布、迁移前停止、失败停机、目标旧版本无新服务、跨 schema 回退门禁 |
| 历史修复 | Source 和 URL 冲突；保留 News.id/用户关系；只撤销仍匹配的修复；隔离旧正文及共享/私人译文不再展示，运行中旧翻译不能发布；合法新候选可恢复可用 |
| 启用变化 | disabled 时 checkpoint 合法；off→on 失效旧 ETag；近期合格 missing 可有界补排；重复操作幂等 |

至少一组并发/恢复测试使用独立进程、临时文件 SQLite，并断言 journal_mode=wal。现有 tests/backend/conftest.py 会将数据库改为内存数据库，普通 pytest 单元测试不能证明跨进程预算有效。SQLite 测试只连合成测试库，不读取仓库随带数据库或生产路径。

故障用本地受控 HTTP server 或传输替身模拟，不通过真实网站连续请求人为制造 429。不要断言随机抖动的固定值，应断言不会早于 Retry-After、范围有界和状态可恢复。

### 14.2 复用的测试入口

优先扩展这些已有测试，而不是创建重复验证框架：

- tests/crawler/test_crawl_only_mode.py、test_bbc_spider_selectors.py
- backend/api/tests/test_full_content_status_service.py、test_full_content_status_model.py
- backend/api/tests/test_fetch_full.py、test_fetch_full_command.py、test_backfill_scrapy_command.py
- backend/api/tests/test_article_fetcher.py、test_article_fetcher_quality_report.py、test_article_fetcher_security.py、test_safe_http.py
- backend/api/tests/test_article_fetch_monitor.py、test_suggested_questions.py、test_chat_context.py
- backend/api/tests/test_shared_translations.py、test_research_tool_cancellation.py
- frontend/tests/hooks/useFullArticle.test.jsx、useTranslation.test.jsx
- frontend/tests/components/news-detail/FullContentFetchStatus.test.jsx
- scripts/deploy/tests 现有发布、卷及本地域名测试

必要新增：test_news_ingestion、test_feed_state、test_feed_receipts、test_request_budget、test_budgeted_download_handler、Worker 生命周期与队列契约。命名按仓库实际风格落地；新增测试必须验证行为或故障边界，不仅重复字段赋值。

### 14.3 执行命令

以下命令在仓库根执行，使用仓库 CI 的 Python 3.12 虚拟环境。依赖安装沿用 .github/workflows/ci.yml，不单独猜测 Torch/浏览器版本。[C22]

~~~bash
NEWSHUB_TEST_DIR="$(mktemp -d)"
export DJANGO_ENV=development
export DJANGO_DB_PATH="$NEWSHUB_TEST_DIR/schema-check.sqlite3"

PYTHONPATH=backend:crawler RUN_MAIN=true backend/venv/bin/python -m pytest --collect-only -q tests/ backend/api/tests/ scripts/deploy/tests/

PYTHONPATH=backend:crawler RUN_MAIN=true backend/venv/bin/python -m pytest -q tests/ backend/api/tests/ scripts/deploy/tests/

PYTHONPATH=backend:crawler RUN_MAIN=true backend/venv/bin/python backend/manage.py makemigrations --check --dry-run

npm --prefix frontend ci
npm --prefix frontend run typecheck
npm --prefix frontend run lint
npm --prefix frontend run test:run
npm --prefix frontend run build

bash -n scripts/deploy/deploy.sh scripts/deploy/rollback.sh scripts/deploy/backup.sh scripts/deploy/restore.sh scripts/deploy/tests/test_release_scripts.sh
bash scripts/deploy/tests/test_release_scripts.sh
~~~

执行迁移/check 命令时通过 DJANGO_DB_PATH 指向单独的临时文件数据库，并使用合成环境配置；不得默认操作克隆中随带的数据库。先按任务跑相关测试子集，兼容集合完成后再跑 CI 现有完整门禁；已有脚本要求的其他 release/local-domain gates 不删除或绕过。

根 scripts/run_tests.sh 没有覆盖全部 backend/api/tests，不能单凭该脚本宣称通过完整回归。[C22]

本文件是设计与执行合同，未声称业务实现或上述测试已经完成。Codex 实施后填写实际通过/失败结果和原因，不能照抄历史文档里的通过数量。

### 14.4 来源正文抽样

每个准备启用的正文来源抽样 10 篇可用代表条目，尽量覆盖短文、长文、图片、代码、旧文章和近期更新；来源实际样本不足时使用全部可获得样本并记录数量。确认标题/身份、正文首尾、段落结构、截断、canonical 和界面显示。

将必要结构做成合成/最小化 fixtures，不提交整篇受版权保护的媒体文章作为无关测试材料。离线故障 fixtures 必须包含“长但不完整”“200 错误页”“摘要即 legacy content”三类。

这轮抽样的启用门槛是没有发现错文章或已知截断被标为 complete；发现一个即修对应契约并重跑相关样本。它是样本验收，不是对全部新闻宣称 100% 完整性。

## 15 监控与交付标准

### 15.1 复用既有数据

CrawlRun.stats 增加：

~~~text
outcome
entries_seen
entries_committed
entries_changed
body_candidates_committed
policy_skips_by_reason
parse_failures
persistence_failures
checkpoint_committed
next_attempt_at
~~~

outcome 使用 updated、unchanged、valid_empty、deferred、rate_limited、blocked、parse_failed、partial。前三类可成功完成；部分持久化失败、全站 429 或收到错误 HTML 不能仅凭进程退出 0 显示抓取成功。保持机器可读 JSON 汇总与现有人工日志兼容。

ArticleFetchEvent 继续记录 Provider、站点、耗时与诊断，补充 HTTP 状态、退避、物理请求数和持久化结果。验证通过但 CAS 未提交分别记录 validated 与 persistence_conflict，不计算为“正文已保存”。不要把完整响应、正文或敏感 URL 写入错误日志。

### 15.2 指标口径

| 指标 | 口径 |
| --- | --- |
| 新闻正文覆盖率 | 符合抓取准入的 article 中 full_content_state=complete 的占比 |
| legacy 正文数 | 历史可读但未按新规则复核的数量，单独展示 |
| 单篇请求成本 | 实际 HTTP 请求数 / 成功提交的新正文数，观察重复获取是否下降 |
| 限流 | 429 次数、被预算主动延期次数、冷却剩余时间，三者分开 |
| 时效 | 发布时间可信时从发布到发现、从任务入队到正文可用的延迟 |
| 稳定性 | 最近成功 Feed 提交、解析错误、队列最老任务、stale lease 恢复、Worker 心跳 |
| 正确性 | 抽样中错文章、摘要冒充全文、截断全文、来源归属错误的数量 |

没有全文的数量不能直接解释为抓取失败率；摘要型来源、未排队、legacy、授权不满足和真实失败必须分开。成功率的分母只包含实际发出的可评估尝试。

### 15.3 开发完成定义

1. 已有可信 API/Feed 正文不再丢失或二次下载；31 个来源都有明确策略。
2. 伪造 URL 路径消失，元数据更新不覆盖并发正文/译文。
3. 429 与所有正文入口共享持久预算，重启/force/Reader 均不绕过。
4. 只把通过身份及完整性验证的内容写为 complete。
5. Feed 进度与数据库提交一致，故障重放不丢新闻。
6. Worker、API、前端、研究和旧命令的契约闭合。
7. 新进程进入发布、停机、恢复、健康与旧版本兼容验证。
8. 实施记录包含实际基线、提交、迁移、测试结果、开启步骤和剩余来源限制。

## 16 可直接交给 Codex 的执行指令

将本文件放入仓库建议路径后，可使用以下指令：

~~~text
请基于当前最新 main，实施 docs/plans/2026-10-13-news-ingestion-design-codex.md。

先读取仓库当前指令、本文和所涉及的现有实现，再 fetch 最新 main 并记录实际 SHA。
本文基线是 7990f7c3733ed90b67d3f69a51395f0385eb22fa；不要为对齐旧 SHA 回退仓库。
如果 main 已有部分实现，请核对合同后复用，只补缺口。

本任务需要实际修改代码、迁移、必要测试与部署配置，不要只重述方案。
按 T00–T12 的依赖顺序推进，每项完成相关验证并形成清晰提交。
可以并行处理没有共享修改冲突的来源适配与独立测试，公共模型/状态/预算契约先统一。

必须保持：
- 真实 URL/来源 ID；不按标题猜文章 URL。
- 摘要与完整正文分离，类型化候选必须验证。
- 所有正文写入经 URL/revision/lease CAS；已有有效正文在刷新失败后继续可读。
- Feed 条目持久化完成后才提交 ETag/checkpoint。
- 所有真实新闻获取 HTTP 共享预算，429/Retry-After 不被 force、retry、Jina 或 CLI 绕过。
- 当前 SQLite 路径/WAL、翻译 source hash、鉴权/CSRF、既有发布门禁保持。
- 新 Worker、enqueue API、前端和发布脚本作为兼容集合交付。

本次开发不自动部署生产，不修改真实 scheduler/来源开关，不直接修复线上数据或触发全库回填。
准备具体的 dry-run、上线与恢复说明；对可在本地解决的实现问题持续推进。
遇到来源不支持时按本文降级/隔离，不猜 API、不生成假全文。

测试复用当前 CI，并增加真实文件 SQLite WAL 的多进程预算/租约场景。
禁止用真实站点请求风暴制造 429，禁止把未经运行的测试写成通过。
最终报告实际改动、提交、测试、迁移、启用顺序、剩余限制，并逐项核对开发完成定义。
~~~

## 参考代码与官方资料

代码链接固定到本方案基线，便于 Codex 与届时 main 对比；外部协议和接口以发布者当前文档及真实响应为准。

[C00]: https://github.com/CoderLambert/news-aggregator/tree/7990f7c3733ed90b67d3f69a51395f0385eb22fa
[C01]: https://github.com/CoderLambert/news-aggregator/compare/cf069a23a7d52d94abc321e53f0d1e6bfa8f769d...7990f7c3733ed90b67d3f69a51395f0385eb22fa
[I52]: https://github.com/CoderLambert/news-aggregator/issues/52
[C02]: https://github.com/CoderLambert/news-aggregator/tree/7990f7c3733ed90b67d3f69a51395f0385eb22fa/docs/plans
[C03]: https://github.com/CoderLambert/news-aggregator/tree/7990f7c3733ed90b67d3f69a51395f0385eb22fa/crawler/news_crawler/spiders
[C04]: https://github.com/CoderLambert/news-aggregator/blob/7990f7c3733ed90b67d3f69a51395f0385eb22fa/crawler/news_crawler/pipelines.py
[C05]: https://github.com/CoderLambert/news-aggregator/blob/7990f7c3733ed90b67d3f69a51395f0385eb22fa/crawler/news_crawler/spiders/devto_spider.py
[C06]: https://github.com/CoderLambert/news-aggregator/tree/7990f7c3733ed90b67d3f69a51395f0385eb22fa/backend/api/services/article_fetcher
[C07]: https://github.com/CoderLambert/news-aggregator/blob/7990f7c3733ed90b67d3f69a51395f0385eb22fa/backend/api/services/article_fetcher/validators.py
[C08]: https://github.com/CoderLambert/news-aggregator/blob/7990f7c3733ed90b67d3f69a51395f0385eb22fa/backend/api/services/full_content_status.py
[C09]: https://github.com/CoderLambert/news-aggregator/blob/7990f7c3733ed90b67d3f69a51395f0385eb22fa/backend/api/views.py
[C10]: https://github.com/CoderLambert/news-aggregator/blob/7990f7c3733ed90b67d3f69a51395f0385eb22fa/backend/api/management/commands/auto_fetch_full_content.py
[C11]: https://github.com/CoderLambert/news-aggregator/blob/7990f7c3733ed90b67d3f69a51395f0385eb22fa/compose.prod.yaml
[C12]: https://github.com/CoderLambert/news-aggregator/tree/7990f7c3733ed90b67d3f69a51395f0385eb22fa/scripts/deploy
[C13]: https://github.com/CoderLambert/news-aggregator/blob/7990f7c3733ed90b67d3f69a51395f0385eb22fa/backend/api/services/crawler_control.py
[C14]: https://github.com/CoderLambert/news-aggregator/blob/7990f7c3733ed90b67d3f69a51395f0385eb22fa/backend/api/services/shared_translations.py
[C15]: https://github.com/CoderLambert/news-aggregator/blob/7990f7c3733ed90b67d3f69a51395f0385eb22fa/backend/requirements.txt
[C16]: https://github.com/CoderLambert/news-aggregator/blob/7990f7c3733ed90b67d3f69a51395f0385eb22fa/crawler/news_crawler/spiders/venturebeat_ai_spider.py
[C17]: https://github.com/CoderLambert/news-aggregator/blob/7990f7c3733ed90b67d3f69a51395f0385eb22fa/backend/api/services/tts_service.py
[C18]: https://github.com/CoderLambert/news-aggregator/blob/7990f7c3733ed90b67d3f69a51395f0385eb22fa/backend/api/services/research/tools.py
[C19]: https://github.com/CoderLambert/news-aggregator/blob/7990f7c3733ed90b67d3f69a51395f0385eb22fa/backend/api/serializers.py
[C20]: https://github.com/CoderLambert/news-aggregator/tree/7990f7c3733ed90b67d3f69a51395f0385eb22fa/backend/api/management/commands
[C21]: https://github.com/CoderLambert/news-aggregator/tree/7990f7c3733ed90b67d3f69a51395f0385eb22fa/frontend/src
[C22]: https://github.com/CoderLambert/news-aggregator/blob/7990f7c3733ed90b67d3f69a51395f0385eb22fa/.github/workflows/ci.yml
[C23]: https://github.com/CoderLambert/news-aggregator/blob/7990f7c3733ed90b67d3f69a51395f0385eb22fa/backend/api/models.py
[C24]: https://github.com/CoderLambert/news-aggregator/blob/7990f7c3733ed90b67d3f69a51395f0385eb22fa/docs/deployment/release-gates.md
[D01]: https://feedparser.readthedocs.io/en/stable/http-etag.html
[D02]: https://docs.scrapy.org/en/latest/topics/download-handlers.html
[D03]: https://developers.forem.com/api/v1
[D04]: https://github.com/HackerNews/API
[D05]: https://info.arxiv.org/help/api/tou.html
[D06]: https://reutersagency.com/content-delivery-platforms/content-delivery
[D07]: https://developer.wordpress.org/rest-api/reference/posts/
[D08]: https://docs.djangoproject.com/en/5.2/ref/databases/#sqlite-notes
[D09]: https://www.rfc-editor.org/rfc/rfc6585.html
[D10]: https://www.rfc-editor.org/rfc/rfc9110.html
[D11]: https://docs.github.com/en/rest/repos/contents#get-a-repository-readme
[S01]: https://www.leiphone.com/feed
[S02]: https://webkit.org/feed/
[S03]: https://www.smashingmagazine.com/feed/
[S04]: https://v8.dev/blog.atom
[S05]: https://hacks.mozilla.org/feed/
[S06]: https://svelte.dev/blog/rss.xml
[S07]: https://blog.angular.dev/feed
[S08]: https://feeds.bbci.co.uk/news/world/rss.xml
[S09]: https://techcrunch.com/feed/
[S10]: https://css-tricks.com/feed/
[S11]: https://web.dev/blog/feed.xml
[S12]: https://developer.chrome.com/static/blog/feed.xml
[S13]: https://react.dev/rss.xml
[S14]: https://openai.com/news/rss.xml
[S15]: https://deepmind.google/blog/rss.xml
[S16]: https://www.infoq.com/feed
[S17]: https://arstechnica.com/tag/artificial-intelligence/feed/
[S18]: https://www.technologyreview.com/feed/
[S19]: https://www.producthunt.com/feed
[S20]: https://frontendfoc.us/rss
[S21]: https://venturebeat.com/category/ai/feed/



