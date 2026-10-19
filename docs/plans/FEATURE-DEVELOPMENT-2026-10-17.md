# NewsHub 现行开发任务与合同索引

> **更新于 2026-10-19**；当前主线最新适用全量门禁通过基线：`main@27c5b6b2b9bf22f95c99e9b5602296236e2486d1`（[PR #131 全量 CI #39207985870](https://github.com/CoderLambert/news-aggregator/actions/runs/39207985870) 与 [main Push CI #39208921110](https://github.com/CoderLambert/news-aggregator/actions/runs/39208921110) 均 SUCCESS；`changes`、`backend-and-release-gates`、`merge-gate` 成功，前端作业因后端单域变更被跳过；后端 pytest `2483 passed / 16 skipped`、xdist 对账 `2565 passed / 16 skipped`，T00 合成 SDK/Proxy `239/239 PASS`，隔离 G1 实际镜像 revision 为 `27c5b6b2b9bf22f95c99e9b5602296236e2486d1`）。注意较早的 `main@5770062ad10d923ca28c90fe4a4f3709adc30939` 主线 Push CI #39205855011 曾因 T05 并发任务用例/SQLite 锁竞争失败；该失败仍记录为已知间歇问题，PR #130 尚未合并，不能因为后续一次主线通过就宣称已解决。每次开工仍必须重新读取最新 main。**本文件是当前任务状态唯一入口**；[2026-10-17 原计划和旧批次记录已完整归档](archive/FEATURE-DEVELOPMENT-SNAPSHOT-2026-10-17.md)，其中的“下一批/T01 待完成/旧凭据并存”属于历史快照，不再指导开发。

## 1. 当前已验证交付与未完成边界

| 原任务 | 当前状态 | 证据、边界 |
|---|---|---|
| BYOK T01 连接与旧单 Key 退出 | `IMPLEMENTED / TESTED` | [PR #103](https://github.com/CoderLambert/news-aggregator/pull/103)：`UserAIConnection` 是唯一现行个人连接身份；`0061` 原子迁移旧密文、默认停用，生产迁移未授权 |
| BYOK T01 通用 Worker 围栏 | `IMPLEMENTED / TESTED` | [PR #105](https://github.com/CoderLambert/news-aggregator/pull/105)、[合同](../features/byok/T01-WORKER-FENCING-2026-10-18.md)：owner/epoch/version，enqueue/claim/retry/send/commit 保护 |
| AG-01 来源主题元信息 | `IMPLEMENTED / TESTED` | [PR #104](https://github.com/CoderLambert/news-aggregator/pull/104)、[合同](../features/smart-channels/AG-01-2026-10-18.md)：域名真实性、版本化证据、人工审核、幂等及 GET 无副作用 |
| RSS T20 订阅发现错误恢复 | `IMPLEMENTED / TESTED`（差额） | [PR #94](https://github.com/CoderLambert/news-aggregator/pull/94)：按失败阶段恢复；不代表 RSS 最终切源/发布验收通过 |
| BYOK T00 SDK/Proxy 进程 | `PARTIAL` | [PR #95](https://github.com/CoderLambert/news-aggregator/pull/95)：合成 `SDK_LOCAL / PROXY_PROCESS_LOCAL` 通过；真实上游/正式镜像合同/运维均尚未完整验收 |
| BYOK T02 个人模型配置和显式能力探针 | `IMPLEMENTED / TESTED`（离线合成） | [PR #111](https://github.com/CoderLambert/news-aggregator/pull/111)，head `ae8825b024716c6c6fd31bfdec64be39727a84cc`，Squash `a006c59a7a24fa782f3e691872d9fb02058ae4b0`，[CI #39125387435](https://github.com/CoderLambert/news-aggregator/actions/runs/39125387435)：后端与发布门禁、前端通过；[main CI #39136578514](https://github.com/CoderLambert/news-aggregator/actions/runs/39136578514) 已 PASS。保留 `ai_execution.py` fail-closed；真实 Provider/浏览器 UAT `NOT_RUN`。T03 已保存用途偏好；T04 已接通离线验证的文章问答，其他业务消费者仍须分别验证 |
| AG-02 离线规则和可信证据 | `IMPLEMENTED / TESTED`（差额） | [PR #110](https://github.com/CoderLambert/news-aggregator/pull/110)，head `cf9e8169ec0f37c1bc5677dbff7a005637d718bf`，Squash `36deba6779f4c3527c5b07fb22a6a8487e62b516`，[CI #39124308296](https://github.com/CoderLambert/news-aggregator/actions/runs/39124308296)，[main CI #39124955967](https://github.com/CoderLambert/news-aggregator/actions/runs/39124955967)：已完成域名核验后才允许跨来源标题证据；其余可信来源、手工覆盖、弱提示、隔离与只读路径沿用现有实现。真实数据和人工验收 `NOT_RUN` |
| BYOK T03 五用途模型偏好与快照 | `IMPLEMENTED / TESTED`（离线合成） | [PR #114](https://github.com/CoderLambert/news-aggregator/pull/114)，head `0b943da4af5031ecc16162956cd065282e21e98d`，Squash `c51dceb3d10a22e8164d35cea256395b3fd165a4`，[PR CI #39138340014](https://github.com/CoderLambert/news-aggregator/actions/runs/39138340014) 通过：后端混合 2512 passed / 16 skipped，前端 665 passed / 96 files，镜像与隔离 G1 PASS；主线 [push CI #39138991501](https://github.com/CoderLambert/news-aggregator/actions/runs/39138991501) 已通过（changes、frontend、backend-and-release-gates 均 SUCCESS）。五项完整 CAS 保存、owner/CSRF、可信模型与真实 T02 attempt 能力验证、深研工具门禁及不可变选择快照均已交付。真实调用/业务 Worker/UAT `NOT_RUN`，`ai_execution.py` 仍 fail-closed |
| RSS T21 OPML 预览/确认/导出/恢复 UI | `IMPLEMENTED / TESTED`（差额） | **正式编号 T21 属于 OPML，不是频道发现（T20）**。现有 API/XML/owner/队列和界面保留；[PR #113](https://github.com/CoderLambert/news-aggregator/pull/113)，head `37692e07631677c219574db31564251b048cbb6a`，Squash `930d7eb1b80e9b511634ebcc1ed72eecb1509ae7`，[PR CI #39138391177](https://github.com/CoderLambert/news-aggregator/actions/runs/39138391177) 前端 662 passed / 95 files，[main CI #39138781175](https://github.com/CoderLambert/news-aggregator/actions/runs/39138781175) PASS。现在能在确认响应未知时用原预览 ID GET 对账并在未确认时返回原预览，不重复发送付费/网络请求。真实 OPML 浏览器 UAT `NOT_RUN` |

**不能混淆：** T01 连接及共享 Worker 安全合同已交付，T03 已提供持久用途偏好和不可变安全选择快照，T04 文章问答与 T05 私人全文翻译均已实现并通过离线合成验证；T09 等其他业务消费者仍须分别审计/接入验证。T01 整体业务闭环仍是 `PARTIAL/BLOCKED`，并非“重新实现 T01”！`ai_execution.py` 在未完成各业务用途授权与消费前继续 fail-closed，不恢复旧 `UserProviderCredential`、站点 Key 回退；ChatGPT Subscription 独立。

第 6 批离线代码基线与门禁：AG-02 [PR #110](https://github.com/CoderLambert/news-aggregator/pull/110) / [main CI #39124955967](https://github.com/CoderLambert/news-aggregator/actions/runs/39124955967)；T02 [PR #111](https://github.com/CoderLambert/news-aggregator/pull/111) / [PR CI #39125387435](https://github.com/CoderLambert/news-aggregator/actions/runs/39125387435)，合并 main@`a006c59a7a24fa782f3e691872d9fb02058ae4b0` 的 [push CI #39136578514](https://github.com/CoderLambert/news-aggregator/actions/runs/39136578514) 已 PASS。禁止将单测、合成 G1、Proxy 传输 stub 称为真实 Provider/浏览器验收。

第 5 批最终证据：[主线 CI #39102973310](https://github.com/CoderLambert/news-aggregator/actions/runs/39102973310)；后续代码/CI 优化通过 [#106](https://github.com/CoderLambert/news-aggregator/pull/106)、[#107](https://github.com/CoderLambert/news-aggregator/pull/107) 合入。CI Job 路由以 [配置说明](../../ops/ci/change-routing.md) 为准；这些都是合成/离线门禁，不是厂商、生产或人工 UAT 通过。

第 7 批交付门禁：RSS T21 [main CI #39138781175](https://github.com/CoderLambert/news-aggregator/actions/runs/39138781175) PASS；BYOK T03 [PR CI #39138340014](https://github.com/CoderLambert/news-aggregator/actions/runs/39138340014) PASS，合并 `main@c51dceb3d10a22e8164d35cea256395b3fd165a4` 的 [push CI #39138991501](https://github.com/CoderLambert/news-aggregator/actions/runs/39138991501) 已 PASS（changes、frontend、backend-and-release-gates 三个 Job 均成功）。这仍不是真实供应商、生产、浏览器或模型业务端到端验收。

## 1.1 第 8 批实际交付与明确未完成边界（2026-10-19）

| 项目（保留原编号） | 状态 | HEAD、CI、风险与验收 |
|---|---|---|
| **RSS T09** 正文/元数据同步两次读取围栏差额 | `IMPLEMENTED / TESTED`（已合并的差额） | [PR #117](https://github.com/CoderLambert/news-aggregator/pull/117) head `dbbde844e1656b78f020e838742398b3c9ac5757`，Squash `538185bc4b6e2723c9f64545f1fad71c84b6206e`；[PR CI #39152816747](https://github.com/CoderLambert/news-aggregator/actions/runs/39152816747) 后端 2517 passed/16 skipped、生产镜像/隔离 G1 PASS（前端因后端单域变更被正确跳过），[main CI #39161898261](https://github.com/CoderLambert/news-aggregator/actions/runs/39161898261) SUCCESS。补充 Source 名称/URL/地区及 News 来源/分类快照的陈旧写入拒绝；原 T09 的真实 RSS 与发布验收 `NOT_RUN` |
| **BYOK T04** 个人模型新闻问答 | `IMPLEMENTED / TESTED`（离线合成，已合并）；真实验收 `NOT_RUN` | [PR #118](https://github.com/CoderLambert/news-aggregator/pull/118) 最终 head `9d2f10a7d62d1e10bb84e74750fda5da01b0f4cc`，Squash `35017836a4260904bf4c6d0c67d26704cf613322`；[Ready 全量 CI #39190496763](https://github.com/CoderLambert/news-aggregator/actions/runs/39190496763) 与 [main Push CI #39191215473](https://github.com/CoderLambert/news-aggregator/actions/runs/39191215473) 均 SUCCESS。个人模型显式选择、可信 T02/T03 绑定、T01 owner/epoch 围栏、逐次收费确认、持久取消 CAS、历史清空/提交竞态、真实 SDK 流及原生终态证明已实现；[Issue #121](https://github.com/CoderLambert/news-aggregator/issues/121) 的取消/流式代码缺口已解决。真实收费 API、并发真实账户、生产与浏览器 UAT `NOT_RUN`，不声明 `ACCEPTED` |
| **BYOK T05** 有界私人全文翻译 | `IMPLEMENTED / TESTED`（离线合成已合并）；真实 Provider/凭据、生产迁移/部署与人工浏览器 UAT `NOT_RUN` | [PR #127](https://github.com/CoderLambert/news-aggregator/pull/127) head `822aa6a3b261349956e317c1ac2b6b58be0ee185`，Squash `675a846fc6dd8f58fe80e18950679fc9ca5032f8`；[PR CI #39200592175](https://github.com/CoderLambert/news-aggregator/actions/runs/39200592175) 与 [main Push CI #39201460890](https://github.com/CoderLambert/news-aggregator/actions/runs/39201460890) 均 SUCCESS。BYOK/订阅凭据 XOR；显式模型选择与逐次收费同意；依赖 T02 能力、T03 选择快照和 T01 owner/epoch 围栏；GET/SSE 不触发上游，未知已派发结果不自动重发，SQLite 仅作有界 DB-only 重试。稍后的 `main@577` 用例竞争失败见第 1.3 节；后续通过不抹去该失败证据 |
| **CI 开发/合并双阶段**（CI 规范，非新业务编号） | `IMPLEMENTED / TESTED`（离线与 GitHub Actions 实测） | [PR #123](https://github.com/CoderLambert/news-aggregator/pull/123)，head `373b67383cf1201ec5a020519b447c60cda93c0e`，Squash `3e7d80d2b24c0a22ef7104b637e203e24a16b976`。Draft [首次快检 #39166918371](https://github.com/CoderLambert/news-aggregator/actions/runs/39166918371) 49 秒、changes/dev-frontend/dev-backend SUCCESS，完整 Job SKIPPED；只改后端单文件的 Draft [增量 #39167054338](https://github.com/CoderLambert/news-aggregator/actions/runs/39167054338) 42 秒，`frontend=false/backend=true`、仅 dev-backend 通过。Ready [PR 完整 CI #39167139417](https://github.com/CoderLambert/news-aggregator/actions/runs/39167139417) 全部适用全量 Job 和 `merge-gate` SUCCESS（前端 667 passed / 96 files，后端 2517 passed / 16 skipped、合成生产镜像与隔离 G1 PASS）；[main Push CI #39167643161](https://github.com/CoderLambert/news-aggregator/actions/runs/39167643161) 再次 SUCCESS。新 PR 默认 Draft；准备合并转 Ready，修改后退回 Draft。**未启用 branch protection 必需检查的硬门禁**，合并操作者仍需确认最新 HEAD/BASE、全量 SUCCESS 和 review；真实生产、收费上游与主机网络变更 `NOT_RUN` |
| **CI 基础设施故障恢复**（不新增业务编号） | `IMPLEMENTED / TESTED`（代码/离线）；宿主机 `NOT_RUN` | 两个 Omarchy Runner 的 MTU=1500 Bridge TLS 握手超时已用容器 eth0=1280 临时验证恢复；[PR #120](https://github.com/CoderLambert/news-aggregator/pull/120) head `0711d55cdb19c42fa4d560764f2fbaa994ef4600`，Squash `e5599a3698899eab4cf0dfbdde50b69cece3d243`，[PR CI #39162978737](https://github.com/CoderLambert/news-aggregator/actions/runs/39162978737) 全部门禁 SUCCESS。现仅源码默认 Bridge MTU=1280；在 Omarchy 空闲状态应用新 Compose 网络、复核真实两台 Runner Online 和精确 CI 为 `NOT_RUN`，禁止 CI Busy 时重建 |

**本批风险边界：** RSS #117 仅完成同步一致性最小差额；BYOK #118 已合并且主线离线全量门禁通过，但真实收费 API/生产/UAT 仍未验收；#120 仅提交独立 CI 网络设置及离线门禁，没有远程操作生产、宿主 Docker 或 Runner 重启。此处 `TESTED` 均指真实执行的合成/离线 CI，不代表生产验收。

**T04 精确证据与运行边界：** PR 全量和合并后主线均为前端 **683 tests / 100 files**、后端 **2537 passed / 16 audited skips**（2553 collected/executed identities 对账，无测试重试），SDK/Proxy **239/239 PASS**；Django→真实 SDK→本地 Proxy→合成上游 E2E **1 passed**（主线 20.85 秒），覆盖成功持久化、EOF 失败、关闭连接与显式取消。生产镜像构建和隔离 G1 均 PASS，主线 G1 核对实际 revision `35017836a4260904bf4c6d0c67d26704cf613322`；这不是生产部署或真实厂商验收。

- 流式路由仅允许已证明能力的精确 `deepseek/deepseek-flash`，使用新的 T02 能力证明，不把旧 `deepseek-chat` 静默改名或复用旧证明；原生 `finish_reason='stop'` 证明不能由 LiteLLM 合成 `[DONE]` 替代。
- 迁移 `0064_article_chat_turn` 提供持久 owner-scoped turn/CAS 状态；仅合成 CI 数据库验证，生产迁移 `NOT_RUN`。回滚应用时保留 turn 表和取消/完成记录，不以删数据回滚。
- 已确认取消先于最终提交时禁止成功助手记录；已提交则如实返回 `already_completed`。客户端停止等待、服务端确认取消、结果未知必须区分；已经派发的请求不能承诺撤销供应商计费，未知结果不能自动重发。
- 文章权限/内容及 `policy_versions` 在提交时重查。SQLite BUSY/LOCKED 仅在整笔终态事务已回滚后作有限 DB-only 重试，重查 owner/凭据/文章围栏，不重放 SDK/网络调用；真实逻辑冲突与外层事务不重试。

## 1.2 RSS T11 已合并的最小授权差额（2026-10-19）

[PR #126](https://github.com/CoderLambert/news-aggregator/pull/126) 将 Miniflux 正文来源映射绑定到当前文章 URL：仅当 `EngineEntryMap.source_url = News.url` 且原有 entry/binding 身份均匹配时，当前正文来源才授权读取。新增负例先证明经标准化的有效 URL 仍返回全文；随后只改 `News.url`、保留旧 entry 映射与已接受正文来源，访问被拒并退化为 summary（无 provenance/body owner）。legacy-origin 读取保持不变；仅修改 `backend/api/rss/access.py` 与 `backend/api/tests/rss/test_access_contract.py`，无模型或迁移变更。head `e845f06e511433701f90bf1affa15cff924a4376`，Squash 合并为 `c35d10379684383363f20d9d12abd43168bcb560`。

验证：[PR 全量 CI #39192213193](https://github.com/CoderLambert/news-aggregator/actions/runs/39192213193) 与 [main Push CI #39192796936](https://github.com/CoderLambert/news-aggregator/actions/runs/39192796936) 均 SUCCESS；主线后端 xdist 覆盖 `2538 passed / 16 skipped`（2554 个测试身份对账、无重试），T00 SDK/Proxy `239/239 PASS`，生产镜像与隔离 G1 PASS，G1 核实实际 revision 为 `c35d10379684383363f20d9d12abd43168bcb560`。两次 run 的前端作业均为 SKIPPED，不能记作前端 PASS。真实 RSS/Miniflux、生产切源及真实浏览器/来源 UAT `NOT_RUN`；此项仅证明最小 URL 绑定差额，不代表 T11 全部合同已验收。

## 1.3 BYOK T05 与 RSS T14 更新证据（2026-10-19）

BYOK T05 有界私人全文翻译已在 [PR #127](https://github.com/CoderLambert/news-aggregator/pull/127) 合并（head `822aa6a3b261349956e317c1ac2b6b58be0ee185`，Squash `675a846fc6dd8f58fe80e18950679fc9ca5032f8`）；[PR CI #39200592175](https://github.com/CoderLambert/news-aggregator/actions/runs/39200592175) 与该合并的 [main Push CI #39201460890](https://github.com/CoderLambert/news-aggregator/actions/runs/39201460890) 均 SUCCESS。已实现的 T05 范围使用现有 task/result 身份，绑定 T02/T03/T01 安全快照与文章当前全文权限/版本；合成离线 SDK/Proxy 验证通过。真实 Provider/凭据、生产迁移/部署和人工浏览器 UAT 仍 `NOT_RUN`，不声明 `ACCEPTED`。

RSS T14 的两项本地回放差额现已合并，但仅关闭该条窄证据路径：[PR #129](https://github.com/CoderLambert/news-aggregator/pull/129) head `c11d583e4228f1c018a4450be11a0ec6db79864a`，Squash `5770062ad10d923ca28c90fe4a4f3709adc30939`，[PR 全量 CI #39204773850](https://github.com/CoderLambert/news-aggregator/actions/runs/39204773850) SUCCESS；它在 `search_news/analyze_topic` 文章行与独立时间线事件上回放时重查 StoredArticle 快照/授权、标题摘要 URL、scope 与 `policy_versions`，旧无快照证据 fail closed。该合并的 [main Push CI #39205855011](https://github.com/CoderLambert/news-aggregator/actions/runs/39205855011) **FAILURE**：`test_concurrent_identical_posts_and_worker_claims_send_once` 断言 `0 != 1`，日志同时记录 T05 admission/claim 阶段的 `SQLITE_LOCKED_SHAREDCACHE` 重试；这是已观察的 T05 首次派发前 `prepare_dispatch`/admission 阶段 SQLite 凭据/数据库锁竞争，不是 GET 轮询失败。PR #129 的有界 GET-only 轮询重读已随 `main@577` 合并，属于合成测试辅助器，不覆盖派发前数据库锁竞争。[PR #130](https://github.com/CoderLambert/news-aggregator/pull/130) 仍开放，待处理的是 `prepare_dispatch`/fresh-fence 的 DB-only 重试差额，不是 GET poll；在该修正合并并经适用门禁验证前，不宣称此间歇失败已解决。

[PR #131](https://github.com/CoderLambert/news-aggregator/pull/131) 在同一 T14 本地回放合同下补足 `fetch_article` / 已索引 `fetch_webpage` 完整序列化载荷核验，包括 `_truncate_result` 变换、标题/URL/来源/发布时间与 `policy_versions`；长正文 envelope-only、结果行-only、仅标题/URL变化及仅策略版本变化负例通过。head `2a09e39bcbdc929763f54f962bbd8b61f6aac24f`，Squash `27c5b6b2b9bf22f95c99e9b5602296236e2486d1`；[PR 全量 CI #39207985870](https://github.com/CoderLambert/news-aggregator/actions/runs/39207985870) 与 [main Push CI #39208921110](https://github.com/CoderLambert/news-aggregator/actions/runs/39208921110) 均 SUCCESS。该主线 run 的 frontend jobs 被跳过；隔离 G1 实际镜像 revision 为 `27c5b6b2b9bf22f95c99e9b5602296236e2486d1`。此证据只证明本地研究证据回放差额已实现并通过合成/离线 CI，不代表完整 T14/A11 或 T27 真实来源/浏览器验收；当前最新 main 通过也不删除前述 `main@577` 失败记录。

## 1.4 2026-10-20 连续功能迭代

- BYOK T06（#130 / `b9d8f94`）、T07（#133 / `ec5ae59`）、T08（#134 / `462619b`）已合入；下方旧候选列表中的 T06–T12 需据此理解为逐项差额，不能重新实现 T06–T08。
- BYOK T09 已合并 [#135](https://github.com/CoderLambert/news-aggregator/pull/135)，main `988c4c4`。精确 head `ec7f0e1` 的 Draft 快检通过；Ready 全量 CI #39260053906 的两个实际执行作业均因 self-hosted Runner 失联失败，日志 annotations 已核实，未取得全量通过。按用户本轮明确授权跳过此已知基础设施问题并直接合并；没有将失败改称通过，也未修改 CI 门禁配置。
- BYOK T10 本批实现：同一会话锁定原模型，明确同意的续问 POST 复用服务端版本化 native continuation；原生 reasoning/tool 调用历史不进入可见消息 DTO；完成历史/native 状态/终态事件在原 run-token/lease CAS 与凭据围栏下原子提交。GET/SSE 保持只读，BYOK 队列恢复仍不自动派发；无法确认的运行不自动重发。旧无 native continuation 的会话只读保留，必须新建研究以建立安全续接。
- 本地验证：前端 typecheck 与既有 ResearchPanel/API 定向 30 项通过；新续问场景 1 PASS，生产前端 build PASS；原生 helper 模型/协议负例 PASS（未运行 Django/数据库）。后端当前解释器缺少 pytest/PyYAML，数据库回归 NOT_RUN；不安装/重建环境，不触碰真实数据库或 Provider。真实厂商、生产迁移/部署、浏览器 UAT 仍 NOT_RUN。

### BYOK T11 私有推荐问题（2026-10-20）

- T10 已合并 [#136](https://github.com/CoderLambert/news-aggregator/pull/136)，main `033bfad`；沿用本轮授权按批集中 CI。
- T11 首次加载切为 GET，仅读取 owner 私有缓存或免费模板；POST 显式携带个人模型与 consent:true 后才生成。保留旧订阅 POST API，个人输出不再写入 News 共享问题缓存。
- 私有缓存按 owner/news/原文与元数据及权限摘要/模型执行摘要/prompt_version 隔离；模型、凭据和文章在发送前及保存时重检。沿用既有预算，个人生成窗口进一步隔离到 owner/model；GET 不占推理额度、不派发。
- 前端用途偏好绑定、每次费用确认、生成/换批与来源、错误提示已接通；类型检查 PASS，相关前端 18 项最终 PASS（首次 hook 验证发现偏好加载状态与 mock 隔离问题，已修正并仅重跑该文件 8 项）；前端生产 build PASS；实际 JSON 解析负例与 Python 语法 PASS。后端 Django/数据库回归、真实 Provider/生产/UAT NOT_RUN。

### BYOK T12 个人使用记录（2026-10-20）

- T11 已合并 [#137](https://github.com/CoderLambert/news-aggregator/pull/137)，main `f5a1b4b`。
- T12 新增仅含 owner/用途/模型/时间/状态/可知 Token 的业务 AICallAttempt；复用现有 T02 AIModelProbeAttempt 展示真实既有探针，不补造历史业务消耗，not_sent 探针不计入调用。
- 文章问答、每个翻译分段、每次研究工具轮次与推荐生成均在实际 SDK create 边界记录一次。流式明确请求已有 Proxy 支持的 usage 帧；无 usage/断线/异常/进程中断保留 NULL 或未知。写统计失败不重发模型请求、不丢弃成功业务响应。
- `GET /api/me/ai/usage/` 严格按当前 owner 查询，只读无推理，返回全部累计已知 Token/未知次数及最近最多 100 条记录；设置页展示最近 50 条、用途/模型/状态与未知 Token，不估算账户余额或费用。
- 本地 typecheck、相关设置页/使用记录 16 项、前端生产 build PASS；实际统计函数隔离执行确认一次发送/一次记录、0 与未知分离、断线无伪完成、关闭不重复与用途不匹配拒绝。Python AST/diff PASS。后端数据库/API 回归、真实厂商、生产迁移与浏览器 UAT NOT_RUN。沿用本轮合并授权，未改 CI 工作流。

## 2. 第 8 批实施状态与后续候选（最多两个独立写入目标）

| 顺序 | 原编号与目标 | 需要完成的真正差额 | 阶段验收 |
|---|---|---|---|
| 第 8 批 A（离线交付已合并） | **BYOK T04 个人模型新闻问答** | T03 + T01 已接入文章阅读器和 per-turn 问答；取消/流式与提交围栏差额由 #118 完成，证据见上；真实验收仍独立保留 | 用户/文章版本/模型尝试/取消/重试负例及 SDK→本地 Proxy→合成上游通过；真实付费上游/UAT `NOT_RUN` |
| 第 8 批 B（差额已合并） | **RSS T09 正文/元数据写入一致性差额** | 先核对当前正文版本、主来源/非主写入、同正文元数据变化与重试提交围栏；仅补实际代码与合成回归 | SQLite 版本/内容读取/安全负例、RSS 原验收矩阵 A09；不提前切源 |
| 后续 | BYOK T13/T14 及 T06–T12 批次验证 | T06–T09 已分别合并；T10–T12 本轮按当前主线实现并提交，前端/纯逻辑定向已验证，后端数据库回归与全量 CI 待集中验证。真实厂商矩阵、部署/人工验收未完成 | 按第 1.4 节与各任务记录区分已实现和 NOT_RUN；不重复移植旧 PR #33–#45 |
| 后续 | RSS T11/T14/T27 | T11 Miniflux URL 来源绑定最小差额 `IMPLEMENTED / TESTED`（#126）；T14 本地搜索/正文回放新差额（#129/#131）已 `IMPLEMENTED / TESTED`，但原 T14/A11 的广泛 AI/TTS 上下文消费与译文版本读回仍 `NEEDS_AUDIT`；T27 真实来源/浏览器联合最终验收 `NOT_RUN` | 继续按 T11/A08、T14/A11 与 T27/A15 合同核验权限、版本、撤权和消费者一致性；合成 CI/G1 不等于正式验收 |
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
