# RSS 引擎迁移的接口与数据更新合同

状态：REVIEW_REQUIRED，修订版 v2。本文定义待实现协议，不表示端点、模型或命令已经存在。架构方向沿用 [ARCHITECTURE.md](ARCHITECTURE.md)；任务开发、集成验收和上线条件分别见 [TASKS.md](TASKS.md)。

## C01

### 运行边界

Miniflux 是唯一常规 Feed 获取、解析和允许的正文提取引擎；PostgreSQL 仅供 Miniflux，NewsHub 业务库继续 SQLite。RSSHub 仅使用已维护的批准路由，不新增 Redis、消息队列、搜索服务、浏览器或抓取代理。app 保持 host 网络及现有 BYOK，indexer/channel-worker 保留。

T02 吸收原 T35：交付同仓库独立轻量 rss-sync target 和依赖锁。NEWSHUB_RUNTIME_ROLE=rss_sync 避开 AppConfig 模型预加载；不安装/导入 Torch、embedding、Scrapy、feedparser、浏览器和网页提取器。只有一个同步进程，最多两个在途 API 请求，SQLite 串行短写；网络请求不持数据库写事务。

engine_instance_uuid/account_id/base_url/token_secret_ref 为固定服务端配置；UUID 随受保护部署清单持久化，恢复/重建不得按数字 ID 猜身份。Miniflux API 仅环回/受控内部网络，PG 不发布宿主端口，浏览器只访问 Django。专用采集账号为非管理员，管理凭据分离；生产禁 fetcher debug，日志/异常脱敏，不配置未经审核的代理。自动接入只接受无凭据公开 HTTPS Feed，私网/环回/云元数据、危险协议及重定向/DNS 绕过由引擎与部署防护共同拒绝。

Miniflux 2.3.3 是候选。T00 验证并锁定引擎/PG/SDK 版本及镜像 digest；T06、T16、T21 分别锁定自身转换/目录/OPML 依赖和许可证；T18 锁 RSSHub。实现可先使用候选版本和 fixture，真实运行前核实制品，生产不用 latest。read/unread 保留期目标均为 90 天，显式配置 CLEANUP_ARCHIVE_READ_DAYS、CLEANUP_ARCHIVE_UNREAD_DAYS，按 created_at 和实际保留记录核验。

候选参数：同步 30s、页大小 100、短读 socket timeout 10s/控制 30s、最多 5 次有限退避并遵循 Retry-After、单条 HTML/Markdown 各 2MiB、OPML 1MiB/500 项、query 200 字符、Feed URL 1024 字符（News.url 仍 500）。发现每用户 10 次/分钟、订阅每用户 500 个/每天新增 50 个、全站 10000 物理 Feed 为待测初值。限额可通过测量和常规配置评审调整，不因调参新增 ADR，也不声称 socket timeout 是请求总期限。

RSSHub 使用既有 Nginx 的受保护公共 HTTPS 网关；FETCHER_ALLOW_PRIVATE_NETWORKS=0，保持私网防护。认证仅附加于系统配置的精确 HTTPS origin 和批准 route/参数，用户输入不能选择 secret、proxy、cookie、header 或 TLS 绕过。拒绝 userinfo、相似域名、路径编码绕过，认证 Feed 禁跳转；真实 DNS/TLS/公网回流、路由及凭据隔离由 T18 验收。失败只阻塞该 RSSHub 功能上线。memory LRU 项数不等于内存字节预算；资源实测包含全部服务。

## C02

### 数据、身份和写入权

复用现有 Source/News/NewsSourceItem/用户订阅模型，不重建业务 PK/FK。T05 负责核心身份、权限、正文及同步模型；T13 的已读、T16 的目录、T21 的导入模型随功能交付。迁移编号和共同 models 文件串行合并，不要求一次预建全部 DDL。

| 数据 | 字段/约束与所有权 |
| --- | --- |
| Source / News / NewsSourceItem | 原 PK/FK、Source.name 与 News.url 唯一约束、旧 source_key/upstream_id 保持；Miniflux 数字 ID 不冒充发布者 ID |
| FeedBinding | uuid、instance/account、engine_feed_id(nullable)、canonical_feed_url、desired_mode、desired_enabled、connection_state、policy_version、applied_policy_version、last_error；规范 URL 和非空 feed_id 各在 instance/account 内唯一 |
| SourceFeedLink | source_id、binding_id、editorial_pin、enabled、association_policy；source/binding 唯一；association_policy V1 只允许全部条目或 manifest 中明确的本地元数据过滤，不保存执行代码 |
| SourcePublication | source 一对一；publication=public/personal、display_name、reading_policy、policy_version、owner=legacy/miniflux/paused、epoch、pause_reason；停更不改变 publication |
| EngineEntryMap | binding_id、engine_entry_id、news_id(nullable)、source_url、comments_url、raw_hash、conversion_version、last_seen、disposition；binding 关联 instance/account，复合身份为 instance/account/feed/entry |
| 正文归属 / provenance / 候选 | News 上唯一 body_owner（legacy source 或 binding）、body_owner_version；保留实际已接受正文 provenance/hash；候选带 source_id/source_epoch、body_owner_version、source_policy_version、binding_policy_version；按条目身份/候选 hash/转换与政策版本去重 |
| FeedSyncState | instance/account、new_cursor、run_id、upper_id、page_cursor、lease_token/epoch/until、last_complete_at；新增和对账进度分别持久化 |
| FeedOperation | UUID、kind、actor、binding、intent_version、dedupe_key、state、attempts、next_attempt、lease、safe_result；固定动作，不保存任意 HTTP、代码或来源 HTML |
| FeedRejection / IdentityConflict | 复合身份、reason、safe metadata/hash、first/last_seen、retryable、resolution；永久业务拒收与临时故障分开 |
| LegacyTranslationSnapshot | news、field=title/content/full_content、source_hash、translation_hash、source_text、translated_text、origin、captured_at；news/field/source_hash/translation_hash 唯一，仅归档旧兼容字段，不新建翻译任务体系 |
| FeedDirectorySnapshot / Entry（T16） | checksum/commit/license/schema_version/active；名称、URL/模板、标签、出处、verified_at(nullable)、visibility；快照原子切换 |
| RssImportBatch / Item（T21） | user、file_hash、preview_token_hash、expiry、confirmed_request_hash、选项/分组快照、逐项结果；不新增订阅真相 |
| NewsReadState（T13） | user/news 唯一、is_read、updated_at、version；缺记录未读，不推断 ReadingDay |
| 现有用户关系 | ChannelSubscription/Group/Member、ReadingDay、Favorite、Chat、Research、私人/共享译文及任务保持 PK、归属和历史 |

新来源使用稳定内部唯一名（如 rss:<binding-uuid>），display_name 用于展示；不随机重命名旧 Source。Feed URL 只规范 scheme/host 大小写、默认端口、fragment，保留业务 query、路径大小写及尾斜线差异。凭据型私人 Feed 不支持；系统网关凭据使用 secret_ref。文章 URL 沿用已审规则，超 500 字符拒收而不截断。

关联、读取、覆盖分别判断：

| 情况 | 处理 |
| --- | --- |
| 同一复合 entry 重放 | 复用映射，校验 URL/身份；相同内容不重复写 |
| 不同 Feed 的规范文章 URL 完全相同，政策兼容 | 可关联已有 News 和频道，不授予新 Feed 正文/元数据覆盖权，不要求两者原本具有相同主写者 |
| 标题相似、URL 身份冲突、政策无法证明兼容 | 记录 IdentityConflict，保留原 News/正文/权限；不猜测合并 |
| 旧 News 首次转入引擎 | 迁移 manifest 明确绑定和允许的主写接管；只转换写入权、递增 body_owner_version，不改旧正文/hash/provenance；下次合法候选再更新 |
| 主写绑定停用/丢失 | 保留正文，停止其更新；更换主写者需明确映射和 CAS，不按长度或到达顺序自动接管 |

source_epoch 只对应 SourcePublication.epoch；binding 不再有含义重复的 owner_epoch。body_owner_version 防止不同来源的旧任务覆盖同一个 News；operation lease epoch 只用于任务执行租约。新旧写入均在同一短事务内核对当前 source owner/epoch、正文主写者/版本、当前政策版本以及 News URL/revision。旧来源即使仍为 legacy，也不能越过另一来源已经接管的文章写入权。元数据更新采用同样的主写权检查。

频道成员 = 原 News.source/NewsSourceItem 成员 + 通过 SourceFeedLink.association_policy 的 EngineEntryMap 成员；查询去重并先授权，再做用户 scope、分类/地区过滤与计数。T09 更新 channel_articles 等查询适配，不把旧 source_key 改成新 entry ID。public/personal 均独立于采集启停；history_only 仅为迁移结果说明，落库使用 owner=paused、pause_reason=unsupported，保留原 publication。

## C03

### EngineAdapter v1

DTO 白名单，不透传 Feed 凭据、内部媒体地址。时间 UTC，JSON 大整数使用十进制字符串；业务请求不能替换引擎地址或账号。

| 方法 | 输入、结果和副作用 |
| --- | --- |
| discover | URL → 候选 Feed 列表；仅引擎发现，不临时订阅 |
| list_feeds / get_feed | 专用采集账号，创建超时后核对及配置确认 |
| create_feed | canonical_url、服务端 mode/网关 secret → feed_id；未知结果先核对 |
| set_enabled | disabled 显式值；结合有效来源引用/editorial_pin 收敛，暂停不删除历史 |
| update_feed_policy | binding、expected_policy_version、白名单 desired_mode/disabled/批准链接过滤 → 官方 SDK update_feed，再 GET 核对；不接收任意 scraper/rewrite 代码 |
| refresh_feed | PUT /v1/feeds/{id}/refresh；不承诺重新提取旧正文 |
| read_upper_bound | get_entries(order=id,direction=desc,limit=1) → H；空引擎 H=0，失败不猜上界 |
| list_entries | order=id,direction=asc,after_entry_id=L,before_entry_id=H+1,limit；排他边界 |
| get_entry | title/url/comments_url/author/content/published_at/created_at 与复合身份；hash 不当正文 hash |
| refetch_entry | 固定引擎 fetch-content?update_content=true，再 GET 验证持久结果；只由显式操作执行 |

官方 SDK 优先。持久修复参数缺口允许最小扩展；不另写端点客户端或来源抓取器。复用成熟 HTTP 库的连接/读取 timeout，分页、有限重试、引擎抓取上限与进程资源限制。T04 在锁定 SDK 边界验证响应大小保护；如需补丁，只针对有证据的风险采用小型受限响应读取封装，覆盖 get_feeds/read_upper_bound 等非普通页入口。V1 不定义 TransportRequest/TransportResult、自定义解压协议、流式 JSON 解析器或精确到秒的可取消 I/O 框架。

HTTP socket timeout 不保证绝对总时长。持续占槽须告警、隔离问题操作，并由进程监督终止/重启卡住的 worker；租约和持久意图负责恢复。future 超时不得报告底层已取消，进程重启也不证明引擎远端操作停止；创建/配置/修复都先核对未知结果。上线前验证巨大响应不会无界耗尽进程且 worker 可恢复，不将尚未验证的保证写成 PASS。

页超限可减小 page_size 重放；只有完整验证条目身份后才能落永久拒收并推进进度。无法取得完整身份时保留 cursor、记录阻塞，不猜 ID、不解析残缺 JSON 后跳过；按绑定定位、调整经测量的限额或修复上游后重放。此类运行缺口阻塞受影响同步上线，不阻塞目录/转换开发。

政策变更先递增本地 policy_version，立即限制读取和新操作；收紧采集时暂停该绑定，取消旧版本待执行修复，应用配置并 GET 核对 applied_policy_version 后再恢复。执行前、提交时重验政策；过期在途结果不发布。已有引擎请求可能已经发出，禁用不宣称能撤回网络请求；要求零后续请求的切换须等待在途结束，无法证明时保持暂停。共享绑定采用经批准的统一模式，关联政策冲突未解决前不能启用。

## C04

### 内容、元数据和译文

EngineEntry → 已有 HTML 安全清理/相对 URL 解析 → markdownify → BodyCandidate → CAS。禁止访问发布者、识别网页主体或调用旧提取 validator。raw_hash 仅跳过相同转换版本的正文转换，不能跳过元数据、关联或政策检查。canonical_hash 为 Markdown UTF-8 SHA256，换行 LF，代码字符/空格保持；历史正文不批量规范化。

BodyCandidate 携带复合身份、news_url、expected_revision、C02 的来源/主写/政策令牌、markdown、raw_hash、canonical_hash、conversion_version、content_kind、completeness、evidence。结果 unchanged/accepted/rejected/quarantined/conflict/stale。相同正文 hash 不增 revision；归属/政策变化单独递增相应版本并失效权限缓存。正文变化原子 revision+1。

available 表示已获得可读内容；unknown/summary/verified 表示完整性，旧 legacy/complete 语义保留。非空、安全且获授权的 unknown 内容可直接阅读、翻译和 TTS。crawler=true、HTTP200、长度不能证明完整。V1 不要求逐篇人工审核，不开发常态审核队列；人工完整性记录仅用于有限验收样本或可选 hash 绑定证据，内容变化后不沿用 verified。

空/明确错误/政策拒绝不覆盖；明确摘要不替换旧完整正文。大幅缩短的可疑候选保留但不立即覆盖，按身份/hash 去重，采用受控命令接受/拒绝，无需专用审核平台。“旧正文≥1000 字符且新正文<50%”仅为可配置初值，由 T07 样本校准；不推断完整性，普通调参不要求 ADR。单条正文超限拒收，不截断后声称完整。

T09 负责以下基础元数据合同，T07 负责正文提交：

| 字段 | 首次导入与更新规则 |
| --- | --- |
| News.url、source、category | URL 为已审身份；source 来自准入映射，category 继承来源已有分类或现有默认分类；冲突拒收。已有 News 主来源/分类不随跨 Feed 重放改动 |
| title、author | 使用引擎文本字段；title 非空且满足模型限制，缺 title 拒收；author 缺失不清旧值。只有文章主写者可更新；超长字段按明确拒收处理 |
| News.content | 从已清理的内容本地派生纯文本摘要，默认最多 500 字符、规则版本化；这是列表摘要而非正文截断。空内容不抹除旧摘要，不调用 AI/来源网络 |
| publish_time | 有效 published_at 优先；缺失用 created_at 并标 inferred。重放不能用推断时间覆盖已有可信发布时间 |
| comments_url | 存 EngineEntryMap，按当前频道返回对应讨论链接；跨 Feed 不互相覆盖 |
| cover_image、content_kind | 封面仅采用已有合规字段/安全内容中的 HTTPS 图片，无则留空；不下载。类型按批准来源/条目元数据表达，HN 视频、仓库、arXiv 摘要不冒充新闻全文 |
| title_hash、摘要索引 | 标题/摘要变化才沿用现有索引失效逻辑；正文 revision 变化不强制 embedding，也不由 rss-sync 导入模型 |
| title_zh/content_zh/full_content_zh | 对应源文本变化前归档兼容字段并解除当前展示；见下文，禁止直接清空导致唯一副本丢失 |

私人/共享译文和任务继续使用现有 user/connection/news/source_hash 关系。旧 News 兼容字段可能没有独立译文记录：T07 在首次替换对应源文本前，在同一事务保存 LegacyTranslationSnapshot 的原文、译文、精确 hash 和 legacy/已知来源标记，再清当前兼容展示字段；禁止伪造 provider。旧正文未变化时保留原字符串/hash。T14 当前译文读取必须匹配当前正文/标题/摘要 hash，不再无条件回退旧字段；未曾绑定且来源版本不明的译文只归档为历史，不宣称已验证匹配。旧异步翻译开始时捕获对应源 hash，完成时 CAS；旧结果可保留历史但不得发布为当前。

StoredArticle(user,news_id) 返回授权 markdown/summary、scope、revision、canonical_hash、content_kind、completeness、provenance 和政策版本。无文章权限 404，只有摘要权限则 summary scope；AI/TTS/搜索均不得绕过。provenance 改变即使正文不变也要重新授权。前端支持 available，新内容不经过 repairExplodedCodeBlock；旧修复仅显式 legacy。媒体不代理下载，隐藏不安全/不可达内部 URL 并提供原文链接。

## C05

### 公开 API v1

沿用 session+CSRF、用户校验、public-read-only/capabilities。匿名写拒绝，越权用户对象 404，个人响应 private/no-store；用户 scope 筛选不代替 ACL，向量候选限制后再次授权。旧公开来源保留公开性，新来源默认 personal，仅有效订阅者可见；收藏本身不授予来源权限。

错误 {error:{code,message,retryable},request_id}；400 输入、401 未登录、403 政策/只读、404 无权、409 stale/幂等请求不匹配、413 超限、429 配额、502/503 引擎失败。新业务对象 UUID；原 News/Source/Group ID 保持。

| 端点 | 合同 |
| --- | --- |
| GET /api/rss/discovery/?q=&limit=&cursor= | 本地 DirectoryResult 列表/next_cursor/snapshot_version；limit≤50，无来源请求 |
| POST /api/rss/discovery/resolve/ | {input}；缓存 200 候选，异步 202 operation；不自动订阅 |
| GET/POST /api/me/rss-subscriptions/ | 复用 ChannelSubscription；POST 互斥选择 candidate_token/directory_entry_id/feed_url，带 group_ids 和 Idempotency-Key；201 已连接、200 重放、202 待连接 |
| DELETE /api/me/rss-subscriptions/{id}/ | 本人关系幂等 204，不删 News/历史用户记录 |
| GET /api/me/rss-operations/{id}/ | 仅 actor，安全状态/result，无 HTML/secret；跨用户共享物理注册时各有本人操作视图，由唯一 binding 合并实际引擎动作 |
| POST /api/rss/feeds/{id}/refresh/ | 授权 binding，202、合并限频；不是旧正文修复承诺 |
| POST /api/news/{id}/rss-refetch/ | 文章/绑定授权及当前政策允许才 202，worker 执行 |
| PATCH /api/admin/rss/feeds/{id}/policy/ | 管理权限，{desired_mode,expected_policy_version} → 202 配置操作；只允许系统政策白名单 |
| POST /api/me/rss-imports/preview/ | 有界文件字节 → preview_id/token/expiry/items/groups；无网络 |
| POST /api/me/rss-imports/confirm/ | {preview_id,token,selected_item_ids,group_map} → 202 import；校验本人分组/选项后原子保存 confirmed_request_hash，重复相同请求返回原批次，不同请求 409 |
| GET /api/me/rss-imports/{id}/ | 本人逐项状态，失败项可重新走幂等订阅，不重做成功项 |
| GET /api/me/rss-export/ | 本人 Feed/分组 OPML，RSSHub 别名不含 secret |
| GET/PATCH /api/me/news/{id}/read-state/ | is_read/version；PATCH 可带 expected_version，当前用户且文章可见 |
| GET /api/admin/rss/health/ | 管理权限，连接错误、lag、对账完成/积压，不触发抓取 |

DirectoryResult={id,name,description,language,region,tags,origin,kind:feed|route_template,public_url,required_parameters,capability_requirements,verified_at,subscribed,cached_articles[]}。未知时间/统计为 null，预览仅已有授权缓存。candidate_token 可绑定 user/规范 URL/发现操作/15 分钟 expiry；直接 URL 输入仍完整校验，token 不是采集权限。OPML 预览 token 只绑定 user/file hash/preview_id/30 分钟 expiry，不预先绑定尚未选择的项和分组。

分组保持多组、删组不退订、退订移除组归属。news API 增字段不移除兼容字段。旧 fetch-full 对 miniflux owner 显式 POST 转修复或 410；legacy 仅过渡期且完整 fence 下运行。GET、首访、搜索、预览、hover、切组均不触发正文获取/引擎刷新。

## C06

### 增量、对账与控制操作

新增按 L<id≤H 升序 keyset 分页，H 固定，本轮进度持久化；测试 H+1 类型边界。可配置回读窗口（初值 1000 ID）补近期乱序，仍需每日完成全部实际保留条目的对账；不按 published_at 截断，不依赖 changed_at 或 read/star。低 ID 晚提交由后续完整轮补齐。

先提交 News/元数据、关联、正文或永久业务拒收，再提交页 cursor；临时 DB/API 故障不推进。崩溃可重放，cleanup 不删除本地 News。只能发现引擎已保存的变化；超过保留期且无备份的缺口明确报告。

固定操作 register/set_enabled/update_feed_policy/discover/refresh_feed/refetch_entry。state 为 pending/running/retry_wait/unknown/manual_blocked/succeeded/failed/cancelled；过期 lease 的旧执行者不能提交。创建/配置未知结果先 GET 核对；控制和同步共单进程，短读保留容量，写事务不跨网络。

T09 交付 new lag、reconciliation age、oldest backlog、error class；T20 展示连接/同步状态，HTTP 成功不等于 ready。保留期风险告警阈值可配置（初值距目标 7 天），超保留期报告缺口并停止继续扩大上线。不会以告警触发另一套来源爬虫。

## C07

### 目录、发现、OPML

固定种子 commit/license/hash，目录是元数据而不是已验证健康列表。RSSHub 仅声明式 namespace/routes/name/description/parameters/features；忽略 heat/topFeeds，不执行 Radar JS。参数/能力未满足时只能展示 template。

目录按日检查，校验后原子换快照，失败用旧版。URL/名称精确、前缀、标签描述、可用状态排序，ID 稳定收尾；无独立搜索服务/LLM。用户订阅不自动发布到全站。

OPML 仅 listparser 解析上传字节，拒远端实体/网取/超深输入；预览无引擎操作，确认逐项复用订阅服务。导出本人关系，多组重复 outline，导入 group set union 幂等。目录、发现、直接 URL 三个入口分别可开发，最终统一订阅校验。

## C08

### 用户状态

保留用户身份/凭据/OAuth、ChannelSubscription/Group、Favorite/BlockedNews、Chat/Research、全部译文及任务。ReadingDay 保持 user/news/day 和统计；NewsReadState 默认未读，不推断旧已读、不因退订/正文更新重置，不写 Miniflux read/star/category。组和订阅的跨用户归属在服务入口校验。

## C09

### 运维入口与兼容回滚

复用现有部署脚本，提供薄入口 scripts/rss；不另建审批服务/通用运维平台。显式 --environment isolated|production --manifest PATH 绑定目标；只读 status/install-check/diagnose 不变更。start/update/backup/restore/rollback 默认 dry-run，--execute 才变更；restore 覆盖还需 --replace、prior backup 和停写检查。

manifest 记录 SHA/digest、schema 集合、engine_instance/account、组件/角色、secret 引用、备份恢复点及兼容证据。备份使用 SQLite online backup 与 PG dump；停止全部 SQLite writer（app、sync、legacy、indexer、channel-worker、后台线程）及 Miniflux 写入，取得可配对快照，不复制活动 SQLite 主文件忽略 WAL。恢复先校验身份/schema/hash/目标和恢复点，失败保持停写。

授权沿用现有部署权限和变更记录：执行切源/恢复/发布前核对批准的环境、来源集合、目标版本和窗口；可一次批准明确批次，不要求每个命令携带自定义 approval-file。隔离测试使用明确资源 allowlist，环境名称不能代替目标检查。一般字段/索引调整按迁移和兼容测试评审，不要求每次另立 ADR。

T03 只交付工具/隔离两库恢复，不依赖 T11 开发完成。T26 合并原 T36：先选择含完整 fence、available/ACL 读取的候选过渡镜像，在隔离副本执行往返回滚；通过后封存 SHA/digest/schema/manifest 为生产兼容基点。演练本身无需先获得“已演练封存”的基点，避免自我前置。默认同 schema 回滚最简单；早期可先演练核心流程，最终封存前须核对计划发布的 T13/T16/T21 领域 DDL 已纳入受测 schema。领域 DDL 可作为小提交先集成，不要求 OPML/健康 UI 先完成；尚未纳入的 schema 不在封存证明范围。后续 schema 变化重测兼容目标，不把 migration 子集当兼容证明。

普通 rollback 只回应用/来源意图，保留新增数据，不恢复库；灾难 restore 单独决定恢复点/RPO。T29 生产试点必须使用已经封存的兼容基点。未知 schema/实例拒绝写入，无受测基点先暂停。

## C10

### AI 与旧栈退出

ADR-002 保持：翻译不抓中文外链，研究 fetch_article/fetch_webpage 仅已同步正文，未收录给既有搜索摘要和 URL；联网搜索继续使用必要通用安全 HTTP 工具。先抽离共用安全工具，再删旧 Provider，不能改名保留来源提取器。

全部来源替代或明确停更、迁移与恢复验收通过后，T30 停旧进程/宿主调度并验证重启；T31 合并代码、依赖、镜像/脚本清理，保留历史迁移及 AI/索引功能。最终新部署必须停止上一版本遗留容器/定时角色，不能仅从 Compose 删除定义。T33 最终单栈验证后才发布；兼容镜像留存但正常运行不依赖旧栈。

## C11

### 来源切换与失败保护

T24 用代码清单与授权一致性副本取并集，记录 source_id、旧选择规则、Feed/路由、对象类型、覆盖差异、publication/reading_policy、owner/epoch、用户关系/正文及译文 hash。未知值标 UNKNOWN，实际来源数未知仅阻塞生产范围冻结，不阻塞独立开发。

T25 交付 rss_migration plan|apply|verify --manifest PATH --source-ids ID[,ID...]；manifest 含各 source 的 expected-owner/epoch 与目标绑定。单源用单个 ID；共用物理 Feed 的旧来源形成最小切换组，计划必须包含会继续重复采集该绑定的全部旧来源。apply 需 --execute；plan 默认只读，verify 只读。生产检查已批准批次/窗口、备份和封存兼容基点；isolated 可用合成 manifest 验证，不依赖生产盘点或封存产物。

切换顺序：部署带 fence 的兼容旧入口并重启/排空不带令牌的旧进程 → 切换组 legacy→paused、epoch 递增 → 阻止新旧任务启动并排空在途 → CAS 移交文章主写权 → 确认引擎政策/引用 → 激活 miniflux。所有旧 RSS/HTML/backfill/manual/全文及元数据写入在获取前捕获令牌、提交时重验；仅检查调度开关不够。不能改造已运行旧二进制，未排空不得宣布隔离完成。失败保持 paused，可重复 verify/recover。

Source 暂停与物理 Feed 暂停不同：共享绑定仍有其他有效新来源引用时可以继续采集，但不能向暂停来源新增成员或由它发布结果。只有无有效引用且无 editorial_pin 才停物理 Feed。切换组消除 legacy 与 Miniflux 对同一绑定的重复采集。回 legacy 仅对旧支持来源、明确事故范围和受测兼容版本；新 Feed 只能暂停。任何方向切换 epoch/body_owner_version 均递增，防止 ABA 晚写。

T29 合并原 T28：先执行一个批准试点来源或最小共享切换组，验收后再执行其余批准批次。一个统一 manifest 和逐源结果表足够；特殊政策/路由/失败来源才另开工单，不强制 N 份三文件、N 个 PR。逐来源保留覆盖差异和结果，公共权限/恢复测试复用已验收版本的证据，实际切换串行。不支持来源以 owner=paused/pause_reason=unsupported 保留原访问范围和历史，不保留隐藏 Spider。
