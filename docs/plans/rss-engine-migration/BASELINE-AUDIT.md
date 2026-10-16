# NewsHub RSS 重构代码基线与数据兼容审计

> 证据版本说明：本文保留对 878b690 / 上游候选版本的静态审计事实，不是运行证明。514410b 之后的任务编号、并行/审批/DDL/transport 和验收建议由修订后的 [决议](ARCHITECTURE-DECISIONS.md)、[接口合同](INTERFACE-CONTRACTS.md)、[任务](TASKS.md) 覆盖；不得把历史建议当作额外前置。

审计日期：2026-10-16。固定代码基线：`878b69081f8d5b3ae965bcf1c855390b059caa33`。本报告描述该提交的源码事实及迁移合同要求，不证明线上已实现目标架构，也不构成生产迁移授权。

## 审计范围与证据边界

在隔离规划工作区读取模型、迁移、服务、前端和已有测试；未执行产品代码、迁移、批量回填、来源切换或生产操作，未打开实际 SQLite、环境文件或凭据。仓库文件清单未发现 `AGENTS.md` 或 `CLAUDE.md`。

原工作区 `git status --short` 仅记录以下路径，不读取数据库内容、不纳入其他本地改动：

- 已修改：`backend/db.sqlite3`。
- 未跟踪：`docs/NewsHub-RSS-Architecture-Final-2026-10-16.md`。
- 未跟踪：`docs/features/NEWSHUB-CODEX-LOCAL-ACCEPTANCE-2026-10-14.md`。

用户已确认将第一份未跟踪架构定稿的原文纳入本规划目录的 `ARCHITECTURE.md`。用户进一步确认：研究工具只读取本地已保存正文，但保留联网搜索；新增独立的可设已读/未读状态并保留 `ReadingDay`；共享物理 Feed 的采集模式由管理员统一决定。执行 Agent 不得重新解释这些已确认边界。

上游 API 能力、版本与运行部署证据分别由本目录独立上游核验、运维核验文档说明；本报告不把源码默认值当成当前线上配置。

## 已实现、需要调整与最终删除

| 能力 | 当前已实现 | 需要调整 | 最终删除的旧实现 |
|---|---|---|---|
| 来源与频道 | `Source`、静态来源政策、动态 `SourceConfig/SourceEndpoint`、接入审批 | 增加引擎身份/共享 Feed 绑定；频道状态与成员查询退出 Spider 注册表 | Spider 执行注册、动态 HTML/Feed 解析执行逻辑 |
| 个人订阅与分组 | 用户订阅、分组、成员、资讯范围偏好及人工分组覆盖 | 接入新 Feed 生命周期；保留用户关系与人工选择；数据库与服务共同校验归属 | 不删除个人订阅/分组模块 |
| 阅读与用户行为 | 收藏、点赞、屏蔽、`ReadingDay` 按日阅读遥测 | 新增独立 read/unread；个人 Feed 内容不得自动全站公开 | 首访自动获取正文及旧任务轮询语义 |
| 文章保存 | `News`、发布者身份 `NewsSourceItem`、URL 唯一、正文 revision/CAS | 同步引擎结果；冲突隔离；可读性与完整性分离；内容对账 | NewsHub 自己下载/解析 Feed 和网页正文 |
| 阅读展示 | Markdown、代码高亮、目录及已有语言模式 | `available` 内容完整显示；新内容跳过历史代码修复；保留体验 | 新引擎内容经过历史代码重排的路径 |
| 翻译与 AI | 私人/共享译文、用户聊天、推荐问题、研究及 TTS 消费路径 | 所有入口统一读取已授权本地内容快照；消除隐式旧采集 | 多级正文 Provider、全文 Worker 以及 AI 触发它们的调用 |
| 搜索 | 摘要向量索引、正文关键词查询 | 保留现有摘要索引语义；所有返回结果执行统一可见性过滤 | 不删除向量索引或联网搜索 |
| 调度与恢复 | 旧抓取任务/租约/条件请求状态 | 新单进程 API 同步、原子检查点、可续跑内容对账、引擎控制请求 | 新系统真实验收后删除 Scrapy、旧 Feed 解析及全文任务运行路径 |

来源注册仍直接绑定 Spider：[`source_registry.py:7`](https://github.com/CoderLambert/news-aggregator/blob/878b69081f8d5b3ae965bcf1c855390b059caa33/backend/api/services/source_registry.py#L7)。可订阅状态也依赖该注册表：[`channel_catalog.py:12`](https://github.com/CoderLambert/news-aggregator/blob/878b69081f8d5b3ae965bcf1c855390b059caa33/backend/api/services/channel_catalog.py#L12)。不能先删注册表，再期待现有频道继续可订阅。

## 数据所有权与必须保留的关系

| 数据 | 当前键与关系 | 目标所有权与保留要求 |
|---|---|---|
| `Source/Category` | 名称唯一；`News.source/category` 使用 `PROTECT` | NewsHub 业务身份；保留主键、名称及人工元数据，目录候选不能按同名覆盖 |
| `News` | URL 全局唯一；来源为单值外键 | NewsHub 已接受文章事实；不重建文章，不用 Miniflux ID 替换主键 |
| `NewsSourceItem` | `(source_key, upstream_id)` 唯一，指向 `News` | 保留旧发布者身份；引擎 instance/account/feed/entry 身份另行建映射 |
| `ChannelSubscription/ChannelGroup/ChannelGroupMember/NewsPreference` | 用户+来源唯一、用户+分组名唯一；分组成员关联订阅 | NewsHub 用户私有；保留关系和默认资讯范围 |
| 智能分组数据 | `SourceTopicProfile`、配置、人工覆盖、提案、订阅分组状态 | 保留人工调整、提案历史和已有来源/分组/订阅外键 |
| `Favorite/BlockedNews` | 用户+文章(+类型)唯一 | NewsHub 用户私有；不能写共享 Miniflux 已读/收藏状态 |
| `ReadingDay` | `(user, news, day)` 唯一 | 保留原日期、用户/文章关系和统计；不是 read/unread 的替代表 |
| `ChatSession/LegacyChatArchive` | 用户/文章关联或历史归档 | 保留聊天及历史归档，不因采集切换重置 |
| 私人译文/任务 | 用户、连接、文章及 source hash | 保留归属、任务和结果；旧任务不得向新正文发布过期结果 |
| 共享译文/任务 | 文章、source hash、语言、翻译版本 | 保留历史译文及其原 hash；新版本只失效当前命中，不批量删除历史 |
| 研究 | `ResearchSession/ResearchSearchResult/ResearchRun/ResearchRunEvent` | 保留用户、会话、结果与事件；历史结果 JSON 中的文章引用也需兼容 |
| 用户身份/凭据关联 | Django 用户、授权、个人模型连接和相关外键 | 不迁移到 Miniflux、不重建用户、不读取或搬运凭据 |
| 来源审批及旧采集审计 | `SourceConfig/SourceEndpoint`、接入申请、抓取/正文事件等 | 保留历史政策与审计证据；是否归档模型须由单独删除任务确认，停止执行不等于删除历史表 |

模型证据：[`models.py:28`](https://github.com/CoderLambert/news-aggregator/blob/878b69081f8d5b3ae965bcf1c855390b059caa33/backend/api/models.py#L28)、[`models.py:151`](https://github.com/CoderLambert/news-aggregator/blob/878b69081f8d5b3ae965bcf1c855390b059caa33/backend/api/models.py#L151)、[`models.py:197`](https://github.com/CoderLambert/news-aggregator/blob/878b69081f8d5b3ae965bcf1c855390b059caa33/backend/api/models.py#L197)、[`models.py:306`](https://github.com/CoderLambert/news-aggregator/blob/878b69081f8d5b3ae965bcf1c855390b059caa33/backend/api/models.py#L306)、[`models.py:353`](https://github.com/CoderLambert/news-aggregator/blob/878b69081f8d5b3ae965bcf1c855390b059caa33/backend/api/models.py#L353)、[`models.py:634`](https://github.com/CoderLambert/news-aggregator/blob/878b69081f8d5b3ae965bcf1c855390b059caa33/backend/api/models.py#L634)、[`models.py:1091`](https://github.com/CoderLambert/news-aggregator/blob/878b69081f8d5b3ae965bcf1c855390b059caa33/backend/api/models.py#L1091)、[`models.py:1161`](https://github.com/CoderLambert/news-aggregator/blob/878b69081f8d5b3ae965bcf1c855390b059caa33/backend/api/models.py#L1161)、[`smart_channel_models.py:8`](https://github.com/CoderLambert/news-aggregator/blob/878b69081f8d5b3ae965bcf1c855390b059caa33/backend/api/smart_channel_models.py#L8)。

当前成员表只约束 `(group, subscription)` 唯一，跨用户关系主要在服务层校验。新入口不得绕过 [`channel_views.py:89`](https://github.com/CoderLambert/news-aggregator/blob/878b69081f8d5b3ae965bcf1c855390b059caa33/backend/api/channel_views.py#L89) 与 [`channel_views.py:143`](https://github.com/CoderLambert/news-aggregator/blob/878b69081f8d5b3ae965bcf1c855390b059caa33/backend/api/channel_views.py#L143) 的归属语义。

## 阅读记录不能误判为已读开关

`ReadingDay` 是持久化记录，不是浏览器临时状态。前端在文章详情可见 3 秒后上报，后端按用户、文章、日期幂等创建；统计 API 返回今日/累计/连续天数，并允许用户清除统计。首页热门排行也依赖该表。

证据：[`smart_channel_models.py:83`](https://github.com/CoderLambert/news-aggregator/blob/878b69081f8d5b3ae965bcf1c855390b059caa33/backend/api/smart_channel_models.py#L83)、[`ReadingTracker.tsx:17`](https://github.com/CoderLambert/news-aggregator/blob/878b69081f8d5b3ae965bcf1c855390b059caa33/frontend/src/components/workspace/ReadingTracker.tsx#L17)、[`smart_channel_views.py:285`](https://github.com/CoderLambert/news-aggregator/blob/878b69081f8d5b3ae965bcf1c855390b059caa33/backend/api/smart_channel_views.py#L285)。

在审计源码中未发现独立可设的 read/unread 模型/API。新增该能力时需要明确默认未读、幂等标记、取消已读、用户隔离和订阅取消后的保留语义；不能从按日遥测擅自批量推导历史已读，也不能把“标为未读”实现为删除阅读统计。

## 身份、来源政策与可见性风险

1. `News.url` 全局唯一，而 `News.source` 为单值。相同 URL 出现在多个 Feed 时，必须先验证身份和政策是否兼容，再附加映射；关联权不授予正文主写权，历史 provenance 不因附加映射改写。不能以 Feed 创建时间、名称、内容长度或引擎 ID 决定覆盖权；无法确定时拒收该冲突并留下可审核记录，暂停依赖该来源的迁移验收。
2. 来源名称唯一不是 Feed 身份。同名新 Feed 不能命中旧 `Source` 后静默改写其订阅对象。旧发布者 `upstream_id` 与 Miniflux entry ID 命名空间不同；引擎重建时 ID 也不能当作稳定发布者身份。
3. 现有文章 URL 规范化要求文章路径、最大 500 字符，保留业务 query 编码/顺序并去除部分跟踪参数；不能直接用于 Feed URL 规范化，也不能新增猜测性 canonical 合并。超限、URL 变更与已有唯一 URL 冲突需要明确拒收结果。证据：[`article_identity.py:13`](https://github.com/CoderLambert/news-aggregator/blob/878b69081f8d5b3ae965bcf1c855390b059caa33/backend/api/services/article_identity.py#L13)。
4. 当前 `channel_filter`、地区和分类成员资格依赖旧政策 key 和 `NewsSourceItem`。新 Feed 绑定必须先覆盖这些关系查询，历史成员继续有效。证据：[`channel_articles.py:6`](https://github.com/CoderLambert/news-aggregator/blob/878b69081f8d5b3ae965bcf1c855390b059caa33/backend/api/services/channel_articles.py#L6)。
5. 现有列表默认从全部 `News` 查询，个人订阅范围只是筛选；详情也直接查询全部文章。因此新个人 Feed 若只增加订阅关系而不加发布可见性，会进入全站首页/详情/热门排行等路径。需统一校验列表、详情、全文搜索、向量结果、收藏、聊天、研究、TTS、阅读统计和热门排行；编辑发布与个人订阅分别授权。证据：[`views.py:174`](https://github.com/CoderLambert/news-aggregator/blob/878b69081f8d5b3ae965bcf1c855390b059caa33/backend/api/views.py#L174)、[`views.py:523`](https://github.com/CoderLambert/news-aggregator/blob/878b69081f8d5b3ae965bcf1c855390b059caa33/backend/api/views.py#L523)、[`smart_channel_views.py:314`](https://github.com/CoderLambert/news-aggregator/blob/878b69081f8d5b3ae965bcf1c855390b059caa33/backend/api/smart_channel_views.py#L314)。
6. 当前 `api.view_article_body` 权限与旧抓取授权关联。新合同必须区分读者访问权和服务器采集政策，不能以个人权限覆盖发布者限制。证据：[`body_access.py:5`](https://github.com/CoderLambert/news-aggregator/blob/878b69081f8d5b3ae965bcf1c855390b059caa33/backend/api/services/body_access.py#L5)。共享 Feed 的采集模式按用户确认由管理员统一管理，普通订阅者不能修改其他引用者共享的物理采集配置。

## 正文状态、首次访问与内容持久化

当前 `full_content_state` 只有 `missing/legacy/complete`。Python helper、SQL 可用性标记和筛选均只接受 `legacy/complete`；不能仅增加一个数据库枚举，就宣称 `available` 已被所有阅读路径支持。必须统一返回已授权内容、revision、hash、可读性和完整性，并保持旧 `complete` 的证据要求。证据：[`models.py:121`](https://github.com/CoderLambert/news-aggregator/blob/878b69081f8d5b3ae965bcf1c855390b059caa33/backend/api/models.py#L121)、[`full_content_status.py:85`](https://github.com/CoderLambert/news-aggregator/blob/878b69081f8d5b3ae965bcf1c855390b059caa33/backend/api/services/full_content_status.py#L85)、[`full_content_status.py:450`](https://github.com/CoderLambert/news-aggregator/blob/878b69081f8d5b3ae965bcf1c855390b059caa33/backend/api/services/full_content_status.py#L450)。

已有正文提交使用 URL/revision 和可选 lease 的 CAS，但依赖旧 `FullContentCandidate` 与站点校验器。其相同文本但 provenance 改变的路径仍会增加 revision；正文变化会清旧兼容译文及推荐问题。新通用接收层必须明确定义相同规范 hash 的 no-op、空/退化产物保护、候选待审核、来源写入权和版本并发，不直接把 Miniflux HTML 填成旧 complete candidate。证据：[`full_content_status.py:246`](https://github.com/CoderLambert/news-aggregator/blob/878b69081f8d5b3ae965bcf1c855390b059caa33/backend/api/services/full_content_status.py#L246)、[`full_content_status.py:312`](https://github.com/CoderLambert/news-aggregator/blob/878b69081f8d5b3ae965bcf1c855390b059caa33/backend/api/services/full_content_status.py#L312)。

旧 ingestion 会要求已知政策、域名、发布者身份，并受结构化正文开关/来源名单控制；还可能自动排入全文任务。新 Feed 不能直接复用它作为完整接入合同。证据：[`news_ingestion.py:29`](https://github.com/CoderLambert/news-aggregator/blob/878b69081f8d5b3ae965bcf1c855390b059caa33/backend/api/services/news_ingestion.py#L29)、[`news_ingestion.py:178`](https://github.com/CoderLambert/news-aggregator/blob/878b69081f8d5b3ae965bcf1c855390b059caa33/backend/api/services/news_ingestion.py#L178)。

详情 GET 本身使用读取视图，但前端 `useFullArticle` 对无正文的 pending 文章首次进入时调用旧 POST；对已有任务也会通过 POST 提升优先级。故只断言 GET 无副作用不能满足首访验收。必须使用浏览器网络证据验证首次打开、列表、悬停、分组切换和搜索均不会触发旧正文任务。证据：[`useFullArticle.ts:258`](https://github.com/CoderLambert/news-aggregator/blob/878b69081f8d5b3ae965bcf1c855390b059caa33/frontend/src/hooks/useFullArticle.ts#L258)、[`views.py:528`](https://github.com/CoderLambert/news-aggregator/blob/878b69081f8d5b3ae965bcf1c855390b059caa33/backend/api/views.py#L528)。

前端 Markdown 路径会调用 `repairExplodedCodeBlock`，新引擎内容必须避开该修复，验收代码复制与原取得代码一致。证据：[`MarkdownContent.tsx:198`](https://github.com/CoderLambert/news-aggregator/blob/878b69081f8d5b3ae965bcf1c855390b059caa33/frontend/src/components/news-detail/MarkdownContent.tsx#L198)、[`MarkdownContent.tsx:281`](https://github.com/CoderLambert/news-aggregator/blob/878b69081f8d5b3ae965bcf1c855390b059caa33/frontend/src/components/news-detail/MarkdownContent.tsx#L281)。

## 翻译、研究与搜索兼容

共享翻译使用正文精确 UTF-8 SHA-256 和 `(news, hash, language, version)` 命中，发布时再次检查当前正文 hash；私人翻译另按用户和连接隔离。新转换仅作用于新引擎产物，不得为统一格式批量重写历史正文，导致历史译文失去匹配。并发完成的旧版本翻译不能发布到新正文；相同 hash 不清缓存。证据：[`shared_translations.py:43`](https://github.com/CoderLambert/news-aggregator/blob/878b69081f8d5b3ae965bcf1c855390b059caa33/backend/api/services/shared_translations.py#L43)、[`shared_translations.py:164`](https://github.com/CoderLambert/news-aggregator/blob/878b69081f8d5b3ae965bcf1c855390b059caa33/backend/api/services/shared_translations.py#L164)、[`serializers.py:232`](https://github.com/CoderLambert/news-aggregator/blob/878b69081f8d5b3ae965bcf1c855390b059caa33/backend/api/serializers.py#L232)。

聊天会调用 `ensure_full_content`；研究 `fetch_article` 会调用 `request_full_content` 并短暂等待旧 Worker。统一读取 helper 的迁移必须覆盖这些间接入口和推荐问题。按用户确认，研究的文章工具只读本地已保存正文，不能请求发布者或隐式提交引擎补抓；联网搜索能力继续保留。联网搜索目前导入 `article_fetcher.execution`，删旧目录前需抽离其通用取消/安全依赖。证据：[`views.py:840`](https://github.com/CoderLambert/news-aggregator/blob/878b69081f8d5b3ae965bcf1c855390b059caa33/backend/api/views.py#L840)、[`views.py:1086`](https://github.com/CoderLambert/news-aggregator/blob/878b69081f8d5b3ae965bcf1c855390b059caa33/backend/api/views.py#L1086)、[`research/tools.py:692`](https://github.com/CoderLambert/news-aggregator/blob/878b69081f8d5b3ae965bcf1c855390b059caa33/backend/api/services/research/tools.py#L692)、[`research/tools.py:729`](https://github.com/CoderLambert/news-aggregator/blob/878b69081f8d5b3ae965bcf1c855390b059caa33/backend/api/services/research/tools.py#L729)。

现有向量索引实际使用标题和 `News.content` 前 500 字，hash 包含模型及 schema 版本。它不是全文索引；保留该合同，不能把所有正文 revision 更新都当成 embedding 重建条件，也不能让 `rss-sync` 导入模型执行。全文关键词检索另读已授权的 `full_content`，需支持 `available` 并保留分页/频率限制。证据：[`search_index.py:37`](https://github.com/CoderLambert/news-aggregator/blob/878b69081f8d5b3ae965bcf1c855390b059caa33/backend/api/services/search_index.py#L37)、[`search_index.py:223`](https://github.com/CoderLambert/news-aggregator/blob/878b69081f8d5b3ae965bcf1c855390b059caa33/backend/api/services/search_index.py#L223)、[`views.py:174`](https://github.com/CoderLambert/news-aggregator/blob/878b69081f8d5b3ae965bcf1c855390b059caa33/backend/api/views.py#L174)、[`views.py:209`](https://github.com/CoderLambert/news-aggregator/blob/878b69081f8d5b3ae965bcf1c855390b059caa33/backend/api/views.py#L209)。

## 发现功能与来源覆盖差异

当前添加频道使用 URL 输入、已登记频道匹配和未知来源接入申请，不是关键词目录搜索或任意 Feed 自动接入。新目录检索、Miniflux URL Discovery、订阅预览和 OPML 应分别验收，复用现有个人分组及人工覆盖。证据：[`AddChannelDialog.tsx:15`](https://github.com/CoderLambert/news-aggregator/blob/878b69081f8d5b3ae965bcf1c855390b059caa33/frontend/src/components/workspace/AddChannelDialog.tsx#L15)。

静态政策包含 DEV.to API、HN 讨论、GitHub README、arXiv 摘要、受限来源等不同对象；相同来源名称不意味着选题和条目身份相同。最新迁移还包含 HTML-only 医疗来源及监管数据 Feed。逐来源清单必须包含原规则、新 Feed/已有 RSSHub 路由、身份变更、内容类型、策略和实测状态；没有可用替代路径时保留历史并标明停用/阻塞，不恢复自研 Spider。证据：[`source_policy.py:33`](https://github.com/CoderLambert/news-aggregator/blob/878b69081f8d5b3ae965bcf1c855390b059caa33/backend/api/services/source_policy.py#L33)、[`0051_seed_domestic_medical_sources.py:8`](https://github.com/CoderLambert/news-aggregator/blob/878b69081f8d5b3ae965bcf1c855390b059caa33/backend/api/migrations/0051_seed_domestic_medical_sources.py#L8)。

## 独立验收边界与阻塞条件

建议按以下功能边界建立任务，并由 `TASKS.md` 给出唯一任务 ID 和最终依赖 DAG：

1. 来源身份、共享物理 Feed 和可见性模型：保留旧键；并发创建同 Feed 幂等；同名源与 URL 冲突明确拒收；共享模式仅管理员修改。
2. 通用正文接收与版本合同：安全 HTML 转 Markdown、可读性/完整性、hash no-op、CAS、防退化和候选审核分别有可复现案例。
3. 可靠同步：增量导入、内容全量分批对账、检查点事务、进程崩溃恢复和引擎重建映射分别验收，不以最大 entry ID 代替全部状态。
4. 用户订阅与状态：复用个人关系；新 read/unread 与原 ReadingDay 独立；取消最后引用不误删本地文章/用户历史。
5. 读取与 AI 兼容：所有消费者使用统一访问快照；研究本地只读、联网搜索保留；首访不触发旧抓取；译文版本并发保护。
6. 来源迁移：逐来源证明替代覆盖、政策和身份映射，单来源单采集所有者；不支持项明确记录。
7. 旧系统退出：前置依赖是新系统真实验收及回滚演练通过；先清通用工具依赖，再删执行路径/服务/依赖，不删除保留的业务数据与历史迁移。

共享数据库模型/迁移与读取核心 helper 的任务应串行合并；在接口合同冻结后，纯转换器、SDK 包装及隔离运维验证才具备安全并行条件。现有迁移测试已提供空库/历史数据保留的模式，可扩展到最新 `0051` 基线，并覆盖本文所有保留关系；这里未执行这些测试。参考：[`test_ingestion_migration.py:10`](https://github.com/CoderLambert/news-aggregator/blob/878b69081f8d5b3ae965bcf1c855390b059caa33/backend/api/tests/test_ingestion_migration.py#L10)、[`test_channel_migration.py:9`](https://github.com/CoderLambert/news-aggregator/blob/878b69081f8d5b3ae965bcf1c855390b059caa33/backend/api/tests/test_channel_migration.py#L9)。

## 未取得的证据不能标记通过

| 检查 | 本次状态 | 放行所需证据 |
|---|---|---|
| 源码模型/调用链与固定 SHA 对应 | 已核查 | 本文固定 SHA 链接，可复核 |
| 实际业务库迁移版本、记录数、正文状态分布、孤立关系 | NOT_RUN | 后续获准环境的只读盘点，脱敏计数与一致性报告 |
| 生产来源开关、已运行服务、线上真实配置 | NOT_RUN | 独立运维核验；不能用 Compose/默认值推断 |
| Miniflux/PostgreSQL/RSSHub 运行、目标来源覆盖 | NOT_RUN | 隔离实际运行验收及可追溯输出 |
| 最新基线升级、用户关系/译文 hash 保留及回滚 | NOT_RUN | 临时测试库和经批准快照演练；前后对账 |
| 功能、迁移、浏览器、部署测试 | NOT_RUN | 各开发任务及批次的真实测试报告 |

缺少上述真实测试条件时，仅相应实际运行门禁标记 `BLOCKED`，不能写 `PASS`；按接口/fixture 的独立开发继续。规划 PR 可审核合同的完整性，但不能代替任何生产授权或开发完成验收。
