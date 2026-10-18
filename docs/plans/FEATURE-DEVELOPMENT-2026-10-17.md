# NewsHub 现行开发任务与合同索引

> **更新于 2026-10-18**；第 7 批功能合并基线为 `main@c51dceb3d10a22e8164d35cea256395b3fd165a4`（本状态同步提交晚于该 SHA）。每次开工仍必须重新读取最新 main。**本文件是当前任务状态唯一入口**；[2026-10-17 原计划和旧批次记录已完整归档](archive/FEATURE-DEVELOPMENT-SNAPSHOT-2026-10-17.md)，其中的“下一批/T01 待完成/旧凭据并存”属于历史快照，不再指导开发。

## 1. 当前已验证交付与未完成边界

| 原任务 | 当前状态 | 证据、边界 |
|---|---|---|
| BYOK T01 连接与旧单 Key 退出 | `IMPLEMENTED / TESTED` | [PR #103](https://github.com/CoderLambert/news-aggregator/pull/103)：`UserAIConnection` 是唯一现行个人连接身份；`0061` 原子迁移旧密文、默认停用，生产迁移未授权 |
| BYOK T01 通用 Worker 围栏 | `IMPLEMENTED / TESTED` | [PR #105](https://github.com/CoderLambert/news-aggregator/pull/105)、[合同](../features/byok/T01-WORKER-FENCING-2026-10-18.md)：owner/epoch/version，enqueue/claim/retry/send/commit 保护 |
| AG-01 来源主题元信息 | `IMPLEMENTED / TESTED` | [PR #104](https://github.com/CoderLambert/news-aggregator/pull/104)、[合同](../features/smart-channels/AG-01-2026-10-18.md)：域名真实性、版本化证据、人工审核、幂等及 GET 无副作用 |
| RSS T20 订阅发现错误恢复 | `IMPLEMENTED / TESTED`（差额） | [PR #94](https://github.com/CoderLambert/news-aggregator/pull/94)：按失败阶段恢复；不代表 RSS 最终切源/发布验收通过 |
| BYOK T00 SDK/Proxy 进程 | `PARTIAL` | [PR #95](https://github.com/CoderLambert/news-aggregator/pull/95)：合成 `SDK_LOCAL / PROXY_PROCESS_LOCAL` 通过；真实上游/正式镜像合同/运维均尚未完整验收 |
| BYOK T02 个人模型配置和显式能力探针 | `IMPLEMENTED / TESTED`（离线合成） | [PR #111](https://github.com/CoderLambert/news-aggregator/pull/111)，head `ae8825b024716c6c6fd31bfdec64be39727a84cc`，Squash `a006c59a7a24fa782f3e691872d9fb02058ae4b0`，[CI #39125387435](https://github.com/CoderLambert/news-aggregator/actions/runs/39125387435)：后端与发布门禁、前端通过；[main CI #39136578514](https://github.com/CoderLambert/news-aggregator/actions/runs/39136578514) 已 PASS。保留 `ai_execution.py` fail-closed；真实 Provider/浏览器 UAT `NOT_RUN`。T03 现已保存用途偏好，但业务消费者仍未接通 |
| AG-02 离线规则和可信证据 | `IMPLEMENTED / TESTED`（差额） | [PR #110](https://github.com/CoderLambert/news-aggregator/pull/110)，head `cf9e8169ec0f37c1bc5677dbff7a005637d718bf`，Squash `36deba6779f4c3527c5b07fb22a6a8487e62b516`，[CI #39124308296](https://github.com/CoderLambert/news-aggregator/actions/runs/39124308296)，[main CI #39124955967](https://github.com/CoderLambert/news-aggregator/actions/runs/39124955967)：已完成域名核验后才允许跨来源标题证据；其余可信来源、手工覆盖、弱提示、隔离与只读路径沿用现有实现。真实数据和人工验收 `NOT_RUN` |
| BYOK T03 五用途模型偏好与快照 | `IMPLEMENTED / TESTED`（离线合成） | [PR #114](https://github.com/CoderLambert/news-aggregator/pull/114)，head `0b943da4af5031ecc16162956cd065282e21e98d`，Squash `c51dceb3d10a22e8164d35cea256395b3fd165a4`，[PR CI #39138340014](https://github.com/CoderLambert/news-aggregator/actions/runs/39138340014) 通过：后端混合 2512 passed / 16 skipped，前端 665 passed / 96 files，镜像与隔离 G1 PASS；主线 [push CI #39138991501](https://github.com/CoderLambert/news-aggregator/actions/runs/39138991501) 须单独确认。五项完整 CAS 保存、owner/CSRF、可信模型与真实 T02 attempt 能力验证、深研工具门禁及不可变选择快照均已交付。真实调用/业务 Worker/UAT `NOT_RUN`，`ai_execution.py` 仍 fail-closed |
| RSS T21 OPML 预览/确认/导出/恢复 UI | `IMPLEMENTED / TESTED`（差额） | **正式编号 T21 属于 OPML，不是频道发现（T20）**。现有 API/XML/owner/队列和界面保留；[PR #113](https://github.com/CoderLambert/news-aggregator/pull/113)，head `37692e07631677c219574db31564251b048cbb6a`，Squash `930d7eb1b80e9b511634ebcc1ed72eecb1509ae7`，[PR CI #39138391177](https://github.com/CoderLambert/news-aggregator/actions/runs/39138391177) 前端 662 passed / 95 files，[main CI #39138781175](https://github.com/CoderLambert/news-aggregator/actions/runs/39138781175) PASS。现在能在确认响应未知时用原预览 ID GET 对账并在未确认时返回原预览，不重复发送付费/网络请求。真实 OPML 浏览器 UAT `NOT_RUN` |

**不能混淆：** T01 连接及共享 Worker 安全合同已交付，**T03 已提供持久用途偏好和不可变安全选择快照，但具体业务 Worker 仍须分别由 T04/T05/T09 等业务卡接入验证**。T01 整体业务闭环仍是 `PARTIAL/BLOCKED`，并非“重新实现 T01”！`ai_execution.py` 在业务用途执行链未完成授权与消费前继续 fail-closed，不恢复旧 `UserProviderCredential`、站点 Key 回退；ChatGPT Subscription 独立。

第 6 批离线代码基线与门禁：AG-02 [PR #110](https://github.com/CoderLambert/news-aggregator/pull/110) / [main CI #39124955967](https://github.com/CoderLambert/news-aggregator/actions/runs/39124955967)；T02 [PR #111](https://github.com/CoderLambert/news-aggregator/pull/111) / [PR CI #39125387435](https://github.com/CoderLambert/news-aggregator/actions/runs/39125387435)，合并 main@`a006c59a7a24fa782f3e691872d9fb02058ae4b0` 的 [push CI #39136578514](https://github.com/CoderLambert/news-aggregator/actions/runs/39136578514) 已 PASS。禁止将单测、合成 G1、Proxy 传输 stub 称为真实 Provider/浏览器验收。

第 5 批最终证据：[主线 CI #39102973310](https://github.com/CoderLambert/news-aggregator/actions/runs/39102973310)；后续代码/CI 优化通过 [#106](https://github.com/CoderLambert/news-aggregator/pull/106)、[#107](https://github.com/CoderLambert/news-aggregator/pull/107) 合入。CI Job 路由以 [配置说明](../../ops/ci/change-routing.md) 为准；这些都是合成/离线门禁，不是厂商、生产或人工 UAT 通过。

第 7 批交付门禁：RSS T21 [main CI #39138781175](https://github.com/CoderLambert/news-aggregator/actions/runs/39138781175) PASS；BYOK T03 [PR CI #39138340014](https://github.com/CoderLambert/news-aggregator/actions/runs/39138340014) PASS，合并 `main@c51dceb3d10a22e8164d35cea256395b3fd165a4` 的 [push CI #39138991501](https://github.com/CoderLambert/news-aggregator/actions/runs/39138991501) 本次记录时仍在进行，**不可标 PASS**。这仍不是真实供应商、生产、浏览器或模型业务端到端验收。

## 2. 第 7 批后的下一批候选（最多两个独立写入目标）

| 顺序 | 原编号与目标 | 需要完成的真正差额 | 阶段验收 |
|---|---|---|---|
| 第 8 批候选 A | **BYOK T04 个人模型新闻问答** | 以现行 T03 `resolve_task_model` + T01 Worker 围栏接入文章阅读器与 per-turn 问答；核查旧 PR #38 只提取真实差额；不得绕过 SSE 终态与文章 ACL | 用户/文章版本/模型尝试/取消/重试负例 + 合成网关，无真实付费上游 |
| 第 8 批候选 B | **RSS T09 正文/元数据写入一致性差额** | 先核对当前正文版本、主来源/非主写入、同正文元数据变化与重试提交围栏；仅补实际代码与合成回归 | SQLite 版本/内容读取/安全负例、RSS 原验收矩阵 A09；不提前切源 |
| 后续 | BYOK T05–T12 | `NOT_COMPLETE/NEEDS_AUDIT`；T04 稳定集成后再分别实现私人翻译、研究、恢复、推荐与用量 | 不将旧 PR #33–#45 直接合入；保留业务授权与终态 |
| 后续 | RSS T11/T14/T27 | `NEEDS_AUDIT`；已有引擎同步/正文权限/AI 消费代码，待核对依赖与最小差额，不重新发明编号 | 正文版本、权限、消费一致性、任务恢复及相关测试 |
| 后续 | AG-03–AG-07 | `NEEDS_AUDIT`；已有 UI、人工审核和队列等部分代码，不能因存在组件就声明完成 | 按 AG 合同逐项核查 |
| 统一最终验收 | RSS T18/T24/T26/T27/T29–T33、BYOK T13/T14、AG-00/07、NH28–NH31 | `NOT_RUN` 的真实厂商、生产数据迁移、真实来源、容量、浏览器/移动端 UAT | 不以合成 G1/SSE 冒充正式生产与真实流式验收 |

**并行边界：** 两个独立目标可以并行，只读审计可分开；`models.py`、URL、迁移、锁文件、共享夹具的写入须由一个任务串行整合。表格只是开发建议，不等于启动新功能或授权付费/生产操作。

## 3. 保留原合同及编号

| 工作流 | 权威任务与架构 |
|---|---|
| RSS T00–T36 | [架构](rss-engine-migration/ARCHITECTURE.md)、[原任务](rss-engine-migration/TASKS.md)、[验收矩阵](rss-engine-migration/ACCEPTANCE-MATRIX.md)；Miniflux + PostgreSQL 为独立 RSS 引擎目标，NewsHub 主库仍 SQLite。旧 Scrapy/全文路径只作迁移兼容，退出属于 T29–T33 |
| BYOK T00–T14 + T00-G | [原合同（冻结参考）](https://github.com/CoderLambert/news-aggregator/tree/ed58afa7a72ae905e2a2ffc315d968ca3634b8f2/docs/features/byok)、[T01 Worker](../features/byok/T01-WORKER-FENCING-2026-10-18.md)、[T00 探针](../../tools/byok_t00_probe/README.md)；官方 SDK→LiteLLM Proxy，不能恢复旧 Key 连接路径 |
| 智能频道 AG-00–AG-07 | [Issue #55](https://github.com/CoderLambert/news-aggregator/issues/55)、[AG-01](../features/smart-channels/AG-01-2026-10-18.md)；人工审核、公共来源证据和私人分组不能混淆 |
| 最终发布 | [NH28–31](../deployment/NH28-NH31-operator-acceptance.md)、RSS/BYOK 原验收矩阵；无重复发布验收编号 |

BYOK 依赖：T02 ← T01/T00；T03 ← T02；T04 ← T03/T00；T05 ← T04；T06/T07 ← T05；T08 ← T05/T07；T09 ← T03/T00；T10 ← T09；T11 ← T04；T12 ← T02/T04/T05/T09/T11；T13/T14 为最终验收。T00-G 运维交付独立跟踪，生产网关部署不阻塞离线业务开发。

旧 Issue/PR 清理建议与 2026-10-17 原任务审计保存在[历史快照](archive/FEATURE-DEVELOPMENT-SNAPSHOT-2026-10-17.md)。本次仅清理文档，不批量关闭旧 Issue/PR。

## 4. 每批验收记录

开工重新核对最新 main、相关代码和合同，记录 `原 ID → 现存实现 → 缺口 → 受影响文件/接口 → 专项/负例测试 → PR/head SHA`。单独区分 `IMPLEMENTED`、`TESTED`、`PARTIAL`、`BLOCKED`、`NOT_RUN` 与 `ACCEPTED`；新功能验收需更新**本文件**而非历史快照。未经授权不触碰真实凭据、生产库、生产切源或付费请求。
