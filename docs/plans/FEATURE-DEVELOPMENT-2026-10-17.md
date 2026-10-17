# NewsHub 开发计划与原任务合同索引（2026-10-17 校正）

> **当前唯一的跨项目任务协调入口**。这是任务索引、优先级和状态交接，不替代各项目的原始设计/测试合同，也**不新增任务编号体系**。
>
> 代码基线：`main@48f29568d279852be903ab11f4a2e1d588f342a5`（PR #76、#77/#78、#90、#91 已合并）；合成 CI 后端最近基线为 **2429 passed / 16 skipped**。跳过不算通过。更新开发状态时必须指向实际 SHA、PR 与测试证据。
>
> **用户确定的阶段边界**：先继续功能开发与必需的单元/合成集成测试；真实浏览器手工验收、真实付费模型/厂商矩阵、公网 DNS/TLS、真实数据库副本恢复、容量/降级、生产切源/上线 **最后统一验收**。延期不代表门禁通过或永久取消。

## 1. 任务权威与唯一入口

| 工作流 | 原有权威（保留任务编号） | 本阶段如何跟踪 |
| --- | --- | --- |
| **RSS / 阅读与订阅** | [RSS 架构合同](rss-engine-migration/ARCHITECTURE.md)、[26 项有效交付 + 11 合并索引](rss-engine-migration/TASKS.md)、[执行与证据](rss-engine-migration/EXECUTION-STATUS.md) | 仍用 **RSS T00–T36**；以原有效交付为单位，不另建 RSS-R* 或 F52-R*。原 T29/T30/T31/T33 属生产切换、退出与发布门禁，保留不提前执行 |
| **个人 BYOK / 共享网关** | [原始 T00–T14 任务索引（冻结参考）](https://github.com/CoderLambert/news-aggregator/blob/ed58afa7a72ae905e2a2ffc315d968ca3634b8f2/docs/features/byok/tasks/README.md)及[同编号 Task/Test 合同](https://github.com/CoderLambert/news-aggregator/tree/ed58afa7a72ae905e2a2ffc315d968ca3634b8f2/docs/features/byok) | 只使用 **BYOK T00–T14 + T00-G**；旧 PR #33–#45 为未直接合并的实现与测试素材，需按最新 main 差量集成。不可用新 B00–B14 代替原任务 |
| **AI 智能频道整理** | [Issue #55：AG-00–AG-07](https://github.com/CoderLambert/news-aggregator/issues/55) | #55 为保留的功能 Issue；对照已有 `channel_topics/channel_grouping/channel_ai/SmartGroupingWorkspace` 差距开发，不建立平行 AG-R 编号 |
| **A09 / NewsHub 已完成整合** | [已合并 PR #76](https://github.com/CoderLambert/news-aggregator/pull/76) | 已入 main，发现回归只按原功能具体修复，不重开 A09 全套任务 |
| **最终统一验收** | [RSS 验收矩阵](rss-engine-migration/ACCEPTANCE-MATRIX.md)、[RSS T24/T26/T27/T29–T33](rss-engine-migration/TASKS.md)、[NH28–NH31 运维合同](../deployment/NH28-NH31-operator-acceptance.md)、原 **BYOK T13/T14** | 按原合同标记 `NOT_RUN` / `BLOCKED` / `PASS`。不再新增 #88/#89 一套重复生产验收 Issue |

**原始 BYOK 文档的 `PLANNED` 与旧分支 SHA 是历史快照，不代表 2026-10-17 的主线状态。** 本表只继承已确认的目标、编号和依赖；实际实现状态以最新 main 与旧 PR 逐项对比，不能因为同名功能存在就自动判定合同通过。RSS 的 T01/T10/T12 等合并索引不再重复开工单。

## 2. 恢复后的开发优先级和并行边界

| 顺序 | 工作流与原任务 | 需完成的开发动作（只修**差额**） | 阶段完成标准 |
| --- | --- | --- | --- |
| **D1** | RSS **T20/T21**（依赖 T16/T17/T19） | 频道目录搜索、按网址发现、已订阅状态/连接健康、订阅向导、OPML 预览确认/失败重试/分组导入导出；针对当前 UI、API 及后台已集成路径审计真正的代码缺口 | 相关后端与 React 回归、模拟订阅/并发/失败路径通过；T27 的人工浏览器部分留最终验收 |
| **D1** | BYOK **T00 + T00-G（仅独立本地交付）**，T01 可并行 | 复核官方 SDK→**真实隔离 LiteLLM Proxy**→受控上游的 Chat/Responses/Messages 终态、工具回合与 Key 隔离；选择性复用 #33/#35/#45。T01 核对现有单凭据存储与原“连接增删改停”差异，保留既有数据，向前迁移 | `SDK_LOCAL` 与 `PROXY_LOCAL` 依原合同各自记录；无真实付费调用。独立网关业务开发不依赖其**生产部署** |
| **D1** | 智能分组 **AG-01–AG-04** | 逐项核实现有元信息、规则、预览/手动排除和移动端/键盘 UI，仅补明确缺口。PR #90 的标题推测是低证据**补充**而非 AG-02/05 正式验收 | 规则无模型调用、双用户隔离、幂等/失效、Tab/Escape/焦点恢复及对应组件回归 |
| **D2** | BYOK **T02 → T03 → T04** | 模型录入/工具能力探针、按任务默认模型偏好、新闻问答 BYOK 完整闭环；不得将用户 Key 回退到站点 Key | 分任务模型和版本围栏、额度/错误、Owner ACL、合成 Proxy 完整终态测试 |
| **D2** | RSS **T09/T11/T14/T27 的代码差距** | Miniflux 同步/正文版本与消费层一致性、详情/翻译/问答/TTS 使用相同授权正文；T27 只补可自动验证的正文回归与 UI 缺口 | 旧内容不丢、摘要不伪装全文、旧兼容译文可回读、同步失败有界恢复 |
| **D2** | 智能分组 **AG-05/AG-06** | 在已授权 BYOK 服务合同上补 AI 结构化归类、受限预算/429 退避、独立队列与新订阅 `off/suggest/auto`；全站无人值守 AI 不能挪用个人 Key | mock/synthetic 上游、取消/恢复/人工优先、无权拒绝、GET 零推理；真实 DeepSeek 实测延期 |
| **D3** | BYOK **T05 → T06；T07 → T08** | 私人全文翻译、长文分块、断连/取消/显式重试、详情/聊天/TTS 同一用户私有结果；与 RSS 内容主写/版本迁移兼容 | 合成完整终态、版本与撤销围栏、私有历史可回读、Markdown 结构与分块一致 |
| **D3** | BYOK **T09 → T10；T11；T12** | 首次个人深度研究、续问恢复；问题推荐缓存；本人调用用量统计。按原独立任务交付，不能合并成未定义的“B10–B14”笼统工作 | 工具白名单/严格 JSON、用户隔离、额度计数、取消/恢复和故障测试 |
| **最终验收** | RSS **T18/T24/T26/T27/T29–T33**；BYOK **T13/T14**；智能分组 **AG-00 真实模型部分/AG-07 发布部分**；**NH28–NH31** | 真实来源许可/完整性、公网认证、业务数据库副本与回滚、真实厂商、真机/浏览器、隔离 2C4GB、最终单栈/旧栈退出及发布 | 分合同签字放行；未运行就是 `NOT_RUN`，不能从 CI 成功推导 |

**并行规则**：RSS 订阅 UI 与 BYOK T00/T01、AG 规则/UX 可并行；共用 `models.py` / URL / migration 文件时串行整合。BYOK T04/T09 要求 T00/T02/T03 的业务合同可用，但不要求先上线共享 Proxy。T13 的真实模型矩阵与最终人工 UAT 不阻塞前述代码开发。

## 3. BYOK 原 15 个任务：逐项保留，不重新编号

| 原任务 | 原有交付 | 原依赖 | 当前主线判定 |
| --- | --- | --- | --- |
| T00 | LiteLLM + SDK + 受控 upstream 三协议、本地终态/工具/隔离技术验真 | 无 | **历史实验与旧 PR 存在，待按 main 整合核验**；#91 仅属于终态防护局部修复 |
| T00-G | 独立 Proxy/Postgres、项目 virtual key/配额/日志/备份回滚运维交付 | T00 | [旧 #35](https://github.com/CoderLambert/news-aggregator/pull/35) 可选择性复用；业务开发阶段只做隔离实现/测试，不生产部署 |
| T01 | 个人 Key 连接的增删改停、掩码、恢复与隐私隔离 | 无 | main 有基础 `UserProviderCredential`，但原连接合同**未证完整** |
| T02 | 添加模型/可信预设；文本与工具能力显式探针 | T01、T00 | 旧 [#36](https://github.com/CoderLambert/news-aggregator/pull/36) 待审差量 |
| T03 | 默认/问答/翻译/研究/推荐用途模型偏好 | T02 | 旧 [#37](https://github.com/CoderLambert/news-aggregator/pull/37) 待审差量 |
| T04 | 新闻问答 BYOK、个人模型闭环 | T03、T00 | main 已有个人路径但未按新合同封口；旧 [#38](https://github.com/CoderLambert/news-aggregator/pull/38) 可复用 |
| T05 | 个人全文翻译持久结果/重开恢复 | T04 | 旧 [#39](https://github.com/CoderLambert/news-aggregator/pull/39) 待审差量 |
| T06 | 长文分块和 Markdown 安全完整合并 | T05 | 旧 [#40](https://github.com/CoderLambert/news-aggregator/pull/40) 待审差量 |
| T07 | SSE 断开、取消、显式再生成与代际围栏 | T05 | 旧 [#41](https://github.com/CoderLambert/news-aggregator/pull/41) 待审差量；不是“必须先完成 T06” |
| T08 | 译文详情/问答/朗读一致读取，换 Key 保留历史 | T05、T07 | 旧 [#42](https://github.com/CoderLambert/news-aggregator/pull/42) 待审差量 |
| T09 | 首次个人模型深度研究与合法工具调用 | T03、T00 | 旧 [#43](https://github.com/CoderLambert/news-aggregator/pull/43) 待审差量 |
| T10 | 研究续问、断线恢复及服务端 continuation | T09 | **不得遗漏**；原 Task/Test 合同仍有效 |
| T11 | 私有问题推荐及缓存，无隐性首次收费 | T04 | **不得遗漏** |
| T12 | 个人 AI 用量记录与可知/未知 token | T02、T04、T05、T09、T11 | **不得遗漏** |
| T13 | 六个首批产品预设分子卡的真实厂商验证（不是 LiteLLM 上限） | T00、T00-G、T02、T04、T09 | 最后统一验收；首轮实际厂商仅按独立获准 DeepSeek，其余保持 `NOT_RUN` |
| T14 | 功能/安全/兼容/发布判定 | T04–T13、T00-G | 最后统一验收 |

**技术方向不改**：NewsHub 后端用官方 SDK 访问 LiteLLM Proxy，Proxy 做路由/协议，NewsHub 不重做三套自研 provider adapter。用户 Key、项目 virtual key、Proxy master key 各有所有者；共享网关须可供其他项目复用。旧 BYOK 分支迁移编号不得直接搬到当前 RSS 后期数据库。

## 4. 智能分组 AG-00–AG-07：按源码差距推进

| 原任务 | main 已观察到的候选实现 | 后续动作 |
| --- | --- | --- |
| AG-00 | 来源标题/元信息和模拟分类证据存在 | 补完整样本覆盖/指标；真实模型受控调用留统一验收 |
| AG-01 | `SourceTopicProfile`、主题字典及来源概况已存在 | 验证目录版本/迁移和无副作用 GET |
| AG-02 | 目录规则、证据 hash、#90 **低置信度标题提示**已有 | 审核低证据标记、来源身份与分类重算幂等；标题提示不能当正式 AI 分类 |
| AG-03 | 私人提案预览/应用/撤销、人工抑制已有 | 补并发、过期、用户隔离与历史分组不破坏测试 |
| AG-04 | `SmartGroupingWorkspace` 页面已有 | 优先核对移动端 390px、键盘/焦点恢复、空状态和异常提示 |
| AG-05 | 可选 BYOK 模型分类代码已有 | 依赖 BYOK 验证能力；补安全的结构化结果和预算/429；真实厂商调用延后 |
| AG-06 | `off/suggest/auto` 增量订阅和队列已有 | 审核来源新增、任务恢复、人工优先与限额 |
| AG-07 | 开关/边界与部分运维逻辑已有 | 先补离线退避/回滚/监控代码；发布实测最后验收 |

AG 项只能标 **`代码已有/待核对/待开发/待真实验收`**，不因文件/单测存在直接宣告原 Task PASS。只有 [#55](https://github.com/CoderLambert/news-aggregator/issues/55) 作为本工作流 Issue；旧设计 PR #54 已关闭，不作为新功能实现基线。

## 5. 旧采集与 #52 的归属

已确认的 [RSS 最终架构](rss-engine-migration/ARCHITECTURE.md)规定：**Miniflux + PostgreSQL 是唯一常规 RSS/正文提取引擎，RSSHub 提供可选已有路由**。NewsHub 负责同步、内容转换、目录、订阅、阅读与 AI。最终切源后退出 Scrapy、独立 Feed Parser、旧 `article_fetcher` 提取 Provider、旧全文 Worker。

因此旧 [Issue #52](https://github.com/CoderLambert/news-aggregator/issues/52) 的 Spider → `full_content` 继续扩展不再另做。保留其历史问题/已落地旧兼容代码，但**不能**继续投资即将退出的旧抓取链。正文真实性、质量、内容版本、翻译失效和来源权限归属 RSS **T06/T07/T09/T11/T14/T27**；真实来源质量最后按 RSS 验收矩阵核实。PR #90 对旧 `source_probe` 的有界读取属于已合入的兼容安全修复，**不产生新一轮旧采集开发任务，也不提前删除仍参与运行的旧代码**。旧栈真正退出归 RSS T29/T30/T31/T33 最终门禁。

## 6. GitHub Issue / PR 清理规则

| 对象 | 决定 | 理由与承接 |
| --- | --- | --- |
| [#55](https://github.com/CoderLambert/news-aggregator/issues/55) | **保留 OPEN，更新原 AG-00–07 状态与链接** | 原生功能 Issue，不引入新 AG-R 体系 |
| [#52](https://github.com/CoderLambert/news-aggregator/issues/52) | **关闭为 not planned（原实现路径被架构替代）** | 后续正文与发布合同由 RSS 原任务承担；这不表示正文质量问题已解决 |
| [#92](https://github.com/CoderLambert/news-aggregator/issues/92) | **关闭为 not planned（重复规划）** | 不再使用 B00–B14；恢复原 BYOK T00–T14/T00-G |
| [#88](https://github.com/CoderLambert/news-aggregator/issues/88) | **关闭为 not planned（重复追踪）** | RSS 的 T18/T24/T26/T27 + 原验收矩阵保留 `NOT_RUN` 与真实门禁 |
| [#89](https://github.com/CoderLambert/news-aggregator/issues/89) | **关闭为 not planned（重复追踪）** | NH28–NH31 原运维合同保留；不是取消发布安全门槛 |
| **旧 BYOK PR #33–#45** | **暂不成批关闭、不直接合并** | 实际代码/测试素材尚未逐项对照；按原 T 编号完成后再逐项去重收口 |
| **SIWC PR #28** | **继续 Draft** | Hosted 推理使用须另外取得明确授权，不能在本开发阶段借道开启 |

旧 [PR/Issue 审计快照](MAIN-PR-ISSUE-AUDIT-2026-10-17.md)只保存历史取证，原来的 F52-R/F55-R 或建议优先级**不再作为当前计划**。

## 7. 代码开发的质量门禁与交付格式

- 每次开工先查最新 `main`、既有实现、原 Task/Test 合同和相关旧 PR patch，产出 **`原 ID → 现存代码 → 真正缺口 → 修改文件 → 专项测试 → PR/SHA`**，禁止临时发明新编号或把小的可选优化插队。
- 原任务可按文件边界并行；每项先专项单测/类型检查，再按批次集成。避免无必要地在每个小提交重复全量 CI；但不能跳过仓库实际要求的 PR 合并门禁。全部开发完成后的统一验收仍包含最终全量 CI、人工 UAT、真实厂商和生产环境证据。
- 区分 `IMPLEMENTED`（代码存在）、`TESTED`（指定 SHA 的自动化通过）、`ACCEPTED`（原合同与必要环境全部满足）、`NOT_RUN`、`BLOCKED`。上一轮两批 PR #90/#91 是**附加兼容改进**，不冲销原 RSS/BYOK/AG 的未完成任务。
- 不自动更新真实发布开关、生产数据库、用户 API Key、OAuth hosted 模式、站点服务或公网来源；原归属与权限模型不因为计划重排而被修改。
