# 上游能力核验与尚待运行的边界

核验日期：2026-10-16。证据类型为官方文档及上游源码静态阅读；本轮没有启动引擎、抓取目标文章、部署服务或变更生产。本文辅助接口冻结，不改变 `ARCHITECTURE.md` 的技术方向，也不充当实际运行验收报告。

## 1. 版本与证据效力

本次查询的官方发布列表最新列出 Miniflux 2.3.3（2026-07-24）。下文 Miniflux 行为以该 tag 的源码为核验参考。**参考版本不等于验收通过的版本锁**：Miniflux、PostgreSQL、RSSHub、Python SDK、转换库的最终版本及镜像 digest 仍须在隔离验证任务中记录实际制品、平台和运行证据；不能根据本文自动填写 digest 或宣称兼容性已通过。[官方发布列表](https://miniflux.app/releases.html)、[2.3.3 发布说明](https://miniflux.app/releases/2.3.3.html)

RSSHub 与 Python SDK 的 `master` / `main` 链接只证明核验时可见实现，不能充当最终不可变依赖锁。执行任务须记录所选 commit/tag、依赖版本及校验值，再重跑合同测试。

## 2. 引擎 API 与 SDK 边界

### 2.1 已核实的常规能力

官方提供 Python API 客户端。可优先包装 `discover`、`create_feed`、`get_feeds`、`get_feed`、`get_feed_entries`、`get_entries`、`get_entry`、`refresh_feed`，固定服务地址并使用专用非管理员账号 token。发现输入为网站 URL；创建输入包含 Feed URL 及 `crawler` 等设置。NewsHub 自行承担操作意图、权限、配额、幂等和超时后核对，SDK 不替代这些业务合同。[官方客户端](https://github.com/miniflux/python-client)、[客户端实现](https://github.com/miniflux/python-client/blob/main/miniflux.py)

最小 API 对应关系如下；其余字段以锁定版本的契约测试为准。[官方 API 参考](https://miniflux.app/docs/api.html)

| 操作 | 引擎接口 | NewsHub 约束 |
|---|---|---|
| URL 发现 | `POST /v1/discover` | 显式操作、登录、配额、不得透传用户自定义请求头 |
| 创建 | `POST /v1/feeds` | 超时为结果不明；查询已有订阅后再重试 |
| 条目读取 | `GET /v1/entries`、`GET /v1/feeds/{feed_id}/entries` | 白名单 DTO，不透传嵌套 Feed 凭据 |
| 刷新 Feed | `PUT /v1/feeds/{feed_id}/refresh` | 与单篇正文重试是不同操作 |
| 单篇正文重试 | `GET /v1/entries/{entry_id}/fetch-content?update_content=true` | 具有来源网络请求和可选写入副作用，只允许 worker 执行 |

### 2.2 普通刷新不等于强制正文重新提取

2.3.3 的 `refreshFeedHandler` 调用 `RefreshFeed(..., false)`。正文处理器仅在 `crawler=true` 且条目为新条目或 `forceRefresh=true` 时尝试原网页。刷新实现还在普通 `crawler=true` 情况下跳过已有条目内容更新。因此，不能承诺普通 API 刷新会修复全部旧正文，或者自动发现任意旧网页编辑。[API handler](https://github.com/miniflux/v2/blob/2.3.3/internal/api/feed_handlers.go)、[刷新流程](https://github.com/miniflux/v2/blob/2.3.3/internal/reader/handler/handler.go)、[正文处理器](https://github.com/miniflux/v2/blob/2.3.3/internal/reader/processor/processor.go)

抓取错误或空提取结果时，处理器保留 Feed 内容；普通 `entry.content` 没有可用于证明完整原文的提取成功字段。`crawler` 或非空内容均不能自动映射到 `verified`。[正文处理器](https://github.com/miniflux/v2/blob/2.3.3/internal/reader/processor/processor.go)

### 2.3 单篇重试存在 SDK 参数缺口

API 的 `update_content` 默认 false；2.3.3 handler 仅在显式 true 时持久更新标题与正文。核验时官方 Python SDK 的 `fetch_entry_content(entry_id)` 未暴露此参数，只获取返回结果。必须在实施前冻结最小 SDK 包装扩展及重新读取策略，不能假定 SDK 方法已经更新上游数据库。包装仍只请求固定引擎 API，不能改为自己请求发布者 HTML。[SDK 方法](https://github.com/miniflux/python-client/blob/main/miniflux.py)、[单篇重试 handler](https://github.com/miniflux/v2/blob/2.3.3/internal/api/entry_handlers.go)

单篇成功响应不代表完整性已验证；结果仍经同一内容保护合同接收。页面 GET、搜索、预览不得调用这个具有副作用的引擎 GET。

## 3. 同步与内容对账

### 3.1 身份、时间和正文哈希不能混用

2.3.3 存储的 `updateEntry` 在 Feed 更新时修改正文但未更新 `changed_at`；阅读/收藏状态修改却会更新该时间。`entry.hash` 用于上游条目身份匹配，不能直接作为 NewsHub 正文版本哈希。因此不能只依赖 `changed_after` 或上游 `hash` 发现内容变化。NewsHub 必须分别保存引擎身份、本地内容摘要和转换版本。[存储实现](https://github.com/miniflux/v2/blob/2.3.3/internal/storage/entry.go)、[条目字段](https://github.com/miniflux/v2/blob/2.3.3/internal/model/entry.go)

新 ID 扫描加全保留条目对账只能保证发现**引擎已经保存**的内容变化；它不等于重新访问源站，也不能弥补引擎从未取得或已清理的内容。

### 3.2 分页的精确边界

冻结显式 `order=id&direction=asc`，不使用默认发布时间排序。`after_entry_id=L` 是严格 `id > L`；`before_entry_id=H` 是严格 `id < H`。若本轮选定最大可见 ID 为 H，欲包含该条，可使用 `before_entry_id=H+1`，但必须验证整数边界，不能错误使用 H 而漏掉末条。新增循环和对账循环分别持久记录上下界及进度。[查询构建器](https://github.com/miniflux/v2/blob/2.3.3/internal/storage/entry_query_builder.go)

API 默认条目页大小 100；2.3.3 常规条目上限 1000。不得用 `limit=0` 当无上限导出，不能因请求最后一页外的 offset 而猜测完成。空页、页重放、清理并发与晚提交事务须通过运行测试。ID 序列不是严格提交日志：固定上界的单轮扫描仍可能漏到晚提交的小 ID，后续完整对账负责最终补偿。[API handler](https://github.com/miniflux/v2/blob/2.3.3/internal/api/entry_handlers.go)、[条目限制](https://github.com/miniflux/v2/blob/2.3.3/internal/model/entry.go)、[分页修复记录](https://miniflux.app/releases/2.3.3.html)

### 3.3 90 天保留期的真实含义

官方默认已读清理阈值 60 天、未读 180 天，清理周期 24 小时。统一 90 天是本项目配置选择，需分别显式配置 `CLEANUP_ARCHIVE_READ_DAYS=90`、`CLEANUP_ARCHIVE_UNREAD_DAYS=90`，并由版本验证确认有效；不是上游已有默认。[配置文档](https://miniflux.app/docs/configuration.html)

2.3.3 `ArchiveEntries` 按 `created_at` 判断年龄，并排除 starred/shared 条目；按批次删除并保留身份 tombstone。因此，“90 天”不是发布时间窗口、精确全库存量上限或可恢复的 removed 正文仓库。每日对账必须覆盖引擎实际仍保留的条目，不能过滤 `published_at >= now-90d`。NewsHub 已接受正文不因引擎清理而删除；超保留期停机与 Feed 历史滚动缺失应报告不可恢复范围。[清理与 tombstone 实现](https://github.com/miniflux/v2/blob/2.3.3/internal/storage/entry.go)

## 4. SSRF、网关凭据与媒体 URL

`FETCHER_ALLOW_PRIVATE_NETWORKS=0` 默认拒绝私网/环回请求，与直接注册 Docker 私网 RSSHub 地址冲突。2.3.3 fetcher 在实际连接地址处进行检查；显式代理是信任跳点，不能只看此开关就宣布所有代理链安全。生产默认公网 HTTPS 网关方向可保持，但 DNS、公网回流、证书、跳转、IPv4/IPv6 和私网拒绝必须受控运行验证。[fetcher 实现](https://github.com/miniflux/v2/blob/2.3.3/internal/reader/fetcher/request_builder.go)

Feed 请求使用配置的 Basic Auth；正文处理器没有直接加入 Feed 的 username/password。这是静态事实，不是凭据绝无泄露的运行证明。上游 fetcher debug 日志包含请求 headers，生产应避免 debug，并验证日志、错误 DTO、OPML、浏览器及外站均不含网关凭据。网关拒绝越权路由、用户输入无法设置 proxy/cookie/TLS bypass 的门禁仍待实测。[Feed 请求流程](https://github.com/miniflux/v2/blob/2.3.3/internal/reader/handler/handler.go)、[正文请求构造](https://github.com/miniflux/v2/blob/2.3.3/internal/reader/processor/processor.go)、[日志位置](https://github.com/miniflux/v2/blob/2.3.3/internal/reader/fetcher/request_builder.go)

条目 API 会对内容中的媒体 URL 应用 Miniflux media proxy 改写。其 API 为私有地址时，直接保存代理 URL 可能让 NewsHub 浏览器得到不可达的内部地址。实施前需冻结经过验证的媒体模式与 URL 接收方式；不得靠开放引擎管理 API 或新增图片下载器解决。只有相对地址解析也不足以解决已经改写的绝对内部 URL。[条目返回逻辑](https://github.com/miniflux/v2/blob/2.3.3/internal/api/entry_handlers.go)

## 5. RSSHub 目录和轻量运行边界

官方构建产物为 namespace → routes；参数可以是字符串或结构化对象，path 可以是字符串或数组。能力标记含 `requireConfig`、`requirePuppeteer` 等；导入必须保留模板/实例区别及必要配置，不能把 example 当运行通过证明。[类型定义](https://github.com/DIYgod/RSSHub/blob/master/lib/types.ts)、[构建逻辑](https://github.com/DIYgod/RSSHub/blob/master/scripts/workflow/build-docs.ts)、[官方目录消费代码](https://github.com/DIYgod/RSSHub/blob/master/lib/routes/rsshub/routes.ts)

当前 GitHub Trending 路由 `/github/trending/:since/:language/:spoken_language?` 标记无需 Puppeteer，但要求 `GITHUB_ACCESS_TOKEN`。该凭据、实际出口及返回对象质量是来源验证前置；“无浏览器”不等于“无需配置”。当前路由包含仓库类内容，不能直接称为完整新闻正文。[Trending 上游实现](https://github.com/DIYgod/RSSHub/blob/master/lib/routes/github/trending.tsx)

目录构建还包含来自外部 Folo 分析的 `heat` / `topFeeds`。NewsHub 目录 DTO 应采用白名单，不将这些字段当自身订阅统计或稳定开放搜索合同，也不依赖其存在才能完成目录更新。[目录构建来源](https://github.com/DIYgod/RSSHub/blob/master/scripts/workflow/build-docs.ts)

RSSHub 当前默认支持 `CACHE_TYPE=memory`，不强制需要 Redis。`MEMORY_MAX` 默认 256 是 LRU **条目数**，不是 MiB/字节上限；route/content TTL 分别配置。容器内存预算与峰值需另测。无需浏览器的批准路由可以作为本项目候选，需要浏览器的路由应明确不支持，不能静默新增浏览器服务。[配置](https://github.com/DIYgod/RSSHub/blob/master/lib/config.ts)、[内存缓存](https://github.com/DIYgod/RSSHub/blob/master/lib/utils/cache/memory.ts)

## 6. 内容转换和 OPML

nh3 可对已有 HTML 字符串限定标签、属性和 URL scheme，并支持相对 URL 处理；markdownify 用于转换已有 HTML；listparser 接受上传清单内容。这些职责与禁止新增 Feed XML 解析器、正文提取器相容。必须针对锁定版本验证代码文本、表格、图片、链接和恶意输入，不把库名本身视为安全及保真验收通过。[nh3](https://nh3.readthedocs.io/en/latest/)、[markdownify](https://github.com/matthewwithanm/python-markdownify)、[listparser parse](https://listparser.readthedocs.io/en/latest/reference/parse.html)

## 7. 可冻结部分、待决议与运行门禁

可冻结：引擎唯一职责、官方 SDK 优先、明确操作队列、用户状态留在 NewsHub、新 ID 加全保留条目对账、本地内容哈希、普通刷新与单篇重试分离、不可因引擎清理删除本地历史、目录只处理声明式白名单元数据。

待开发合同/独立 ADR 处理：SDK 单篇重试参数扩展及持久化重新读取策略、实际保留期配置和告警阈值、媒体代理 URL 策略、GitHub token 配置责任，以及锁定版本与制品。不得由执行 Agent 以未经审核的新网络抓取路径替代。

| 运行验收项 | 本次状态 | 解除条件 |
|---|---|---|
| 固定版本 API、SDK、分页边界及超时恢复 | BLOCKED | 隔离引擎与可复现契约测试报告 |
| 自动正文、提取失败回退与显式单篇持久化 | BLOCKED | 真实样本和受控失败响应，记录 Feed/entry 身份 |
| 旧内容更新、晚提交、清理并发、断点恢复 | BLOCKED | 故障注入及对账收敛证据 |
| SSRF、重定向、DNS、网关认证及无泄露 | BLOCKED | 受控安全端点、网络与日志证据 |
| RSSHub 网关及 Trending 等真实路由 | BLOCKED | 所需 token、实际出口、网关回流和内容验收 |
| 媒体 URL、代码/表格/图片与前端渲染 | BLOCKED | 锁定依赖夹具与真实浏览器验收 |
| PostgreSQL/SQLite 备份恢复、升级回滚 | BLOCKED | 隔离恢复演练与一致性检查 |
| 资源、质量及延迟目标 | BLOCKED | 统一窗口、同机单栈对照实测 |

以上 BLOCKED 表示相应运行条件本轮未验证，不表示规划文档 PR 不能提交；它们阻止依赖这些运行结果的任务被标记完成或生产放行。
