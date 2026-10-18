# 历史快照（非当前任务入口）

> 此文件原样保存旧批次的讨论与验收文案。过去的“当前状态”“下一批候选”均非现行指令。请参考[现行开发计划](../FEATURE-DEVELOPMENT-2026-10-17.md)。

---

# NewsHub 开发计划与原任务合同索引（2026-10-17 校正）

> **第 5 批合并后基线（2026-10-18，优先于下文较早的第 4 批/历史计划条目）**：本批两项均由最新 `main@5a2f55e` 独立分支开发，按原 Task/Issue 编号交付；PR 已分别 squash 合并。
>
> - **AG-01 来源主题元信息：** [PR #104](https://github.com/CoderLambert/news-aggregator/pull/104)，merge `c863b1d1832a97080c33e671b65fc6fa30c92f98`，合成 [PR CI #39101549592](https://github.com/CoderLambert/news-aggregator/actions/runs/39101549592) 和合并后的 [main CI #39102055335](https://github.com/CoderLambert/news-aggregator/actions/runs/39102055335) 均成功。增加来源名称和受信域名核对、公共来源身份/语言/目录资料的版本化证据、人工主题过期审核标志、幂等重算与 GET 无模型/网络/写入回归；保留既有 `SourceTopicProfile` 与用户私有分组。PR 后端混合矩阵 **2461 passed / 16 skipped**，前端 **655 passed**。详见 [AG-01 交付合同](../features/smart-channels/AG-01-2026-10-18.md) 和 [Issue #55](https://github.com/CoderLambert/news-aggregator/issues/55)。
> - **BYOK T01 Worker 撤销围栏：** [PR #105](https://github.com/CoderLambert/news-aggregator/pull/105)，merge `e64271af7e97241da33b1f5799ae02094fd9da29`；[PR CI #39102434181](https://github.com/CoderLambert/news-aggregator/actions/runs/39102434181) `success`，后端 **2484 passed / 16 skipped**、前端 **655 passed**、动态测试身份门禁、生产镜像及隔离 G1 Smoke 成功。通过 `ai_worker_fencing` 统一无密钥快照、enqueue/claim/retry/dispatch/commit 检查，绑定 owner/epoch/credential_version/provider/endpoint，撤销后阻止新的授权并丢弃过期结果；密文异常和请求前竞态有合成测试。维持 **T02/T03 未完成前的个人模型 fail-closed**。**注意：这是 T01 共享 Worker 凭据安全合同 `IMPLEMENTED + TESTED`，不是聊天、翻译、研究等尚未绑定 T02/T03 模型的具体 Worker 业务端到端已启用**；现有 ChatGPT Subscription 完全独立。详见 [T01 交付合同](../features/byok/T01-WORKER-FENCING-2026-10-18.md)。
> - **当前功能合并基线：** `main@e64271af7e97241da33b1f5799ae02094fd9da29`（本计划同步的文档提交将再前进一个 SHA，最终门禁须核对文档提交后的实际 main）。**AG-00/02–07、BYOK T02/T03 及后续任务继续沿原任务边界执行；不创建新的编号、不直接合并旧 BYOK PR #33–#45。**
> - **NOT_RUN（本批授权范围之外）：** 真实付费厂商模型、真实多进程 PostgreSQL 负载/竞态验收、真实浏览器/手机人工 UAT、生产数据迁移、生产采集和部署。已发往上游的请求不保证能够撤回或取消计费；终态写入必须由未来业务 Worker 在同一 DB 事务内核验 lease/generation 与 epoch。第 6 批未经用户确认不自动启动。


> **第 4 批交付更新（2026-10-18，取代本文件较早的“下一批候选/旧连接并存”状态说明）**：正式功能代码已合并至 `main@13584bcbf3cee7a3787e64bab0da786f8fd8ee47`。CI 门禁 [#102](https://github.com/CoderLambert/news-aggregator/pull/102) 已 squash 合并于 `85994f7`，BYOK T01 旧单 Key 退出 [#103](https://github.com/CoderLambert/news-aggregator/pull/103) 合并于 `13584bc`。T01 单连接架构的前端、后端及 G1 合成 CI 均已在 PR SHA `cd4bbae` [成功验证](https://github.com/CoderLambert/news-aggregator/actions/runs/39053903501)：后端 **2454 passed / 16 skipped**，包含动态身份对账；[#102 三轮独立 CI](https://github.com/CoderLambert/news-aggregator/actions/runs/39052392960) 全绿。最终合并后的 [main CI](https://github.com/CoderLambert/news-aggregator/actions/runs/39098969386) 以实际结果为准，不能把 PR CI 替代为该结果。
>
> **当前架构**：唯一个人 Key 入口 `/settings/ai` 与 `UserAIConnection`；`UserProviderCredential` 运行模型、旧 API/UI/服务已退出。新增 `0061` 对旧密文做一次性原子迁移（不可解密则整个事务回滚），迁入连接默认停用，保留 model ID 提示供 T02 使用；不得在未经授权的生产数据库执行。ChatGPT 订阅独立保留。业务尚无 T02/T03 模型+用途绑定时 fail-closed，不恢复旧调用或站点 Key。**原 T01 的真实后台 worker 全量 credential_epoch 围栏**按原计划在第 5 批继续；真实厂商、真实用户 Key、生产迁移和人工验收均 NOT_RUN。
>
> **后续顺序**：第 5 批仅 BYOK T01 worker 撤销围栏 + AG-01 来源元信息。其余仍按原任务合同、每批最多两个独立目标推进。本文件旧章节均保留为 2026-10-17 历史审计快照，不代表最新未完成任务清单。

> **当前唯一的跨项目任务协调入口**。这是任务索引、优先级和状态交接，不替代各项目的原始设计/测试合同，也**不新增任务编号体系**。
>
> 本轮开发基线：`main@2e3254c890f52af626aa7d2400097301bf550d14`（含原任务权威校正 #93）；合成 CI 后端基线为 **2429 passed / 16 skipped**。跳过不算通过。本批 RSS T20 / BYOK T00 的实际提交、PR 和验证见第 7 节；合并后的 main 以对应 PR 的 merge SHA 为准。
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
| T00 | LiteLLM + SDK + 受控 upstream 三协议、本地终态/工具/隔离技术验真 | 无 | **PARTIAL**；[本轮 #95](https://github.com/CoderLambert/news-aggregator/pull/95) 补官方 SDK 与 LiteLLM 1.105.0 隔离进程验证，`SDK_LOCAL` / `PROXY_PROCESS_LOCAL` PASS；原 1.104.2 镜像、digest/签名与历史 EOF 对照仍 `NOT_RUN`，不等同于镜像级 `PROXY_LOCAL` 或任务 DONE。见[运行与合同映射](../../tools/byok_t00_probe/README.md) |
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

## 7. 2026-10-17 双任务交付记录

开工及提交前重新核对的 main 为 `2e3254c890f52af626aa7d2400097301bf550d14`。本批只实施 RSS T20 与 BYOK T00；原任务合同和最终验收边界保持有效。

| 原任务 | 实际代码与 PR | 本次验证及状态 |
| --- | --- | --- |
| RSS T20 | [PR #94](https://github.com/CoderLambert/news-aggregator/pull/94)，功能提交 [`add9d64`](https://github.com/CoderLambert/news-aggregator/commit/add9d64e695d74c3edc4841b6dd54a943efbaa1f)。按目录、发现、订阅保存和连接查询的失败阶段恢复；固定订阅重试参数与幂等 key，隔离账号切换和旧响应，停止错误/终态轮询 | 本次错误恢复差额 IMPLEMENTED / TESTED。RSS 专项 26 passed；频道/API 关联回归 32 passed，两组有重叠。独立审核 PASS；[PR CI 39020535285](https://github.com/CoderLambert/news-aggregator/actions/runs/39020535285) 成功：前端 609 passed、后端 2429 passed / 16 skipped、隔离 G1 合成 smoke PASS。原 [Task/Test/report](rss-engine-migration/tasks/T20/report.md) 已更新；真实浏览器/来源/人工验收仍 NOT_RUN |
| BYOK T00 | [PR #95](https://github.com/CoderLambert/news-aggregator/pull/95)，功能提交 [`b414ffd`](https://github.com/CoderLambert/news-aggregator/commit/b414ffd836cab032e48131fcac460f4772e60cc2)。新增可复跑的官方 SDK → 真实 LiteLLM → 合成上游探针，临时 PostgreSQL 发放真实项目 virtual key；在现有 CI 中增加独立验证步骤 | **PARTIAL**。24 单元测试 PASS；207 项协议/收据检查 PASS、0 FAIL，含 root + 0700 venv + asyncio。实际/预期上游请求均 86；93 个 SDK 客户端全部关闭。独立审核 PASS；完整 PR CI 与合并状态以 #95 实际检查为准，成功前不合并。命令、版本和原 T00-01–10 映射见 [README](../../tools/byok_t00_probe/README.md) |

T00 的 207 项包含 106 项请求计数/收据检查，不是 207 个单元测试。当前 Proxy Chat 流式按已有 guard 返回 400 且零上游请求，记录的是失败关闭，不是流式成功兼容；Responses / Messages 流式和三协议非流式分别核验。原 1.104.2 镜像、digest/签名、历史 EOF 对照均 **NOT_RUN**，1.105.0 的进程证据不能替代它们。T00-G 完整运维交付、真实厂商/用户 Key、真实数据库、生产部署与最终验收未在本批执行。

下一批候选仍是 **RSS T21 + BYOK T01**。仅在本批 PR 审核和 CI 阻塞清零后，重新读取最新 main 与原依赖再选择具体差额；T00 的未验证项继续跟踪，不将本次局部通过自动转为 T02/T04/T09 的完整依赖放行。BYOK T10 研究续问、T11 问题推荐、T12 个人用量记录保持原独立任务。

## 8. 代码开发的质量门禁与交付格式

- 每次开工先查最新 `main`、既有实现、原 Task/Test 合同和相关旧 PR patch，产出 **`原 ID → 现存代码 → 真正缺口 → 修改文件 → 专项测试 → PR/SHA`**，禁止临时发明新编号或把小的可选优化插队。
- 原任务可按文件边界并行；每项先专项单测/类型检查，再按批次集成。避免无必要地在每个小提交重复全量 CI；但不能跳过仓库实际要求的 PR 合并门禁。全部开发完成后的统一验收仍包含最终全量 CI、人工 UAT、真实厂商和生产环境证据。
- 区分 `IMPLEMENTED`（代码存在）、`TESTED`（指定 SHA 的自动化通过）、`ACCEPTED`（原合同与必要环境全部满足）、`NOT_RUN`、`BLOCKED`。上一轮两批 PR #90/#91 是**附加兼容改进**，不冲销原 RSS/BYOK/AG 的未完成任务。
- 不自动更新真实发布开关、生产数据库、用户 API Key、OAuth hosted 模式、站点服务或公网来源；原归属与权限模型不因为计划重排而被修改。

