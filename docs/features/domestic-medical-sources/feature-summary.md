# 国内医疗来源动态接入功能实现总结

- 日期：2026-10-15
- 功能分支：`feat/domestic-medical-sources`
- 交付范围：在现有聚合器中加入可治理的动态来源注册、探测、审批、运行能力，并配置首批国内医疗资讯与 UDI 发布渠道；新来源不自动进入生产调度。

## 目标与边界

把原先依赖 Python 爬虫白名单和常量的来源接入，改为后台可管理、可探测、需审批的来源配置。普通资讯仍进入“医疗健康”频道；药监 UDI 增量发布作为 `regulatory_data` 独立数据渠道，不伪装成普通新闻或产品主数据。

本次交付不代表已获准生产启用。保存、迁移、探测和本地试运行均不会自动开启调度；生产启用仍要求超级管理员在当前配置版本探测成功并审批后手动操作。

## 实际实现

| 范围 | 主要文件或模块 | 交付内容 |
| --- | --- | --- |
| 数据模型与初始化 | `backend/api/models.py`、`backend/api/migrations/0048–0051` | 新增版本化 `SourceConfig`、`SourceEndpoint`；记录读取政策、状态、探测与审批信息；幂等初始化六个首批渠道，目标默认停用。 |
| 注册、探测与安全策略 | `backend/api/services/source_registry.py`、`source_probe.py`、`source_policy.py`、`dynamic_source_parsing.py` | 合并代码维护和后台维护来源的只读运行时注册表；实现来源入口探测、有限字段解析及网络访问约束。数据库配置不能覆盖代码来源键。 |
| 管理 API 与运行控制 | `backend/api/crawler_serializers.py`、`crawler_views.py`、`urls.py`、`management/commands/crawl.py` | 提供来源列表/创建、读取/修改/删除、探测、审批、启停和单次试运行接口；在运行时校验来源，不依赖静态 Spider choices。 |
| 采集适配器与入库 | `crawler/news_crawler/spiders/dynamic_source_spider.py`、`backend/api/services/feed_support.py`、`news_ingestion.py`、`full_content_status.py` | 动态 RSS/Atom、受限 JSON 与受控 HTML 适配器；复用已有条件请求、预算、身份去重、内容候选与入库链路。运行任务冻结配置快照。 |
| 管理界面与诊断 | `frontend/src/components/admin/SourceConfigSection.tsx`、`frontend/src/pages/admin/CrawlerAdminPage.tsx`、`frontend/src/services/crawlerAdminApi.ts`、`frontend/src/types/crawlerAdmin.ts` | 支持新建、编辑、复制、探测、审批、启停、试运行；区分 Worker 心跳、探测、采集成功和文章入库等健康信号。 |
| 证据与运维 | 本目录下的 `source-probes.json`、`acceptance.md`、`operations.md`、`implementation.md` | 留存有限范围官方入口探测证据、自动与人工验收清单、实施阶段记录及停用/回滚办法；不保存探测响应正文。 |

## 核心行为与兼容性

- 状态流转为 `draft → probed → approved → enabled`，并支持 `blocked`、`unsupported`。探测、审批和配置版本有关联；修改入口、域名或解析规则会使旧探测/审批失效并关闭调度。
- 所有新 `CrawlerTarget.enabled` 默认为 `false`。运行中的任务使用启动时配置快照；之后的管理修改只影响新任务。条件请求状态按来源键、入口 URL 和配置版本隔离。
- RSS/Atom、JSON 和 HTML 仅开放有限字段映射；不支持后台上传代码、模板、JavaScript 或 XPath 函数。HTML 入口受协议、官方域名、DNS、重定向、超时、响应大小和内容类型约束。
- 摘要保存在 `News.content`，缺少摘要时保留空内容及原文链接。`News.full_content` 只接受符合来源许可和完整性校验的候选正文；论文摘要仍为 `abstract`，UDI 发布保持 `regulatory_data`。
- 现有 `Source` 频道、`CrawlerTarget.spider_name`、运行历史和 API 字段继续兼容。停用不删除文章、订阅、收藏、聊天记录或运行证据；删除仅限没有关联数据的草稿配置。

## 首批入口探测结果

探测证据记录于 2026-10-15（Asia/Shanghai），遵守每源一个列表入口、最多三篇详情的低频窗口；没有分页、历史回填或反爬绕过。

| 来源键 | 渠道 | 探测状态 | 结论 |
| --- | --- | --- | --- |
| `chinanews_health` | 中国新闻网健康 | `SUPPORTED` | 官方 RSS 可解析，详情返回成功；Feed 最新条目及 `Last-Modified` 停在 2026-03-06，需重新探测评估时效。 |
| `china_cdc_news` | 中国疾控中心要闻 | `SUPPORTED` | 官方 HTML 列表与三篇详情可访问；生产需继续遵守 robots 策略，初始配置不翻页。 |
| `nhc_news` | 国家卫生健康委新闻动态 | `BLOCKED` | 普通 HTTP 探测收到 412；未尝试绕过 WAF。 |
| `nhsa_news` | 国家医保局医保动态 | `SUPPORTED` | 官方 HTML 列表与三篇详情可访问；初始配置不翻页。 |
| `nmpa_news` | 国家药监局要闻 | `BLOCKED` | 普通 HTTP 探测收到 412；未尝试绕过 WAF。 |
| `nmpa_udi_daily` | 国家药监局 UDI 每日增量 | `SUPPORTED` | 官方 RSS 可读；仅记录数据发布通知，不下载产品主数据。 |

上述 `SUPPORTED` 仅表示有限探测时入口和样本可解析，不是长期可用性或生产准入结论。六个配置均未审批，调度目标均保持关闭。

## 验证证据

以下为功能分支验收记录中的结果（详见 [`acceptance.md`](acceptance.md)），不是本次仅修改文档后重新执行的代码测试：

| 检查 | 记录结果 |
| --- | --- |
| 后端 `api/tests` | 1084 项通过，114.91 秒；有 1 条 ChromaDB 在 Python 3.16 下的第三方弃用预警。 |
| 部署相关测试 | 350 项通过，6.32 秒。 |
| Django system check、迁移差异检查 | 通过。 |
| 前端 TypeScript、ESLint、Vitest、生产构建 | 均通过；Vitest 为 84 个文件、566 项。 |
| Playwright 隔离管理流程 | 登录、新建、探测错误恢复、审批、试运行、启用和刷新流程通过；审批阶段使用隔离数据库中的探测状态，不构成真实上游成功验收。 |
| 动态 JSON Spider 独立 SQLite 全链路 | `Source → NewsSourceItem → News` 入库及条件状态提交通过。 |

本次文档交付另执行 `git diff --check` 和文档差异审阅；结果随提交前检查确认。没有因文档变更重跑后端或前端测试。

## 限制与后续验收

- 国家卫健委和国家药监局资讯入口仍为 HTTP 412 阻断状态；不得以绕过反爬作为上线手段。
- 中新网健康 Feed 在探测时已数月未更新。所有来源启用前应由管理员复核入口、样本内容、身份/时间字段和读取许可。
- 尚未执行生产启用、生产调度观察或长期稳定性验证。产品人工验收清单仍见 [`acceptance.md`](acceptance.md)。
- 回滚优先停用配置并保留关联数据；迁移及应用回滚顺序见 [`operations.md`](operations.md)。
- 主工作区已有的 SQLite 与验收材料未纳入本交付，保持原状。
