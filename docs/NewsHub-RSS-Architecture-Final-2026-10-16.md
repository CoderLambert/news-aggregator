# NewsHub RSS 接入与正文管线重构：审核定稿

**版本：1.0｜日期：2026-10-16｜性质：架构与实施合同，不是已部署证明**

- 项目：`CoderLambert/news-aggregator`。
- 本次核验的远端基线：`main@878b69081f8d5b3ae965bcf1c855390b059caa33`。
- 目标：取消 NewsHub 自研的来源爬虫、Feed 解析和网页正文提取；使用成熟 RSS 服务完成采集及自动正文获取；保留现有阅读和 AI 产品，新增方便的订阅搜索、发现和添加。
- 本文替代《NewsHub-RSS-正文预获取-验证与实施计划-2026-10-16》与《NewsHub-Miniflux-RSSHub-迁移实施方案-2026-10-16》中冲突的设计。旧文档保留为历史记录，不再作为新开发入口。
- 已完成：读取旧方案、核验远端代码、核对上游文档及关键实现。未完成：真实部署、目标来源抽样、迁移、性能测试、生产验收。不得把本文的目标值写成已经达到的指标。

## 1. 最终决策

**采用 Miniflux + PostgreSQL 作为唯一常规 RSS 采集引擎；RSSHub 以可选标准服务提供已有路由；NewsHub 只实现目录搜索、用户订阅、API 同步、内容适配及阅读/AI。**

这不是在旧爬虫前面再加一层代理。迁移完成后，旧 Scrapy、Feed Parser、网页下载/正文提取 Provider 和全文 Worker 必须退出运行与生产依赖。

### 1.1 职责分配

| 职责 | 唯一归属 | NewsHub 不再做的事 |
|---|---|---|
| RSS/Atom/JSON Feed 获取、解析、条件请求、定时更新 | Miniflux | 下载 Feed XML、调用 feedparser、按站点实现 Spider |
| 原网页正文提取 | Miniflux 上游实现 | 自写 Readability、CSS/XPath 提取器、Jina 多级回退 |
| 非原生 RSS 网站转 Feed | RSSHub 已维护路由 | 自写 RSSHub 路由、维护浏览器集群或登录抓取脚本 |
| 关键词查找订阅源 | NewsHub 轻量目录模块 | 全网搜索爬虫、复制 Folo 托管搜索数据库 |
| 根据网址发现 Feed | Miniflux Discovery | 自写网页链接/Feed 探测器 |
| 用户订阅、分组、收藏、已读、访问权限 | NewsHub | 把用户状态混进共享采集账号 |
| 引擎结果同步、来源映射、内容转换 | NewsHub 单一同步进程 | 重新调度发布者抓取、再建通用任务平台 |
| 阅读、翻译、问答、研究、TTS、语义检索 | 现有 NewsHub | 为更换 RSS 底层而推翻产品界面 |

Miniflux 已有上述 Feed 与正文能力和正式 API；这些能力并不包含 Folo 式全平台关键词目录。[U01][U02][U03]

### 1.2 本轮不做

不引入 Celery、Kafka、Redis、Elasticsearch、Meilisearch、浏览器集群、新的 AI 搜索模型、另一套 RSS 服务或第二套用户系统。不 fork Miniflux/Folo/RSSHub，不同时部署 FreshRSS/Morss，不回到 `feedparser + Trafilatura + 自建调度`。

不在本轮迁移 Django 业务数据库到 PostgreSQL，不重构现有模型网关/向量索引，不自动对全部新文章翻译、嵌入或运行研究任务。

“取消本地爬虫”指取消 **NewsHub 自研采集代码与进程**，不是说第三方软件不再访问来源网站，也不是承诺所有采集计算都移到云端或资源消耗归零。

## 2. 本次审核结论及旧方案修正

### 2.1 已核实的项目事实

1. 当前 `AddChannelDialog.tsx` 输入类型是 URL，先匹配已登记频道，未知来源进入接入申请。这不是直接订阅任意正常公开 Feed，也没有完整关键词目录搜索。[C02]
2. 当前 `news_ingestion.py` 的结构化正文入库受开关和来源名单控制，并有自己的自动正文任务入口。迁移后不能只是换 Provider，仍让该入口继续调度旧爬虫。[C03]
3. 当前生产 Compose 有 `crawler`、`full-content` 与 `indexer`；`app` 使用 host 网络。新方案要删除前两个旧角色，但不能误删向量索引或顺带破坏现有 Nginx/BYOK 网络连接。[C04]
4. 当前依赖包含 Scrapy、scrapy-playwright、feedparser，也包含 sentence-transformers 与 ChromaDB。更换 RSS 不会自动消除后两者的资源占用。[C05]
5. 当前 Markdown 渲染路径存在 `repairExplodedCodeBlock` 一类历史代码文本修复。新引擎返回的代码块不能继续被该逻辑自动改写。[C06]

以上是代码事实，不是线上实际镜像、来源开关或成功率的证明。

### 2.2 必须修正的设计问题

| 旧表述/风险 | 审核后的确定处理 |
|---|---|
| 增加 Miniflux，但保留自研 RSS 和全文路径作为长期备用 | 不接受；按来源切换单一所有者，最终移除旧运行路径 |
| Miniflux 可以直接提供 Folo 的关键词搜索 | 不成立；目录元数据检索与 URL Discovery 分开 |
| `crawler=true` 或非空 `content` 就表示获取了完整原文 | 不成立；可读内容和完整性分开，正常展示已获取内容，不虚构全文成功 |
| 仅按新 entry ID 或最近 48–72 小时同步 | 不足；新增同步加保留期内完整、分批、可续跑的内容对账 |
| Webhook 是可靠唯一入口 | 不成立；Miniflux 文档说明不自动重投，V1 不启用 Webhook，直接用可靠 API 同步 |
| `FETCHER_ALLOW_PRIVATE_NETWORKS=0` 同时抓 `http://rsshub:1200` | 配置矛盾；使用受保护的公共 HTTPS Feed 网关，不全局放开私网请求 |
| 所有用户共用引擎，因此已读/收藏也共用 | 不接受；引擎仅采集，用户状态只在 NewsHub |
| 用户新增公开 Feed 就自动出现在全站首页和目录 | 不接受；自己的订阅与站点编辑发布是不同动作 |
| 更换成 Go 服务必然大幅降低内存 | 无实测不能成立；计入 PostgreSQL、RSSHub、同步进程后比较最终单栈 |
| 删 `article_fetcher/` 时连其他模块共用的安全工具一起删 | 先清依赖；通用安全能力独立保留，旧来源提取逻辑删除 |

Miniflux 2.3.3 的处理代码在新条目或强制刷新时执行抓取；抓取失败保留 Feed 内容。它没有在普通内容响应中提供可直接依赖的“这篇已经完整提取成功”证明。[U04] 内容更新与 `changed_at` 的覆盖也不能仅按字段名称猜测。[U05]

**审核判断：该架构可按现有接口实施；无需开发新的新闻爬虫。真正需要实现的是可控的系统集成。生产放行仍取决于第 13 节的明确门槛。**

## 3. 目标架构：逻辑分层，不拆成一堆微服务

```text
浏览器：NewsHub 现有阅读界面 + 新「发现/添加订阅」
                         |
                     Django API
       ┌─────────────────┼──────────────────────┐
       |                 |                      |
   目录元数据检索     用户订阅/分组/权限       本地文章读取与 AI
       |                 |                      |
   FeedDirectory     订阅意图/来源映射        NewsHub SQLite
                         |                      ^
                         v                      |
                rss-sync（单一轻量进程）─────────┘
                 只调用引擎 API、同步/转换/入库
                         |
                     Miniflux ── PostgreSQL
                         |
             官方 RSS / Atom / JSON Feed
                         |
             可选：受保护的 RSSHub Feed
                         |
              RSSHub 已有路由访问对应来源
```

### 3.1 进程与代码边界

NewsHub 内部按模块拆分，仍在一个仓库发布：

```text
backend/api/rss/
  engine.py          # 包装官方 Miniflux Python SDK；固定服务地址
  discovery.py       # 关键词目录、网址发现、路由参数表单数据
  subscriptions.py   # 用户订阅、引用计数、幂等操作
  sync.py            # API 增量、对账、检查点、控制请求
  content.py         # 已获得 HTML 的清理和 Markdown 转换
  access.py          # 阅读可见性与来源政策

backend/api/management/commands/rss_sync_worker.py
frontend/src/features/rss/   # 发现、预览、订阅、OPML；复用现有基础组件
ops/rss/                    # 版本锁定、Compose 配置、健康/备份说明
```

这些是建议的代码组织名称，不是已创建的文件。通用账户、翻译、目录显示组件继续复用，不复制到新模块。

`rss-sync` 可以处理目录快照更新、少量引擎控制请求和内容对账，但**不能请求新闻发布者 HTML/Feed**，不能导入 Scrapy、feedparser、网页正文提取器、Torch 或 embedding 模型。Miniflux SDK 已有 Python 实现，优先包装而非重写客户端。[U01]

### 3.2 数据所有权

| 数据 | 事实来源 | 同步方向 |
|---|---|---|
| 个人订阅、分组、已读、收藏 | NewsHub | 不映射到共享 Miniflux 用户的阅读状态 |
| 希望存在/启停的采集订阅 | NewsHub 的来源绑定 | NewsHub → Miniflux |
| Feed 解析、拉取时间、引擎错误、当前条目内容 | Miniflux | Miniflux → NewsHub |
| 已接受的文章、正文版本、译文、研究历史 | NewsHub | 本地保存，不因引擎清理而删除 |
| 候选来源目录 | 固定来源快照 + 站点已发布目录 | 更新元信息，不批量注册采集 |

Miniflux 使用专用、非管理员采集账号；管理账号与 API Token 分离。浏览器不接触 Miniflux Token，也不直接访问其数据库/API。

同一规范 Feed URL 在同一采集账号下只有一个物理订阅。多用户只是引用它；这不等于承诺“同一文章出现在两个不同 Feed 时引擎绝不重复请求”。

## 4. RSS 渠道接入与自动正文策略

### 4.1 三种明确模式

| 模式 | Miniflux 设置 | 默认适用对象 | 展示规则 |
|---|---|---|---|
| Feed 内容直读 | `crawler=false` | 已确认原生正文 Feed、已提供内容的 RSSHub 路由 | 展示服务已返回的内容，不再次抓原文 |
| 自动尝试原文 | `crawler=true` | 只有摘要的普通公开文章源，且政策允许 | 引擎在采集时提取；失败仍显示 Feed 已有内容 |
| 仅摘要/外链 | `crawler=false` | 付费/登录/既有来源政策受限、视频/产品等 | 明确提示来源限制，不尝试补抓 |

普通新公开文章 Feed 在安全检查与来源政策允许时采用「自动尝试原文」，用户可关闭；目录中已验证自带正文的来源采用直读；已知受限来源不允许用户打开原文抓取。用户不需要填写 CSS/XPath/脚本。

这里区分两个权限：**服务器是否允许访问来源**，以及**NewsHub 是否允许向当前读者展示/在全站发布内容**。一个内部用户权限不能代替发布者规则。

### 4.2 获取时机

订阅创建和 Miniflux 的正常周期同步负责发现文章与自动正文提取。`rss-sync` 导入其结果后，第一次打开详情即读取 NewsHub 本地内容。

`GET /api/news/{id}/`、列表浏览、鼠标悬停、搜索和切换分组都不能触发抓取。删除 `useFullArticle` 的首访自动抓原文行为。对新来源第一轮尚未结束的情况展示“首次同步中”，而不是把点击阅读当作采集触发器。

需要显式重试时，用户按钮只提交一个有配额、可合并的 Miniflux API 操作，由 `rss-sync` 执行；不恢复旧抓取 Worker。V1 不做自动循环逐篇修复，不定时强制刷新所有 Feed。Miniflux 的自动抓取不是无限逐篇重试系统。[U04]

### 4.3 不同内容类型

- Hacker News 是聚合来源，原文在不同网站；保存文章 URL 与讨论链接，视频不称为文章全文。
- GitHub Trending 通过已有 RSSHub 路由接入，仓库简介或 README 按实际内容类型展示，不包装成完整新闻。
- arXiv 的摘要不能标成论文全文；本轮不增加 PDF 抓取。
- 对混合外链 Feed，已知禁止采集的目标应在引擎准入/现有链接过滤中处理。引擎无法表达“保留这条摘要但只禁止其正文”时，不能悄悄写新的 per-item 抓取器；该 Feed 使用 RSS 内容模式，或明确排除受限条目并记录覆盖差异。
- 只接 Miniflux/RSSHub 已支持、在实际出口可用的路径。不支持的来源保留历史记录与原因，不用自研 Spider 偷偷兜底。

### 4.4 首次接入的覆盖差异必须说明

原来的 DEV.to API 按标签/热度选题，与一个通用 DEV.to RSS 不一定等价。原 Hacker News API 的条目数量、排名、稳定 ID，也不一定被替换 Feed 完全保留。

迁移清单必须逐来源列出：原选择规则 → 新 Feed/路由 → 文章对象类型 → 变化或缺失。不能只看来源名称相同就宣布无损迁移。

## 5. 正文展示：不要再把「完整性未确认」变成「只能看一行摘要」

### 5.1 内容合同

Miniflux `entry.content` 返回的是 HTML，但它可能是 Feed 全文、Feed 摘要，或提取后的网页正文。[U01][U04]

因此采用两个独立概念：

- `has_readable_content`：存在经安全处理、当前用户可访问的内容。
- `content_completeness`：`unknown`、`summary`、`verified`。

**非空安全内容可以渲染；只有证据充分才声称是完整原文。** 未确认不代表清空，也不代表必须等待另一套全文任务。

实现上保留现有 Markdown 缓存字段与正文 revision，给 `full_content_state` 增加 `available`。旧 `complete` 的含义不放宽；`legacy` 非空仍可读，但不自动升级为经过新方案验证。新增派生 API 字段 `has_readable_content` 和 `content_completeness`，统一改造读取 helper。不要让旧 `has_full_content` 布尔值继续同时表达“可读”和“已确认全文”。

`News.content` 继续是列表摘要；Miniflux 返回的全部可接受内容写入正文缓存，不以列表摘要长度截断。`available` 记录也在详情页完整呈现已取得内容；页面标签使用“已获取内容”，不是“正文全部验证通过”。

### 5.2 格式处理指定实现

```text
Miniflux JSON（绑定已知 Feed/entry 身份）
  → nh3 清理 HTML / 限定标签、属性和 URL scheme
  → markdownify 转换已有内容
  → 有界安全检查 + 规范内容哈希
  → 现有 Markdown 缓存与版本写入
  → ReactMarkdown / remark-gfm / Shiki / TOC
```

nh3 与 markdownify 均使用固定、经测试的上游版本；前者负责 HTML 清理，后者只做格式转换，不访问网站、不识别原网页文章主体。[U09][U10]

转换配置必须保留标题、段落、列表、链接、图片、引用、表格、代码块；相对资源链接以引擎条目 URL 解析。禁止用正则剥 HTML，禁止对新内容执行历史代码“重排/修复”，代码复制内容与原取得代码一致。[C06]

对图片采用安全 HTTPS URL、懒加载与失败占位；防盗链/HTTP-only 图片不能保证显示。V1 不新增图片下载器/截图浏览器。对不支持的 iframe、脚本和复杂交互提供来源链接，不执行原站代码。

前端不能将外部 HTML 直接传给 `dangerouslySetInnerHTML`。现有受控代码高亮产物不是开放 Feed HTML 的通道。标题/目录描述也按普通文本或受控渲染处理。

### 5.3 防内容退化，不再维护站点提取算法

1. 相同内容哈希：不重复更新 revision，不清译文，不触发重复 embedding。
2. 空内容、明确错误页、来源策略拒绝：不覆盖已保存正文。
3. 旧完整内容收到明确摘要：保留旧正文与旧译文，记录这次上游产物退化。
4. 明显大幅缩短但不能判断是合法编辑还是摘要回退：作为待确认变化，不自动覆盖旧正文；不能据“更长”就自动判定更完整。
5. 可接受的新版本变化：原子更新正文 revision，相关译文/索引按现有版本规则失效，不误删用户收藏与对话。

只保留跨来源通用的数据保护与安全校验，不重新积累一套按域名编写的 HTML 提取规则。每篇文章安全接收的长度上限必须显式配置；超限要报告，不截断后标完整。

### 5.4 AI 与 TTS 的上下文

翻译、问答、研究、TTS 通过一个统一的读取 helper 获得“当前用户可访问的已保存内容 + revision + 完整性”。`available` 内容可参与处理，但提示模型不能假定已覆盖整篇文章；只有摘要时标识摘要。新 Feed 接入不自动产生模型付费调用。

## 6. Folo 式订阅发现与添加

### 6.1 输入分类与后端路线

| 用户输入 | 路线 | 是否访问文章网站 |
|---|---|---|
| `github`、`React`、`人工智能` | 搜索来源目录元数据 | 不访问 |
| `github.blog` 等网站域名 | 规范为 HTTPS，交给 Miniflux Discovery | 由 Miniflux 探测 |
| 完整 Feed URL | 由 Miniflux 验证与创建；不自己解析 XML | 由 Miniflux 获取 |
| `rsshub://...` | 已发布路由模板校验、补参数、映射系统 Feed 网关 | 由 RSSHub/Miniflux 完成 |
| OPML 文件 | 使用 listparser 读取上传的清单，预览后逐项加入正常订阅流程 | 仅已确认项目才由引擎访问 |

listparser 在这里解析上传的订阅清单，不代替 Miniflux 解析新闻 Feed；传入文件内容而非让它抓远端 URL。[U11]

### 6.2 目录来源与规模边界

目录由以下三种数据组成：

1. NewsHub 已发布的公共来源目录。
2. 固定版本的开源 Feed/OPML 种子目录，首个接入 `plenaryapp/awesome-rss-feeds`；逐条保留来源出处，不能据收录就标健康。[U07]
3. RSSHub 官方路由 JSON 的 namespace、routes、名称、说明、参数及能力要求。模板与实例分别索引；缺账号参数的模板展示“填写参数”，不能当成已经可订阅的完整 URL。[U08]

用户自己的新增公开 Feed 在本人的订阅/搜索中可见，不自动纳入全站公开推荐。公开目录收录与用户订阅分开。用户关系、订阅数量不是目录导入时虚构的数据。

采用现有 SQLite 的元数据查询与轻量排序：精确 URL/名称、名称前缀、标签/描述匹配、可用状态依次排序。V1 无独立搜索服务，无 LLM 搜索，无向量模型依赖。目录快照按日检查，更新先校验结构再原子替换，失败继续用上个版本。搜索结果不等于实时健康保证，必须显示验证时间。

**不依赖 Folo 私有/未承诺开放的搜索 API。** Folo 客户端的独立 discover 调用说明它有自己的发现服务，不能推导出安装 Miniflux 或读取 routes.json 就得到其全部数据。[U12]

V1 不动态下载/执行 Radar JavaScript；只处理声明式路由元数据。无网页 Feed 且不能从现成目录/模板匹配时明确返回未发现，不启动深度扫描。

### 6.3 前端交互

保留当前首页、文章页和侧边栏风格；新增“发现/添加订阅”完整页面，同时让现有添加按钮打开同一功能。

结果卡片显示名称、简介、语言、分类、官方 Feed/RSSHub 标识、真实来源、验证时间、已订阅状态。已有采集缓存可显示最近文章；没有缓存就不显示虚构截图、订阅数或更新频率。

交互为：**输入 → 查看候选/必要参数 → 选择个人分组 → 订阅**。普通安全的公开 Feed 不再走“申请后等待管理员开发 Spider”的流程。风险来源、私网、凭据型 Feed 与受限路由单独拒绝或解释原因。

订阅状态：`待连接 → 已连接/首次同步中 → 可阅读`；失败为`连接失败`并显示可操作原因。已有共享 Feed 可以立即建立个人关系，新 Feed 不要求浏览器一直等待完整抓取。

键盘验收包括 Enter 提交、Tab 顺序、Escape 关闭、关闭后焦点恢复；移动端列表卡片、输入错误与长 URL 不溢出。一次搜索失败不清除已订阅列表。

### 6.4 OPML

先预览数量、分组、重复与不支持项目，再让用户确认。只导入当前用户选择的项目；每项经过同样的 URL/配额校验。部分失败可重试失败项，成功项不重复注册。导出只包含当前用户的订阅与分组，不直接导出共享 Miniflux 账号的所有 Feed。

V1 的“自己的 RSS”指自选公开、无凭据的 Feed；带 Token、Cookie、Basic Auth 的私人内容源不纳入共享采集账号。本轮不暗中支持再泄露到全站。系统 RSSHub 网关的专用认证不属于用户私人 Feed，此凭据由服务端管理。

## 7. 最小数据模型与接口合同

### 7.1 复用和新增

保留 `News`、`Source`、`NewsSourceItem`、用户订阅/分组和全部 AI/收藏记录。新建的最小状态类别如下，迁移实现应复用现有模型的等价字段，不能重复建设两套来源注册表。

| 状态类别 | 必要字段/约束 |
|---|---|
| `FeedBinding` | 内部稳定 ID、引擎实例标识、采集账号 ID、引擎 feed_id、规范 Feed URL、来源/端点关联、采集模式、目标启停与连接状态、最后错误 |
| `FeedDirectoryEntry` | 名称、URL 或路由模板、语言/标签、来源出处、快照版本、健康检查时间、可见范围 |
| `FeedSyncState` | 新条目检查点、对账上界/页位置、最后成功时间、worker 租约/心跳 |
| `FeedOperation` | 仅注册/启停/显式刷新/显式单篇修复等固定 API 动作，幂等键、目标、状态、有限重试；不保存来源 HTML 或任意代码 |

`FeedOperation` 是 API 控制请求的持久意图，不是一个新的通用爬虫队列。与数据同步共用一个执行进程，不再启动独立任务服务。

来源与 Feed 不强制一对一：旧频道可能含多个 Feed，别名频道也可能指向同一个 Feed。使用关联关系保留旧 Source ID，不通过重新创建 Source 破坏用户分组。初始迁移输出关系清单，冲突人工处理。

### 7.2 身份与去重

上游条目唯一键为 **引擎实例 + 采集账号 + Feed + entry ID**，不得只保存裸整数 ID。实例重建/恢复后必须核对绑定，不能把不同实例相同 ID 当成同一文章。

正文哈希由 NewsHub 对规范内容计算；Miniflux 的条目 `hash` 是身份相关字段，不能作为我们的正文 revision。[U05]

映射优先复用原 `NewsSourceItem`。原文 URL 匹配可以复用旧 News ID，但不能以相似标题合并文章，不能把不同阅读政策/可见范围的内容借全局 URL 去重而扩大展示权限。新来源碰到旧 URL 冲突时，保留映射及实际正文来源，无法安全合并则记录冲突，不覆盖。

Feed URL 规范化只处理 scheme/主机大小写、默认端口、fragment 等不影响资源身份的部分；不随意删业务 query、改大小写路径或假定尾斜线等价。RSSHub 在应用对外存可读别名，在服务器映射真正 Feed URL，不泄漏网关认证信息。

### 7.3 建议 NewsHub 接口

这些是本轮需实现的 NewsHub 接口，不是声称已经存在：

| 接口 | 行为 |
|---|---|
| `GET /api/rss/discovery/?q=...` | 本地目录检索与缓存预览，不触发来源网络 |
| `POST /api/rss/discovery/resolve/` | 登录+CSRF+配额；把网址交给引擎发现 |
| `POST /api/me/rss-subscriptions/` | 幂等保存订阅/注册意图；已连接返回成功，未连接返回 202 和操作状态 |
| `DELETE /api/me/rss-subscriptions/{id}/` | 只取消自己的关系 |
| `GET /api/me/rss-operations/{id}/` | 读取当前用户授权可见的连接进度 |
| `POST /api/me/rss-imports/preview/`、`.../confirm/` | OPML 预览/确认 |
| `GET /api/me/rss-export/` | 当前用户 OPML |
| `POST /api/rss/feeds/{id}/refresh/` | 有权用户显式请求合并后的引擎刷新；限频 |

文章详情和现有分组 API 保持兼容；新增接口聚焦新发现/连接语义，不重复开发另一套分组。

### 7.4 创建、取消与不确定结果

一个短数据库事务保存用户订阅意图及唯一 FeedBinding，然后返回“待连接”。同步进程在事务外调用 Miniflux。网络请求不能占用 SQLite 写事务。

引擎创建调用超时属于结果不明：先通过引擎已有 Feed 列表核对目标，再决定是否重试，不能立即重复创建。一个用户取消但还有其他用户引用或站点编辑固定收录时，不停用共享 Feed。最后一个引用取消后先暂停，不立即删历史数据；取消注册中的订阅也要按最终引用数收敛。

## 8. 同步可靠性：V1 仅采用 API 拉取与对账

Miniflux Webhook 不自动重投，因此本轮不接 Webhook，不开放对应公网回调。一个可靠拉取链足以满足本项目，不额外维护两种投递机制。[U06]

### 8.1 两条循环，由同一进程执行

**新增循环**：每 30 秒检查 Miniflux 新 entry ID，按 ID 升序分页。每页完成本地持久化后才能提交检查点。上游并发事务晚提交、历史日期文章、分页异常由重复窗口及对账补偿；不能把 ID 当作跨事务严格提交日志。

**对账循环**：每日完成一次 Miniflux 保留期内所有条目的有界重查，分批、固定本轮上界、可暂停续跑；不是按发布时间只重看最近两三天。只比较内容哈希，变化才转换/写库。来源特别多时按实际吞吐设定全轮期限并监测，不把定时开始等同于完成。

新 Feed 注册完成后优先导入首批条目；显式单篇修复成功后立即同步该结果。正常新内容同步不能被一次长时间初始注册或全量对账阻塞：同进程区分短读请求与有界控制请求，最多两个在途任务，SQLite 写入保持短事务。

### 8.2 为什么不能只靠 changed_after

本次审阅版本的条目更新代码不能证明每种正文修改都会更新相同的变更时间字段。新 ID 只能发现新记录，也不能发现老文章正文后补成功。因此不得把 `changed_after` 当作唯一保障，不得把旧方案 48–72 小时滑窗当作完整对账。[U05]

### 8.3 失败处理

可重放同一条目不产生重复 News、重复用户关系、重复翻译。暂时失败的操作有限退避；HTTP 429/Retry-After 与引擎限流不能被用户刷新绕过。正文来源请求的调度和重试属于引擎，NewsHub 只控制引擎 API 操作频率。

一页某条因业务校验无法接收时，必须先落盘可追踪的拒绝记录再推进该条进度；数据库故障等临时失败不能记成永久拒绝。断点恢复后继续，禁止“记录一行日志后跳过”。

既有 Miniflux read/star 状态不作为同步确认，不因一位用户已读而影响其他用户。

### 8.4 保留期与无法保证的情况

方案初始设定 Miniflux 保留期 90 天，NewsHub 已保存文章按现有产品策略保留。每日对账必须覆盖引擎仍保留的记录；实际配置在 T00 确认上游清理参数并锁定。

停机超过引擎保留期、来源 Feed 已滚动删除且没有可恢复备份时，不能承诺补回所有文章。RSS 不是历史归档 API。同步积压接近保留期要提前告警，迁移旧正文不依赖引擎重新抓一遍。

## 9. 多用户、可见性与安全

### 9.1 一个采集账号，不是一个共享用户

用户不需要额外注册 Miniflux；个人登录和授权保持 NewsHub 现状。共同订阅同一公开 Feed 复用采集，但分组、已读、收藏、屏蔽及私人 AI 记录仍各自隔离。

用户新增但未发布的来源只出现在自己的订阅范围；站点公共首页/目录仍受发布状态控制。检查不仅覆盖列表，还必须覆盖直接文章 ID、全文、搜索/向量召回、AI 上下文、TTS、导出和缓存键。

正文需记录 `body_source_binding`/来源证据。对全局 URL 相同、来源政策不同的记录，不能让受限来源导入的正文通过另一个公开频道泄漏。无权限时返回允许范围的摘要或 404，不仅仅前端隐藏按钮。

### 9.2 URL 与凭据边界

V1 自动接入无身份凭据的公开 HTTPS Feed。不接受私网/环回/云元数据地址、非 Web 协议、任意代理、关闭 TLS 校验、自定义抓取 Cookie 或 Header。请求重定向与 DNS 解析后的地址安全由引擎及部署防护落实，入口也做格式/配额检查，不能只验证首个 URL 字符串。

第三方返回的标题、HTML、图片 URL、OPML、目录描述都是不可信数据；使用成熟清理器、URL 白名单、响应/文件大小限制和日志脱敏。API 响应采用白名单 DTO，禁止透传 Miniflux Feed 对象中的 password、cookie、内部地址等字段。

设用户新增数/频率、全站来源数、批量导入上限、URL Discovery 并发上限。默认不开放匿名创建。管理页只能调整允许的模式与状态，不暴露任意脚本/规则执行入口。

## 10. 部署方案：一个 Compose 入口，外部引擎隔离

### 10.1 服务集合

| 服务 | 角色 | 常驻与数据 |
|---|---|---|
| `app` | 现有 Django + 已构建前端 | 保持现有业务数据和运行方式 |
| `rss-sync` | 唯一 API 同步/控制进程 | 共享 NewsHub 业务数据库；不加载浏览器或模型 |
| `miniflux` | 第三方 Feed 引擎 | 自己的 PostgreSQL，无 NewsHub DB 访问权限 |
| `rss-db` | Miniflux 专用 PostgreSQL | 独立卷、数据库及最小权限账号 |
| `rsshub` | 可选的标准 Feed 生成服务 | Compose profile；无浏览器/Redis，使用上游支持的有界缓存 |
| `indexer` 等现有 AI 进程 | 原有产品能力 | 本轮保留，不把其成本算成 RSS 优化收益 |

同一仓库、同一个部署入口；RSSHub 通过 profile 开启。默认自带独立 PostgreSQL，**不要求用户先有数据库，也不依赖 Gitea 等其他产品的数据库实例**。

`rss-sync` 使用同仓库的轻量构建 target 与锁定依赖集，不能因为复用镜像就导入/安装不需要的抓取与模型依赖。前端仍随 app 构建，不另起开发服务器。

### 10.2 不顺带改坏原有网络

当前 `app` 使用 host 网络，本轮保留它与既有 Nginx/本地 AI 网关的连接方式。[C04] Miniflux 的 API 仅发布到宿主机环回端口供 app 使用，`rss-sync` 通过受控 Docker 网络访问服务名；PostgreSQL 不发布宿主端口。若最终需要改变 app 网络，必须另列已知依赖与验证，不混入本轮默认变更。

Miniflux API 地址是服务器固定配置，不由用户 URL 决定。NewsHub 用户与公网不能访问其管理 API。

### 10.3 RSSHub 与 SSRF 的实际矛盾及唯一默认解决方案

Miniflux 的 `FETCHER_ALLOW_PRIVATE_NETWORKS=0` 会拒绝私网 Feed；因此直接注册 `http://rsshub:1200/...` 与该安全配置不能同时成立。[U03]

**生产默认：RSSHub 端口只绑定环回，复用现有 Nginx 提供受保护的公共 HTTPS Feed 网关。**

- 网关使用拟新增的专用域名（例如 `rss.lambert.host`，这是计划值，不表示已配置）。
- 公共 DNS 解析到真实公网地址；Miniflux 访问该 HTTPS 地址，不把它映射回 Docker 私网 IP。
- Nginx 只开放已批准路由前缀/只读 Feed 请求，启用专用 Basic Auth 与请求限额；不开放测试、管理、任意 URL 代理等接口。
- Miniflux 使用系统管理的用户名/密码读取网关，密码不写入 Feed URL，不传给浏览器，数据库/备份同样受保护。
- `FETCHER_ALLOW_PRIVATE_NETWORKS` 保持关闭。实际服务器须验证公网回流、DNS、证书及认证。
- 回流不可用时 RSSHub profile 不予生产放行；原生 RSS 可以先正常运行。不得通过全局开启私网访问绕过失败。

这使用现成反向代理配置，不新增自研抓取代理。官方公共 RSSHub 演示实例不是生产依赖。

### 10.4 初始运行参数与版本管理

本次审阅的 Miniflux 发布参考为 2.3.3。T00 锁定经验证的 Miniflux、兼容 PostgreSQL、RSSHub 和转换库版本及真实镜像 digest；不使用 `latest` 自动追新。[U13]

初始小规模部署：Miniflux worker pool 2、Feed 同主机并发限制 1、使用正常 HTTP 缓存；`rss-sync` 每 30 秒处理新增、每天完成一次有界对账。接口响应/源响应大小上限、HTTP 超时、数据库连接池由固定配置管理。Feed 更新节奏由 Miniflux 负责，30 秒是引擎到 NewsHub 的同步节奏，不是强迫每个网站每 30 秒被抓一次。[U03]

源端 429、解析失败、正文缺失应分开显示，不能只展示一个“服务健康”。暂不增加 Prometheus/Grafana 服务；先使用结构化日志、上游健康检查及现有管理页面的少量聚合指标。

### 10.5 备份和维护

提供一个版本化操作入口，至少覆盖安装检查、启动、状态、更新、备份、恢复、切换来源和诊断。脚本不静默删除卷，不把 `down -v` 当成普通停止命令。

备份包括：NewsHub 一致性 SQLite 快照、Miniflux PostgreSQL 原生备份、版本/配置清单、来源映射和受保护的必要凭据。不能只复制活动 SQLite 的主文件而忽略 WAL。恢复时先暂停所有写入与引擎同步，再校验版本和映射，恢复后执行对账。

RSSHub 缓存不是业务真相，可以重建；PG 和 NewsHub 数据必须各自正确恢复。OPML 只备份订阅目录，不备份正文、译文、研究与用户关系。

## 11. 旧系统迁移和彻底退出

### 11.1 迁移步骤

**M0：记录基线。** 导出旧 Source/端点/用户关系/文章数量、正文状态、来源选择规则、部署进程与实际资源；备份，不改生产。

**M1：部署兼容过渡版本。** 新表/字段只增加，不删历史字段；新同步能识别来源所有者 `legacy|miniflux|paused`。默认仍是旧所有者。该版本必须能读取后续新内容状态，作为回滚基点。

**M2：少量来源切换。** 停止该来源旧调度并处理仍在执行的旧任务，再开启对应引擎订阅；检查写入 fencing，旧进程不能晚到覆盖新结果。按来源双栈并存，但同一来源不允许两边同时采集。

**M3：迁移其余可支持来源。** 保留 Source/News ID、文章 URL、个人分组和 AI 数据。新 Feed 与旧 API 范围不等价时明确记录差异并验收。不可迁移的来源转停止更新/历史可读，不留隐藏旧爬虫。

**M4：停运行入口。** 停 `crawler`、`full-content`，清理 crontab/systemd/容器/CLI 的旧自动启动入口，验证重启后不会复活。

**M5：删代码、依赖和配置。** 清理所有旧引用后删除旧抓取代码；更新 CI、镜像和运维文档。历史数据库列可以暂留兼容，不要求同一发布立即 drop 所有旧列，但运行时不得再使用它们调度抓取。

### 11.2 删除/保留矩阵

| 路径或职责 | 最终动作 |
|---|---|
| `crawler/news_crawler/spiders/` 及只为旧采集服务的 pipeline/handler/receipts | 删除 |
| `services/feed_support.py`、旧 FeedState 调度调用 | 删除运行引用；历史迁移按需要冻结保留 |
| `services/article_fetcher/` 中来源 HTTP、网页提取、站点规则、Jina Provider | 删除；共用安全工具先移动到通用模块 |
| `services/full_content_worker.py`、`auto_fetch_full_content`、旧补抓 CLI | 删除旧执行行为；需要的用户重试改成单一引擎 API 操作 |
| Scrapy、scrapy-playwright、feedparser 生产依赖 | 依赖图确认后移除；不存在旧功能所需的浏览器镜像 |
| `news_ingestion.py` 的入库/去重/版本保护 | 提炼成引擎内容提交入口，移除旧来源候选契约与调度副作用 |
| `useFullArticle.ts` 首访自动抓取 | 删除；已有任务状态 UI 换为真实引擎同步/内容可用状态 |
| `AddChannelDialog.tsx` 与 intake 唯一入口 | 改为发现/直接订阅；风险审核不再阻碍普通标准 Feed |
| `NewsDetail`、阅读主题、TOC、翻译/问答/TTS/收藏 | 保留并适配新内容可读性合同 |
| crawler 管理仪表盘 | 改为简洁的订阅健康/连接状态/同步延迟页，不复制另一套爬虫控制台 |

移除仅归属于旧来源获取的请求预算与监控；研究、模型接口等真正仍需使用的限额/安全能力不可误删。最终依赖关系扫描与运行追踪必须证明没有死引用或隐藏抓取回退。

### 11.3 回滚

迁移中按来源暂停新采集并退回 **兼容过渡版本**，保留新数据。已知旧来源可以经批准恢复原调度，新加入且旧系统从未支持的 Feed 只暂停，不能宣称能自动退回旧 Spider。

普通应用回滚不执行数据库恢复、不重放全库、不清正文/译文。灾难恢复是另一个操作，明确恢复点及恢复点之后的数据损失风险，不声称无条件零丢失。

删除旧代码只在全部来源完成替代/明确停止更新、兼容回滚版本已留存后进行。最终版本的正常运行不依赖旧代码。

## 12. 功能任务拆分

固定技术方向不再二选一。T00 只验证集成合同与部署/来源边界，不重新比较五种阅读器，也不在失败后悄悄恢复自研爬虫。

| ID | 独立可验收交付 | 依赖 | 核心验收 |
|---|---|---|---|
| T00 | 引擎/内容/安全合同验证报告、固定版本清单 | 无 | 真实 Feed、自动正文、失败回退、接口字段、SSRF 与 RSSHub 网关验证；区分事实与未通过项 |
| T01 | 可启动且可备份恢复的 Miniflux/PG/RSSHub profile | T00 | 私有 API、网关认证、健康检查、固定镜像、持久化、实际恢复测试 |
| T02 | FeedBinding、官方 SDK 包装、幂等连接与用户订阅 | T00 | 两用户共享物理 Feed 但个人状态不共享；超时不重复创建；取消不误删 |
| T03 | 单一 rss-sync：新增、对账、断点、受控操作 | T01,T02 | 丢响应/重启/旧日期/老正文更新仍最终一致；无来源 HTML/Feed 网络代码 |
| T04 | 安全内容转换、可读性/完整性合同、现有详情与 AI 适配 | T03 | 正文首开可见、代码表格图片正确、无 XSS、unknown 不冒充 full、旧内容不退化 |
| T05 | 关键词目录搜索与结果预览 | T00 | github/React/中文关键词可查真实种子；模板参数清晰；只读搜索不触发抓取 |
| T06 | 网址发现、RSSHub 模板、一键订阅与用户分组 | T02,T05 | 0/1/多 Feed 候选、正常新源无人工申请、异步状态真实、键盘/移动端可用 |
| T07 | OPML 导入导出与完整用户可见性 | T02,T06 | 仅当前用户、部分失败可续、批量限额、直接 URL/AI/搜索无越权 |
| T08 | 按来源迁移、历史兼容与来源覆盖差异清单 | T03,T04,T06,T07 | Source/News ID/译文/收藏/研究保持；每源一个采集所有者 |
| T09 | 旧抓取栈删除、依赖瘦身、部署脚本更新 | T08 | 无旧进程/定时任务/自动抓取引用；重启不复活；兼容版本可回滚 |
| T10 | 全量回归、单栈资源测量、生产发布验收报告 | T09 | 用户实际阅读验收、备份恢复、升级回滚、安全、性能和来源质量报告 |

T01 与 T02 可并行，T05 可以独立开发，不能多个任务无协调修改同一个身份/内容合同。每个任务有单元/契约测试与明确产物；集中在集成节点跑全量，避免每个无关提交重复整套高成本验证。真实浏览器与真实来源结果单独记录，不把 mock 通过算成线上通过。

文档统一放 `docs/features/rss-engine-migration/`：`PLAN.md`、`TASKS.md`、`ACCEPTANCE.md`、`MIGRATION.md`、`OPERATIONS.md` 和按任务编号的证据。本文是 PLAN 的唯一基线，其他文档不能给出另一种采集架构。

## 13. 验收与可交付边界

### 13.1 T00 真实来源样本

每类建议 5–10 篇，保存实际 Feed/文章 URL、日期、来源模式及判断依据，不需要无限扩样：

- 原生全文：Julia Evans、WebKit、V8 等实际返回完整正文的样本。
- 普通摘要来源：至少两个公开技术博客，验证 Miniflux 自动提取。
- DEV.to：追踪截图 `/news/8555` 的实际原文 URL，并补充当前新 Feed 样本；不能把 NewsHub ID 当 Miniflux ID。
- Hacker News：普通文章、GitHub 外链、视频、自帖分别统计。
- GitHub Trending：实际可运行的 RSSHub 路由，检查输出对象而非只看 HTTP 200。
- 既有受限来源：验证不发原文补抓请求，摘要仍可读。

目录、Feed 来源、文章身份、自动正文、前端渲染分别验收，不用一个总成功率掩盖某来源完全不能用。

### 13.2 必须通过的工程不变量

| 场景 | 要求 |
|---|---|
| 已有原生正文 | 内容不丢失，不额外请求原网页来取得同一正文 |
| 新文章自动正文 | 在没有用户访问时由引擎完成；首访只读本地已同步数据 |
| 完整性未确认 | 展示全部已获取内容并如实标记，不再被旧白名单拒为一行摘要 |
| 页面 GET/搜索/预览 | 不触发来源采集，不调用旧 fetch-full |
| 同一 Feed 20 次重复订阅请求 | 一条物理绑定，个人关系幂等 |
| 两位用户订阅相同 Feed | 分组/已读/收藏/取消互不污染 |
| 新增 Feed 请求超时 | 核对引擎后恢复，不重复创建 |
| worker 中途退出/页面提交失败 | 可重放且不漏记，不先提交游标 |
| 旧文章后补内容/新入库的旧日期文章 | 对账发现，不只看发布时间或新增 ID |
| 原文刷新失败 | 保留旧正文、译文及用户数据 |
| 受限来源、私网、恶意重定向、注入 HTML | 不访问/不泄漏/不执行；风险用受控测试服务器模拟 |
| 原站代码、表格、图片 | 与取得内容一致；代码复制不自动“修复”改写 |
| 引擎/RSSHub/目录服务故障 | 已缓存文章与 AI 可读能力保持；只相应新增连接或同步降级 |
| 最后取消订阅、重启服务 | 不误删别人数据，不恢复旧采集进程 |

### 13.3 质量和时延指标

硬门槛：测试中错误文章覆盖、跨用户泄漏、源策略绕过、代码文本改写、旧数据丢失均为 0。经确认原生全文的受控样本必须完整保留。

真实互联网抽样分别报告原生全文、网页提取、混合外链的可读率及人工完整性结果。可将普通已准入文章的完整正文目标设为 90% 作为首批产品验收目标，达不到时交付来源差异和失败清单，不把失败项从分母偷偷删掉；该数字不是所有 RSS 的服务承诺。

本地目录检索建议 p95 ≤500ms；正常无积压时，引擎成功落库到 NewsHub 可见建议 p95 ≤60 秒。两者均为待测验收目标，不包含发布者更新周期、源站超时或正在执行的初次大批量提取。文章从发布到可读的实际总时延另行记录。

### 13.4 资源测量

同一机器、相同来源/条目窗口、相同正文模式、相同 AI/索引设置，分别测旧单栈和新单栈：空闲 RSS/PSS 内存、抓取时峰值内存、CPU 时间、进程数、请求量、429、正文成功数与数据库增长。

从“首位读者打开才抓”改成“后台预先获取”，会对一部分最终无人阅读的文章增加请求；不能把更早获得正文与更低网络开销当成天然同时成立。优先原生全文、关闭不需要的二次提取，是控制该开销的主要手段。

新架构统计必须包含 Miniflux、PostgreSQL、rss-sync、启用时的 RSSHub。迁移期临时双栈结果不能冒充稳态结果；Feed 自带全文与网页提取应分组比较。不承诺资源一定下降多少，若峰值超预算或增加明显必须先降并发/采集模式/重复同步开销，不掩盖数据。

### 13.5 最终完成定义

只有同时满足以下条件才宣布改造完成：

- 普通公开 RSS 可以前端发现/直接添加，搜索目录可用，个人关系正确。
- Miniflux 承担全部常规 Feed 获取/解析和允许的自动正文提取。
- RSSHub 来源只用已维护路由，无新写抓取逻辑；未支持来源明确停止更新。
- 已取得内容在现有阅读界面正确显示，AI/TTS 等采用一致的权限和完整性上下文。
- 同步可以重放、对账、恢复；安全边界和数据迁移测试通过。
- 旧 crawler/full-content 及其定时任务、抓取依赖和运行引用已经移除。
- 部署、备份、恢复、升级、回滚的实测证据齐备；用户完成真实浏览器验收。

## 14. 执行前必须保留的限制说明

本次没有访问生产服务器、确认实际资源或修改来源开关。方案固定架构，但不把尚未测量的来源成功率、性能或部署连通性写成事实。

若 T00 发现特定来源没有可用 Feed/RSSHub 路由，或者 Miniflux 无法取得正文，处理方式是公开列出该来源边界、调整采集模式或提交上游问题；不是无声地加入自研爬虫。若关键产品来源无法达到用户要求，先报告具体缺口，不擅自改回旧技术方向。

部署到公开站点需要继续遵守已有来源展示政策；软件能返回内容不等于自动获得对所有内容的公开再发布许可。第三方许可证按实际锁定版本保留，独立服务不意味着可以忽略许可证。

## 15. 核验来源

### 项目代码（固定远端基线）

- [C01] [main 基线提交](https://github.com/CoderLambert/news-aggregator/commit/878b69081f8d5b3ae965bcf1c855390b059caa33)
- [C02] [AddChannelDialog.tsx](https://github.com/CoderLambert/news-aggregator/blob/878b69081f8d5b3ae965bcf1c855390b059caa33/frontend/src/components/workspace/AddChannelDialog.tsx)
- [C03] [news_ingestion.py](https://github.com/CoderLambert/news-aggregator/blob/878b69081f8d5b3ae965bcf1c855390b059caa33/backend/api/services/news_ingestion.py)
- [C04] [compose.prod.yaml](https://github.com/CoderLambert/news-aggregator/blob/878b69081f8d5b3ae965bcf1c855390b059caa33/compose.prod.yaml)
- [C05] [requirements.txt](https://github.com/CoderLambert/news-aggregator/blob/878b69081f8d5b3ae965bcf1c855390b059caa33/backend/requirements.txt)
- [C06] [MarkdownContent.tsx](https://github.com/CoderLambert/news-aggregator/blob/878b69081f8d5b3ae965bcf1c855390b059caa33/frontend/src/components/news-detail/MarkdownContent.tsx)

### 上游一手资料

- [U01] [Miniflux 官方 API / SDK / Discovery](https://miniflux.app/docs/api.html)
- [U02] [Miniflux Docker 部署](https://miniflux.app/docs/docker.html)
- [U03] [Miniflux 配置：私网访问、更新频率、限制](https://miniflux.app/docs/configuration.html)
- [U04] [Miniflux 2.3.3 原文处理逻辑](https://github.com/miniflux/v2/blob/2.3.3/internal/reader/processor/processor.go)
- [U05] [Miniflux 2.3.3 条目身份与更新逻辑](https://github.com/miniflux/v2/blob/2.3.3/internal/storage/entry.go)
- [U06] [Miniflux Webhook 与不重试说明](https://miniflux.app/docs/webhooks.html)
- [U07] [Awesome RSS Feeds 目录项目](https://github.com/plenaryapp/awesome-rss-feeds)
- [U08] [RSSHub 官方目录消费逻辑](https://github.com/DIYgod/RSSHub/blob/8aeca4cf7360a21651bf332d8363b4c1d45c003e/lib/routes/rsshub/routes.ts)；[目录构建逻辑](https://github.com/DIYgod/RSSHub/blob/8aeca4cf7360a21651bf332d8363b4c1d45c003e/scripts/workflow/build-docs.ts)
- [U09] [nh3 官方文档](https://nh3.readthedocs.io/en/latest/)
- [U10] [python-markdownify 项目](https://github.com/matthewwithanm/python-markdownify)
- [U11] [listparser 官方文档](https://listparser.readthedocs.io/en/latest/)
- [U12] [Folo UnifiedDiscoverForm](https://github.com/RSSNext/Folo/blob/dev/apps/desktop/layer/renderer/src/modules/discover/UnifiedDiscoverForm.tsx)
- [U13] [Miniflux 2.3.3 发布](https://miniflux.app/releases/2.3.3.html)

旧的两份方案是本次审核对象，不作为第三方能力的独立证明。实施中若升级上游版本，以重新运行的合同验证更新版本清单，而不是仅改镜像 tag。
