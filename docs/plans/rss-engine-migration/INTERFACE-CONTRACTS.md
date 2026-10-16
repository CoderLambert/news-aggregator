# RSS 引擎迁移的接口与数据更新合同

状态：REVIEW_REQUIRED。本文定义后续实现的v1协议，当前端点/类/表/命令大多尚不存在；本轮没有修改产品。所有实施依赖G0及其上游任务，不能将提案称为已部署合同。

## C01

### 运行边界

Miniflux唯一常规Feed/正文引擎，PG仅供Miniflux；NewsHub业务库继续SQLite；RSSHub仅批准的标准路由。app保持现有host网络/BYOK，indexer/channel-worker保留。T35在T08前交付rss-sync独立轻量target，NEWSHUB_RUNTIME_ROLE=rss_sync避免AppConfig预载模型；rss-sync单一轻量进程，最多2个在途有界API任务，SQLite写入串行短事务；不安装或导入Torch、embedding、Scrapy、feedparser、浏览器或网页提取器。Django AppConfig预加载必须显式避开。

服务端固定配置 engine_instance_uuid/account_id/base_url/token_secret_ref；实例UUID由受保护部署清单持久化，不按数字ID猜测。迁移/重建/恢复先核对实例及账号，未知身份停止写入。Miniflux API仅宿主环回/受控内部网，PG不发布宿主端口；浏览器只访问Django。

Miniflux 2.3.3为候选，不以latest发布；T00拉取并锁定实际镜像digest、兼容PG、SDK/nh3/markdownify/listparser版本及license；T01锁RSSHub。生产禁fetcher debug及未经审核代理。保留期目标显式read/unread均90天，使用CLEANUP_ARCHIVE_READ_DAYS和CLEANUP_ARCHIVE_UNREAD_DAYS；按上游created_at及真实保留记录处理，不按published_at推断。

初始候选参数（G1确认才冻结）：同步30s、页大小100、API短读超时10s、控制请求总时限30s、最多5次有限退避（429遵循Retry-After）、每条HTML/Markdown上限各2MiB、发现每用户10次/分钟、订阅每用户500个/每天新增50个、全站10000物理Feed、OPML1MiB/500项、query最长200字符、URL最长1024字符（文章News.url仍500）。这些是可审查的初值，不是已测容量；不足必须出测量及合同修订，不偷偷解除限额。

RSSHub经受保护公共HTTPS网关，实际公网DNS/回流/认证/证书通过T01；认证仅绑定规范化后的精确scheme=https、host、port=443及批准route/参数白名单。用户URL不能选择secret；拒绝userinfo、相似域名、子域、非批准端口、编码路径绕过。网关Feed禁自动重定向，跨origin/path跳转失败关闭；上游不能证明禁跳转/凭据隔离时该网关来源BLOCKED，不降级放开。FETCHER_ALLOW_PRIVATE_NETWORKS=0（禁止私网访问，防护保持启用）。RSSHub memory LRU项数≠内存字节预算，容器资源预算在T00/T01记录。配置/凭据不上客户端；用户不得提交proxy/cookie/header/TLS绕过。

## C02

### 模型所有权与身份

T05是所有新增DDL的唯一所有者。下表为逻辑模型合同；等价已有字段应复用，不能重建第二套Source/Subscription。模型映射表及migration编号必须在T05报告精确列出。

| 数据 | 必备字段、唯一约束 | 唯一写者与语义 |
| --- | --- | --- |
| Source / News / NewsSourceItem | 原PK/FK不变，Source.name和News.url原唯一保持；原source_key/upstream_id不变 | 旧历史只保护，不把Miniflux整数写成旧发布者ID |
| FeedBinding | uuid、engine_instance、account、engine_feed_id(nullable)、canonical_feed_url、mode、desired_enabled、connection_state、owner_epoch、last_error、policy_version | (instance,account,canonical_url)唯一；(instance,account,feed_id)非空唯一；rss-sync收敛引擎状态 |
| SourceFeedLink | source_id、binding_id、editorial_pin、association_policy、enabled | source/binding唯一，多对多；NewsHub决定逻辑频道/物理Feed映射 |
| SourcePublication | source_id、publication=public/personal/history_only、display_name、reading_policy、owner=legacy/miniflux/paused、epoch | Source一对一；旧公开来源显式初始化public，新用户源默认personal；发布只管理员审核 |
| EngineEntryMap | binding_id、engine_entry_id、news_id(nullable)、source_url、raw_hash、conversion_version、last_seen、disposition | (instance,account,feed,entry)复合身份；不只保存裸entry ID |
| BodyProvenance / BodyCandidateRecord | news_id、binding/map、policy_version、canonical_hash、upstream_raw_hash、conversion_version、completeness、evidence、candidate_status、owner_epoch | 正文主写绑定固定；冲突/降级候选落盘，不覆盖当前已接受正文 |
| FeedSyncState | instance/account、new_cursor、run_id、upper_id、page_cursor、lease_token/epoch/until、last_complete_at | 租约所有者提交；新增游标和对账游标分别持久化 |
| FeedOperation | UUID、kind、actor、binding、intent_version、dedupe_key、state、attempts、next_attempt、lease、safe_result、expires_at | 固定kind，活跃dedupe唯一；不保存任意HTTP或代码；非拥有者不得查进度 |
| FeedRejection / IdentityConflict | 复合条目身份、reason、safe metadata/hash、first/last_seen、retryable、resolution | 业务永久拒收可推进cursor；临时DB/API故障不能伪装永久拒收 |
| FeedDirectorySnapshot / Entry | checksum、upstream_commit、license、schema_version、activated_at；名称/URL或模板/标签/出处/verified_at/visibility | 原子切换快照，目录更新不注册Feed；未验证时间允许null |
| RssImportBatch / Item | user、file_hash、preview_token_hash、expiry、selected/group snapshot、per-item status/operation | 预览user-bound，一次确认幂等；不新增第二订阅真相 |
| NewsReadState | user、news、is_read、updated_at、version；(user,news)唯一 | NewsHub用户写入；缺记录视未读；不推断ReadingDay，不写引擎status/star |
| ChannelSubscription/Group/Member / ReadingDay / Favorite等 | 保留现有字段、约束和PK；跨组user归属由服务验证 | 各用户隔离；分组/统计/收藏/对话/研究/译文不因引擎清理删除 |

新Feed展示同名不作为身份；Source.name为稳定内部唯一名，现有名称不改，新名称可使用rss:<binding-uuid>且display_name承载人类名称，现有序列化对新增源改用display_name。不得通过随机修改已存在Source.name来满足约束。

Feed URL规范化仅scheme/host大小写、默认端口、fragment；禁止去业务query、改path大小写、合并尾斜线。凭据query/header与用户私有Feed拒绝；系统网关使用secret_ref而非URL凭据。文章URL沿用已审查身份规则，长度超旧字段上限则隔离，不静默截断/改schema。

URL碰撞须先证明同文章身份、政策兼容且正文主写权限一致才复用News；其余保存IdentityConflict，pending/blocked，不覆盖正文、不扩大发布权限。正文每次只由body_source_binding写，跨Feed不按长短抢写。不存在足够证据时停止自动合并。

## C03

### EngineAdapter v1

内部DTO均白名单、无cookie/password/内部URL；携带instance/account/feed/entry复合身份。时间UTC ISO8601，ID后端整数且对JSON大整数安全以十进制字符串表示。API业务ID不允许由浏览器替换engine地址或账号。

| 方法 | 输入 / 输出及副作用 |
| --- | --- |
| discover(url) | 引擎POST /v1/discover，返回[{feed_url,title,type}]，不自建解析器 |
| list_feeds / get_feed | 仅专用采集账号，供注册超时核对，不能透传Feed对象 |
| create_feed | canonical_url、服务端mode/网关secret；返回feed_id；未知结果先核对不能盲重试 |
| set_enabled | disabled显式值；引用数=0且无editorial_pin后先暂停，不删除引擎或历史 |
| refresh_feed | PUT /v1/feeds/{id}/refresh；不保证强制提取已有条目 |
| read_upper_bound | 官方SDK get_entries(order=id,direction=desc,limit=1)，返回当前可见最大ID H；空引擎H=0；该响应也受总预算限制，超限或无法验证完整身份时本轮BLOCKED，不猜H、不推进游标 |
| list_entries | order=id,direction=asc,after_entry_id=L,before_entry_id=H+1,limit=100；严格排他边界，不依赖默认排序 |
| get_entry | 返回title/url/comments_url/content/published_at/created_at和身份，不把entry.hash当正文hash |
| refetch_entry | 官方SDK最小参数扩展调用GET /v1/entries/{id}/fetch-content?update_content=true，然后重新GET验证持久结果；仅固定受控动作 |

官方SDK fetch_entry_content默认不持久化。扩展须T00实际验证，不可自写另一套客户端/抓取器；若SDK限制无法安全扩展，ADR-007阻塞，不悄悄切成NewsHub自己抓网页。

官方SDK的API定义/响应DTO保持复用；仅允许注入或最小替换受限session/transport（T00须证明所选SDK版本支持），不重写端点客户端。TransportRequest={method,fixed_engine_path,params,absolute_monotonic_deadline,max_wire_bytes,max_decoded_bytes}，TransportResult={status,headers,bounded_json}；短读绝对deadline10s，控制30s；整响应wire≤8MiB、解压后≤16MiB，每条HTML/Markdown≤2MiB。必须流式累计、解压预算、真正可取消I/O并在deadline中止；仅future超时而底层继续运行不合格。总页超限先减小page_size至1重放；单条仍超限且无法取得完整、已验证的复合entry身份时manual_blocked，保留cursor并报告，绝不猜ID或从不完整JSON落拒收再推进。只有完整响应身份已经安全确认而单条内容违反接收上限时，才可持久拒收并推进该条；DB临时失败不推进cursor。无法在SDK边界落实则T00/T04 BLOCKED并修订ADR-007，不能把requests socket timeout当总期限。

所有调用有期限/大小/重试上限，失败区分rate_limited/transient/rejected/unknown/auth_failed。创建/修复结果未知时先核对；HTML响应仅在引擎到同步内容通道出现，不放入操作状态或客户端预览DTO。来源429与API429分别记录。

## C04

### 内容与读取协议

EngineEntry → HTML清理/相对URL解析 → markdownify → BodyCandidate → CAS commit；转换不访问来源。raw_hash用于跳过同版本重复转换，canonical_hash为规范Markdown UTF-8 SHA256，保留代码内空格与字符，仅约定换行LF；算法及conversion_version写入provenance。历史正文及译文精确hash不重算。

BodyCandidate字段：composite_identity、news_url、expected_revision、owner_epoch、markdown、raw_hash、canonical_hash、conversion_version、content_kind、completeness、evidence、source_policy_version。结果枚举 unchanged/accepted/rejected/quarantined/conflict/stale。相同内容hash不增revision，provenance/policy改变单独记并失效权限缓存；正文变化原子revision+1。

full_content_state增加available；legacy/complete的旧含义不放宽。has_readable_content表示当前viewer可读的非空安全正文；completeness=unknown/summary/verified独立。Miniflux crawler=true、HTTP200、非空、长度都不能证明verified；verified只接受绑定当前canonical_hash的逐篇审核证据（reviewer/time/source URL/判断）。旧complete保留状态及历史证据，不批量认作新引擎已验证全文。

空/明确错误/政策拒绝不覆盖；明确摘要不覆盖旧完整正文；旧正文≥1000字符且候选不足50%默认隔离为疑似缩短（仅数据保护阈值，不推断完整性），人工审核后可接受合法编辑。阈值T00夹具验证。超限拒收不截断。News.content仍摘要，完整可接受内容进入full_content；不写站点CSS/XPath/正文提取规则。

StoredArticle(user,news_id) 返回授权的markdown、summary、revision、canonical_hash、content_kind、completeness、body_provenance及policy_version。无文章权限404；有摘要权限但无正文权限返回摘要scope；调用方不得越过helper取受限正文。AI提示标实际scope，TTS同样遵守。历史个人/共享译文按当前source_hash匹配，旧结果可保留但不得当当前译文。现有embedding仍按title+summary hash，不因为body revision变化强制重建。

前端统一helper支持available；新引擎产物禁止repairExplodedCodeBlock。旧legacy修复只显式legacy路径。安全媒体URL不代理下载，不把内部Miniflux proxy URL透给浏览器；有问题则隐藏该资源并给原文链接，是否安全可用由T00验证。

## C05

### 公开 API v1

沿用session+CSRF、当前用户校验、public-read-only和现有capabilities。写请求匿名拒绝，所有用户对象越权404；公开目录只显示published，个人来源仅授权用户；Cache-Control私有/no-store适用于个人内容。用户scope筛选与访问控制分离，向量先限制候选再二次校验。

统一错误 {error:{code,message,retryable},request_id}；400输入/冲突语义，401未登录，403只读/政策，404无权，409 stale或幂等键不匹配，413大小超限，429配额+Retry-After，502/503引擎不可用。新增对象使用UUID字符串；旧News/Source/Group ID继续原值。

| 端点 | 输入与返回 |
| --- | --- |
| GET /api/rss/discovery/?q=&limit=&cursor= | 200 {items:[DirectoryResult],next_cursor,snapshot_version}；只查本地；limit≤50；无网络采集 |
| POST /api/rss/discovery/resolve/ | {input}；缓存200 {candidates:[{candidate_id,feed_url,title,type,candidate_token}],expires_at}，待执行202 {operation_id,status}；discovery操作完成后查询同用户operation得到候选 |
| GET /api/me/rss-subscriptions/ | 返回现有ChannelSubscription的rss状态投影，不新建订阅体系 |
| POST /api/me/rss-subscriptions/ | Idempotency-Key及{candidate_token或directory_entry_id或feed_url,group_ids:[]}；已连接201/幂等200，否则202 {subscription_id,source_id,binding_id,operation_id,state} |
| DELETE /api/me/rss-subscriptions/{id}/ | 204，仅本人，重复取消幂等；不删除News/个人记录 |
| GET /api/me/rss-operations/{id}/ | 200 {id,kind,state,error?,safe_result?,updated_at}；actor授权；无HTML/凭据 |
| POST /api/rss/feeds/{id}/refresh/ | 授权binding_id，202 operation；显式合并限频；不承诺修复旧正文 |
| POST /api/news/{id}/rss-refetch/ | 仅已授权且policy允许的绑定条目，202 operation；明确单篇修复，不能通过GET触发 |
| POST /api/me/rss-imports/preview/ | 文件字节，200 {preview_id,token,expires_at,items,duplicates,unsupported,groups}；无网络 |
| POST /api/me/rss-imports/confirm/ | {preview_id,token,selected_item_ids,group_map}，202 {import_id,items}；token30分钟、绑定user/file hash/选择/分组 |
| GET /api/me/rss-imports/{id}/ | 当前用户批次进度及逐项operation_id，无他人状态 |
| GET /api/me/rss-export/ | 本人OPML文件，只公开Feed URL/可读rsshub别名，不含secret |
| GET/PATCH /api/me/news/{id}/read-state/ | {is_read,version} / PATCH {is_read,expected_version?}；200，跨用户不可见 |
| GET /api/admin/rss/health/ | 管理权限，聚合连接/错误/lag/对账完成信息；沿用现有索引管理，不自动抓取 |

DirectoryResult={id,name,description,language,region,tags,origin,kind:feed|route_template,public_url,required_parameters,capability_requirements,verified_at,subscribed,cached_articles[]}。candidate_token逐候选签名绑定user/规范feed_url/发现operation/expiry（15分钟），不可跨候选或跨用户复用；订阅三种输入互斥且校验请求hash。候选无缓存可返回空数组；来源URL不是engine内部URL，RSSHub无secret。无状态、账号数据或Feed验证时间时返回null/空，不伪造。

现有channel-groups API保持语义：多组、删除组不退订、取消订阅移除组归属；news detail/list按C04增字段不移除旧字段。旧fetch-full对miniflux owner只显式POST转rss-refetch或410解释，不能再排旧worker；legacy owner仅在过渡期按旧流程及fence运行。所有GET/列表/搜索/预览/hover/组切换不执行引擎刷新/正文抓取。

## C06

### 增量、对账与操作状态

新增游标不是提交日志。每轮取H后，仅L<id≤H，page_size100；H+1溢出/上游类型边界必须测试。新游标后保留最近1000个ID的回读窗口，仍由每日全保留条目对账兜底。run固定H且keyset分页可恢复；本轮低ID晚提交由下一完整轮发现，记录最后成功全轮完成时间。

先提交映射/正文或持久业务拒收，再提交页cursor；临时故障保持cursor不前进。上游实际删除只表示引擎保留结束，不删本地News。对账遍历实际存在的全部条目而非最近90天发布记录；只能同步引擎真正已存储变化，不能保证源站任意旧文编辑被抓到。

操作state：pending→running→succeeded；暂时故障→retry_wait→running；未知结果→unknown→核对后succeeded/retry_wait/manual_blocked；永久拒绝failed；已取消意图cancelled。lease过期仅有新lease epoch持有者提交。连接state：pending/connected/initial_sync/ready/failed/paused；HTTP成功不等于ready或完整正文。

每loop最多2个在途任务，新增短读预留一个槽位；控制请求有界，持续耗时单源隔离，写入串行。重放以复合映射/订阅唯一键/CAS幂等，拒绝不依赖日志一行。监控new lag、reconciliation age、oldest backlog、error class；积压距90天目标≤7天时告警，达到保留风险立即暂停继续上线并报告数据缺口。

## C07

### 目录、发现与 OPML

来源种子固定commit/license/hash；RSSHub metadata只白名单namespace/routes/name/description/parameters/features，忽略外部heat/topFeeds。参数填全且实际验证前仅template，不能称Feed。只读关键词查询不访问网络；POST发现仅Miniflux进行，候选不临时订阅。

目录更新按日校验，成功后原子切换active snapshot，失败保留旧版；用户源不自动published。优先URL/名称精确、名称前缀、标签描述、可用状态，确定性ID收尾排序；无额外服务、LLM或私有Folo搜索。

OPML仅解析上传清单不解析新闻Feed；禁远端实体、网取和过量深度，预览不调用引擎。确认逐项普通订阅、独立结果、重试失败项、group按本人归属验证。导出本人关系/分组，不导出引擎账号全部订阅；同一来源多组采用重复outline并在导入幂等合并（group set union），无其他用户统计。

## C08

### 用户状态

ChannelSubscription/Group/Favorite/BlockedNews/Chat/Research/Translation原数据保留；Miniflux专用账号从不承载个人read/star/category。ReadingDay保持原user/news/day及统计；显式ReadState仅当前用户PATCH，默认未读，不因新版本正文/退订被重置。跨用户写入/组引用由服务验证及唯一约束保护。

## C09

### 部署、备份与回滚控制入口

规划的统一入口 `scripts/rss`，所有命令必须显式 `--environment isolated|production --manifest PATH`；manifest精确绑定目标环境/实例/SHA。T02实现安装/启动，T03实现下列已定义协议，T32整合旧入口。命令尚不存在，不在本轮执行。

| 子命令 | 必填输入及执行语义 |
| --- | --- |
| install-check / status / diagnose | 公共参数；只读，不拉镜像/迁移/改变开关；返回结构化JSON，凭据脱敏 |
| start / update | `--target-release-manifest PATH`；默认plan/dry-run输出角色/版本/迁移差异；实际变更需`--execute` |
| backup | `--output-dir ABS_PATH --backup-id UUID`；默认只输出停写/备份计划，`--execute`后SQLite一致性快照+PG dump+sidecar；目录已存在拒绝覆盖 |
| restore | `--backup-manifest PATH --prior-backup-manifest PATH --writers-stopped`；默认dry-run；`--execute --replace`才恢复指定目标，先验证hash/schema/实例/恢复点且留prior backup |
| rollback | `--target-release-manifest PATH --expected-current-sha SHA --expected-schema-hash HASH`；默认dry-run；`--execute`只回应用/owner，禁止数据库恢复，要求T36封存的兼容目标 |

所有production变更（包括停写备份）另必需`--approval-file PATH`，批准文件绑定operation/environment/current+target SHA/source范围/window/backup_id/兼容manifest hash；字段不符或过期退出非0且不写入。isolated执行也必须匹配受控allowlist，不能仅凭环境字符串访问生产。`--execute`缺失时保证无变更；缺参数/未知schema/实例/恢复点/未停writer均失败关闭。具体输出为{operation,environment,plan,executed,artifacts,safe_errors}，失败nonzero且记录可追溯request_id。

发布manifest精确版本化，含SHA/digest、NewsHub schema集合、兼容schema allowlist证据、engine_instance/account、组件版本、secret引用和服务角色。旧脚本要求schema完全相等，不能直接当成已支持过渡回滚。T03只交付工具和隔离恢复验证，不产生生产兼容基点；T25旧入口fence完成后，由T36封存最后一个相同schema、已测能读available/新ACL且完整fence的兼容版本；T26/T28必须依赖该真实基点。额外schema变更另立兼容合同，不用migration子集代替测试。

停止所有writer（app写请求、rss-sync、legacy/indexer/channel-worker及任务线程），暂停Miniflux写入后取得可配对SQLite/PG快照，manifest列两个恢复点及映射hash。凭据通过受控secret备份，不输出值。默认普通rollback只回应用/owner，不恢复库；灾难restore单独批准并说明RPO。

## C10

### AI 与旧栈退出

ADR-002已经用户确认：不再抓中文译文链接；research fetch_article/fetch_webpage只读已同步内容，未收录网页给既有搜索摘要/URL及能力说明，不借研究工具恢复RSS正文抓取。现有联网搜索仍可保留必要安全HTTP工具，从article_fetcher抽离通用安全传输，禁止保留原Provider或重新包装成隐蔽提取器。

在T29所有来源替代/批准停更、真实验收、恢复演练通过前不得删除旧栈。T30停进程与宿主调度；T31删Scrapy/feed/parser/HTML extraction/Provider/full-worker引用；T32移除生产依赖与镜像层，保留历史migration的惰性数据和真正仍需的AI/索引。

## C11

### 来源迁移执行协议

T24盘点每个实际source_id：旧selection规则/PK/URL/用户计数/正文hash/Feed或路由候选/reading_policy/内容类型/覆盖差异/新owner/epoch/验收/回滚。代码来源与数据库动态来源取并集，未知生产状态写UNKNOWN，不猜测。

T25交付 `python backend/manage.py rss_migration plan|apply|verify --source-id ID --expected-owner OWNER --expected-epoch N --manifest PATH`；apply另需 `--approval-file PATH --execute`。plan默认dry-run，verify只读。审批绑定source_id/目标SHA/窗口/备份点/兼容SHA；不得用本轮规划授权替代。运行时先检查授权工单和所有前置，不因命令名存在就可上线。

T28只切换一个已批准试点；T29-SOURCE-ID每份单源工单独立批准/执行/审核/回滚，T29只汇总这些节点，不做批量实现。任务模板见T29目录；每个子工单继承T28且按全局source-cutover锁串行，全部完成后T30才可执行。历史不支持来源必须经批准history_only而非保留隐藏旧Spider。

owner epoch单调：legacy→paused（fence+排空）→miniflux；失败停paused，回legacy须核对曾受支持且单独批准。任何旧结果提交都检查开始时owner/epoch及当前值，禁止晚写。新Feed无旧支持，回滚只能暂停。生产迁移、回填、来源切换、数据删除、恢复均需具体授权。
