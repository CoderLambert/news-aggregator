# NewsHub 现行开发任务与合同索引

> 2026-10-20 当前验收：远程 main `6a2cc025c338ef0308024151be4fbd796f7f3a39`；完整后端 2686 PASS / 16 SKIP、前端 730 PASS、T00 241/241、固定 Proxy 与 SDK 联合流程、隔离 G1/G2 和移动视口功能已验证，范围与历史失败见[集中记录](../verification/consolidated-acceptance-2026-10-20.md)。下文各批次 NOT_RUN 属于相应历史快照，不能覆盖最新证据。T31 已在 [Draft PR #154](https://github.com/CoderLambert/news-aggregator/pull/154) 隔离候选分支开发，真实 T30 门禁前不合并；正式 CI、生产、其他真实凭据与人工签署仍未完成，见[剩余确认清单](../verification/OWNER-ACCEPTANCE-2026-10-20.md)。

> **更新于 2026-10-20**；历史全量门禁通过基线记录（非当前 main 的验收）：`main@27c5b6b2b9bf22f95c99e9b5602296236e2486d1`（[PR #131 全量 CI #39207985870](https://github.com/CoderLambert/news-aggregator/actions/runs/39207985870) 与 [main Push CI #39208921110](https://github.com/CoderLambert/news-aggregator/actions/runs/39208921110) 均 SUCCESS；`changes`、`backend-and-release-gates`、`merge-gate` 成功，前端作业因后端单域变更被跳过；后端 pytest `2483 passed / 16 skipped`、xdist 对账 `2565 passed / 16 skipped`，T00 合成 SDK/Proxy `239/239 PASS`，隔离 G1 实际镜像 revision 为 `27c5b6b2b9bf22f95c99e9b5602296236e2486d1`）。注意较早的 `main@5770062ad10d923ca28c90fe4a4f3709adc30939` 主线 Push CI #39205855011 曾因 T05 并发任务用例/SQLite 锁竞争失败；该失败仍记录为已知间歇问题，该故障记录时 PR #130 尚未合并；现 #130 已以 `b9d8f94` 合并，见第 1.4 节，本轮数据库回归未运行，不能因此宣称所有锁竞争都已消失。每次开工仍必须重新读取最新 main。**本文件是当前任务状态唯一入口**；[2026-10-17 原计划和旧批次记录已完整归档](archive/FEATURE-DEVELOPMENT-SNAPSHOT-2026-10-17.md)，其中的“下一批/T01 待完成/旧凭据并存”属于历史快照，不再指导开发。

**本轮代码交付及后续差额见第 1.4 节；完整 CI、真实环境和发布验收仍未通过；完整原编号核对见[当前交付与剩余执行门禁](DELIVERY-AND-REMAINING-GATES-2026-10-20.md)。下面早期批次证据不替代该边界。**

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

**不能混淆：** T01 连接/Worker 与 T02/T03 模型能力/选择快照已有实现；文章问答、翻译、研究、推荐及 AG 分类已分别接入现行授权路径，近期交付见第 1.4 节。整体真实业务/生产验收仍未完成，不需要重新实现 T01。旧通用 `ai_execution.py` 入口继续 fail-closed，明确业务入口使用当前快照，不恢复旧 `UserProviderCredential` 或站点 Key 回退；ChatGPT Subscription 独立。

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

### AG-05 已验证个人模型分类接线（2026-10-20）

- 基线 main `8601f45`（BYOK T12 已合并 #138）。现有频道 AI 队列已退出 fail-closed 的旧 personal_clients_for_user 入口，改用 T03 已验证模型的不可变快照与 T01 enqueue/send/commit 围栏；个人请求明确展示并提交模型与本次费用同意，公开频道资料进入现有 trusted gateway，调用纳入 T12。
- 站点后台分类使用独立保存的管理员 scope=site 模型授权与每日预算；旧 enabled 配置没有模型快照时不会派发，须重新明确保存授权。个人默认偏好后续修改不会静默替换后台模型；owner/凭据/模型、开关、来源证据与租约在发送和提交前重检。
- 0071 新增 execution_snapshot 与 dispatch_started_at。已派发/旧未知运行租约过期后失败，不自动重新付费；重复执行者受 dispatch CAS 限制；仅明确 429 依据 Retry-After 最多再尝试一次，5xx/超时/未知不自动重发。
- 原来源 GET 零推理、AI 主题 needs_review、人工覆盖优先及私人分组应用/撤销语义保留。JSON 全批来源、主题白名单、重复对象字段/主题、完整 stop 均须验证。
- typecheck、既有前端 20 项、新增模型/同意场景 1 项、生产 build、实际解析/429-vs-5xx/未知输入负例与 Python AST/diff PASS。后端 DB/API 并发/迁移回归 NOT_RUN（本地 pytest/PyYAML 缺失）；真实 Provider、管理员正式授权/后台进程、生产迁移/部署和浏览器 UAT NOT_RUN。按本轮用户授权集中 CI，不重复全量门禁。

### AG-06 增量订阅恢复与人工优先差额（2026-10-20）

- 基线 main `62225dc`（AG-05 已合并 #139）。已生成过建议的新订阅不再永久跳过：来源主题/人工确认或配置版本变化后重查，未变化的 pending/suggested 保持幂等，已 applied 的历史归组继续保留，不因后台资料更新重写。
- 取得 owner 写锁后重读账号与订阅；订阅等待期间被取消/账号停用时停止，不使用陈旧订阅对象创建状态或分组成员。已有手工移出抑制与 off/active_since 边界保留。
- 空绑定配置不消耗后台有效处理窗口。单个 owner 达到预览限额仅延期该 owner，本轮继续处理其他用户并让 channel_worker 到达后续 AI 队列；不会因统计/限额重发 Provider。
- 后端新增资料人工确认后的 auto 恢复、锁边界取消订阅、owner 限流不阻塞其他用户回归。实际增量循环函数的过期建议/幂等/已应用保留/跨 owner 限流分支与 Python AST/diff PASS；数据库回归 NOT_RUN（pytest/PyYAML 缺失）。无前端/API 格式/迁移变更，未重复前端或全量 CI。

### AG-07 分类开关、队列状态与停止操作（2026-10-20）

- 基线 main `bbb671d`（AG-06 已合并 #140）。管理员现有 GET 增加只读 runtime：授权/开关是否可派发、今日入队任务预算、各状态数量、过期租约、已派发失败及下一次等待时间；不据此宣称进程在线，GET 不修复/派发任务。
- 关闭后台、更换 owner/模型授权或降低每日预算时，在同一短事务内取消尚未完成的全站任务并撤销旧 lease；私人提案、已完成来源主题和分组不变。在途 Provider 可能计费，但旧任务不再写入来源结果。
- 重新启用时，仅绑定明确且 dispatch_started_at 为空的已取消/失败任务可作为新入队任务重新授权；新任务按当前日预算计数。任何已派发失败/未知结果仍作为自动重发屏障。
- typecheck、管理员状态 GET/显式停用场景 1 项、前端生产 build、Python AST/diff 与只读结构核对 PASS。新增全站停用不影响私人任务 DB 回归未运行（pytest/PyYAML 缺失）；实际后台 worker、Provider、生产与浏览器人工 UAT NOT_RUN，发布边界仍保留。

### RSS T14 阅读上下文与自动朗读差额（2026-10-20）

- 基线 main `ea44ba9`（AG-07 已合并 #141）。重新核对 T11/T14 原 C04/C05/C10 合同、access/stored_readers/shared_translations/research/TTS 消费链和既有专项报告；授权快照、摘要不冒充全文、hash 绑定译文/历史、无隐式来源抓取、联网搜索保留已有实现，不重复重写。
- 实测复现跨文章误播：第一篇“翻译全文并播放”尚未完成，进入已有译文的第二篇后，旧 pending scope 触发了第二篇朗读。现将等待动作绑定到已提交的 viewer/文章/正文版本与内容、读取状态、开关；切换/卸载/选择个人结果会取消旧等待，旧 Promise 不消费新动作。
- 实测复现历史译文复制不一致：正文为所选旧译文，复制按钮却写入当前推荐译文。工具栏改用正文的同一已选内容；新生成译文不再因原文 legacy 标记套用旧代码修复，仅明确 legacy 原文/绑定 legacy 译文保留该兼容行为。
- 两个缺陷均先失败复现再修正。类型检查、相关页面/个人译文按变更定向共 13 个用例均最终通过（包含原文章正常完成仅播放一次）、生产 build/diff PASS。无后端行为/API/迁移修改，未重复已知不可用的数据库或全量 CI。真实模型、TTS、RSS/浏览器联合产品验收仍 NOT_RUN，归 T27。

### 当前交付与剩余门禁总核对（2026-10-20）

RSS T14 已合并 [#142](https://github.com/CoderLambert/news-aggregator/pull/142)，main `cd83d88`。本轮代码交付、AG-03 既有功能源码复核，以及每个原编号的当前证据/未运行项目，统一见[交付与剩余执行门禁](DELIVERY-AND-REMAINING-GATES-2026-10-20.md)。代码已存在与“完成全部任务/发布验收通过”保持分开；真实六厂商/正式网关、真实数据恢复/来源/浏览器、RSS 试点与旧栈退出、最终发布仍未完成。当前没有本轮全量 CI 通过证据，未把 user 授权跳过的检查伪装成 PASS。

## 2. 第 8 批实施状态与后续候选（最多两个独立写入目标）

### DeepSeek 有界真实验收与 T02 Flash 探针差额（2026-10-20）

- 在 `main@976fe66` 的隔离固定镜像上执行本轮获批的 6 次真实请求，每次上限 256 输出 Token。短文本、完整流、单轮思考输出有真实通过证据；`length` 触发 Proxy 终态拒绝。工具首轮取得原生 `tool_calls`，但完整工具往返、思考多轮回传、双用户不同 Key 尚未运行，T13-C 整体仍为 PARTIAL。详见[脱敏真实报告](../verification/byok-deepseek-real-2026-10-20.md)。临时 Key、容器、网络和数据库卷均已清理，不继续调用本轮已用完的额度。
- 真实上游证明 Flash 默认思考模式拒绝指定函数的 `tool_choice`；现有 T02 工具探针正使用该组合，短文本探针的 8 Token 也可能耗在思考。仅对现有可信 Flash 别名的显式短能力探针设置 `thinking.type=disabled`，保留原有小预算、单次派发、指定白名单工具和严格终态/参数校验。业务研究仍使用原生 `auto` 工具选择和服务端续接，没有放宽流式保护或增加其他厂商路由。
- 新增 Flash 用例先复现 `unknown`，修正后既有独立 HTTP 传输测试 4 项通过。使用已有缓存应用镜像 Python 3.12.12 / Django 6.1.2，`--network none`、只读挂载隔离工作树、清空环境并只配置最小 Django settings；未安装共享依赖、未读取业务 `.env`/数据库、未发出新增 Provider 请求。后端 DB/浏览器/真实修复后探针未运行，全量 CI 继续集中处理。

### RSS T04/T08/T19 Feed 等价地址与未知创建恢复（2026-10-20）

- 基线 `main@1785510`。直接订阅先规范输入地址，但引擎 FeedDTO 原样返回 URL，导致主机大小写、默认 443、尾点或片段不同的同一地址不被复用，已存在 Feed 可能再次创建；创建结果未知后也可能无法按等价地址核对。
- 统一在原引擎 URL 校验入口规范 Feed 地址，操作服务复用相同结果。只规范 IDN/主机大小写、尾点、默认端口及片段；保留路径、大小写、查询字节和非默认端口区别，文章 URL 保留原值。IDN 规范化后仍检查私网 IP 和内部域名，未放宽 SSRF/重定向边界、未变更已绑定引擎身份或权限。
- 修复前明确复现等价已有 Feed 的多余 create/未知结果无法恢复；修复后 6 项适配器局部检查通过，包含未知创建最多一次派发、业务 URL 不误合并与危险地址拒绝。复用缓存 Python 3.12.12 应用镜像，禁外网、只读工作树，未安装依赖或使用真实数据库。DB/正式引擎/生产与全量 CI 未运行，任意跨站重定向别名绑定协议仍未完成。

### BYOK T14 关闭调用后的本人历史只读差额（2026-10-20）

- 基线 `main@3614ece`。翻译任务回放与调用记录继承了连接管理开关，关闭 BYOK 后连已结束历史也返回 403；终态任务内部还错误地依赖推理开关。现仅对这两个明确的历史读取视图允许已登录 owner GET/HEAD，连接管理及所有写入继续受开关保护。
- 已结束的翻译任务仍校验有效用户、凭据归属与文章授权/原文版本，不读取已撤销 Key、不派发/恢复任务；进行中任务仍受执行授权限制。公开 read_only 站点原有策略保持不变。私人翻译面板在连接管理关闭时显示已有终态记录并隐藏收费操作，设置页删去“业务尚未接入”的旧说明。
- 后端实际门禁/终态函数先失败复现，修正后 4 项无数据库检查通过；相关前端 28 项、typecheck、变更文件 ESLint 与生产产物构建通过。只读复用既有 CI 依赖缓存、网络禁用并使用 dummy 数据库，没有重建环境、修改缓存或新增真实 Provider 请求。数据库/API 持久化联合验证与全量 CI 未运行。
- 用户本轮明确“生产验证先跳过”：生产验收、真实数据切换、旧角色停止及依赖该前置的旧栈删除/最终发布保留为延期，不把未执行项记作通过，不再等待生产目标信息来阻塞当前代码迭代。

### BYOK T02/T09/T10 · OpenAI 原生 Responses 开发差额（2026-10-20）

- 用户明确“优先开发，跳过”剩余 DeepSeek 真实验收；生产验证已另行延期。真实厂商/生产未执行项继续记录为 NOT_RUN，不再等待 Key 或请求额度来阻塞独立代码交付。
- 基线 `main@f2c2eec`。补上 OpenAI 官方预置 `gpt-5.4-mini`（目录能力初始 unknown），通过既有可信 Proxy 使用原生 Responses；显式文本/工具探针分别有界一次发送，研究与推荐/分类等非流式业务继续复用原 owner/版本快照、费用同意与调用记录。原生输出映射只供既有工具调度，不建立直连厂商或站点 Key 回退。
- 请求固定 `store=false`、禁用 provider-side conversation/previous_response_id；原生 function_call、function_call_output 和 encrypted reasoning items 完整留在服务端同模型续接，公开历史仍只含可见文字。只有 completed 且无 error/incomplete_details 的响应可进入既有工具参数白名单/最终回答校验；拒绝缺失/重复/孤立工具结果和拒绝/未知输出类型。
- 只开放上述非流式能力；文章流式问答/翻译仍受原 Flash 终态路由限制。OpenAI 预置使用官方支持的 reasoning=none，避免将 Chat 专属 temperature 默认值带入另一协议；探针最多 64/128 输出 Token，无自动重试。
- 10 项局部离线检查通过，覆盖原生工具往返/后续回传、私有字段不公开、Gateway 单次原生派发、显式 HTTP 探针与不完整终态。复用只读现成缓存、dummy DB 和 network-none 容器；无新安装、真实 Key/Provider/生产操作，未运行全量 CI 或数据库联合回归。
- 官方依据：[Responses 状态与回传](https://developers.openai.com/api/docs/guides/conversation-state)、[工具结果条目](https://developers.openai.com/api/docs/guides/function-calling)、[GPT-5.4 mini](https://developers.openai.com/api/docs/models/gpt-5.4-mini)。开发完成不等于 T13-A 真实验收已通过。

### BYOK T13-B Claude 原生 Messages 开发（2026-10-20）

- OpenAI 原生 Responses 已合并 [#147](https://github.com/CoderLambert/news-aggregator/pull/147)，main `0749fb0`。本批基于该提交，补上 Claude Haiku 5.5 可信预置与官方 Anthropic SDK 经既有 Proxy 的 Messages 非流式调用；目录能力仍初始 unknown，业务必须先取得本人/版本绑定的显式文本与工具证明。
- 原生 tool_use / tool_result 对应、多个工具结果合并为同一 user 内容块、thinking/signature/redacted_thinking 完整保留在服务端原模型续接中。未知内容类型、截断、pause/refusal、缺失/重复/孤立工具结果拒绝；公开历史不包含原生块。现有 owner/epoch/版本/研究工具白名单/费用同意/usage 路径保留。
- 模型固定 disabled thinking、low effort，不透传 Chat sampling 默认值；能力探针分别最多 64/128 输出 Token、一次发送。官方 SDK 仅在 Claude 路由按需创建，固定回环 Proxy、项目认证与零重试；供应商 Key 只放请求体，清除 SDK 环境自定义头，关闭请求时释放两个客户端。依赖锁加入 anthropic 1.13.0 与 docstring-parser 0.18.0，没有重建共享环境。
- 核对实际频道分类调用时补足 native timeout 和 JSON 参数映射：OpenAI 使用 text.format=json_object；Messages 没有 Chat 的 json_object 开关，因此使用明确 JSON 指令，并继续依赖既有全响应 schema/身份校验；不声称 Claude 受 provider JSON schema 约束。其余未知参数保持拒绝。
- 20 项定向离线检查通过，包括 OpenAI 回归、Claude 原生工具/私有续问、缺失与截断负例、实际官方 SDK→本地 HTTP、环境头隔离及分类参数。仅使用只读既有依赖缓存、既有 T00 SDK 包、network-none 容器和 dummy DB；未安装软件、未请求真实 Provider。依赖锁静态校验通过；完整安装/CI/数据库联合回归 NOT_RUN。按用户指示继续延期真实模型/生产验收，文章流与翻译仍只允许原 Flash 流式路由。
- 官方依据：[Haiku 5.5](https://platform.claude.com/docs/en/models/haiku-5-5/overview)、[Messages 工具往返](https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview)、[思考块签名](https://platform.claude.com/docs/en/build-with-claude/thinking)、[结构化输出](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)。这是 T13-B 原生协议代码交付，不是 T13-B 真实验收通过。

### BYOK T01 可信地域连接差额（2026-10-20）

- 基线 `main@7ab3d31`。按冻结方案第 3 节与 T01 的“可信厂商/地域端点”范围，补充智谱中国大陆、Z.AI 国际、百炼北京/新加坡及 Moonshot 国际五个独立 profile。现有连接编辑器直接读取服务端目录，因此新增地域可选择、保存并刷新恢复；没有新增厂商协议适配器、模型或依赖，也没有放开原模型白名单。
- 旧 `*_default` profile/version/路由及密文 AAD 保留；地域变更只能新建连接并重新明确提交 Key，PATCH 不接受 endpoint/URL。服务端根据存储的 provider/profile/version 选择固定 Proxy alias；LiteLLM 继续处理其内置 provider 和模型协议。
- 12 项定向检查通过（42 项未选，另有 5 个 subtest）：合成 SQLite 中的五地域连接创建/读取/加密、篡改地域后拒绝解密、原地改地域/URL 拒绝、旧连接目录与脱敏回归、注册表和 Proxy 配置一致性。另在固定 `1.105.0` 镜像实际运行原生 PatternMatchRouter，五个地域别名均优先于默认 wildcard，正确保留模型 ID 和固定 endpoint；该组件检查没有发 HTTP 请求，不能称作完整 Proxy E2E。
- 使用只读现有依赖缓存、network-none 容器、临时测试库与合成 Key；未安装依赖、读取真实凭据、请求厂商或操作生产。完整 CI、真实 SDK→Proxy 请求、真实地域/模型、部署与浏览器验收 NOT_RUN。发布时需核对业务与 Proxy 配置版本和项目 key 准入，不能将代码合并等同于已部署。
- 设计核对：冻结 [方案第 3/4 节](https://github.com/CoderLambert/news-aggregator/blob/ed58afa7a72ae905e2a2ffc315d968ca3634b8f2/docs/features/byok/BYOK_IMPLEMENTATION_PLAN.md)、[T01](https://github.com/CoderLambert/news-aggregator/blob/ed58afa7a72ae905e2a2ffc315d968ca3634b8f2/docs/features/byok/tasks/T01-credentials.md)。T13 是真实厂商验收，不再把六张子卡当成重新开发厂商适配器的顺序。

### BYOK T02 手填模型的显式测试接线（2026-10-20）

- 基线 `main@1904253`。对照冻结方案第 2/3/4 节和 T02，“手填模型 ID”此前只能保存，所有非内置型号的测试都被模型白名单永久拒绝。现将预置目录与可信连接路由分开：规范的手填 ID 只能按存储的 provider/profile/version 解析为固定 LiteLLM alias；保存不发送请求，文本/工具回执与 T03 业务授权仍分别检查 owner、配置版本、Key epoch/version、端点身份及实际成功审计行。
- 不开放任意 endpoint、messages、headers、extra_body、跨 provider 或嵌套路由指令。OpenRouter 的 provider/model ID 仍限定在 OpenRouter 自己的固定前缀。旧 GLM/Qwen/Kimi 默认连接因地域不明确继续不可派发，须新建原方案明确的地域连接；不静默激活旧 Key。
- OpenAI/Claude 的官方 SDK 入口与私有 continuation 协议按可信协议前缀选择，不再绑定单个预置型号；原型号的固定选项只保留在原预置，新型号不继承未经证实的 thinking/effort 参数。全部请求仍经 Proxy，未新增厂商适配器或直连。文章/翻译流式仍保持现有严格路由限制。
- 工具探针采用共同支持的 auto 选择，但只有实际完整、符合 schema 的 byok_probe 调用才能证明工具能力；普通文字保留 unknown，不把未调用推断成不支持或可用于研究。原 schema、终态、无重试与输出预算保留。旧断言“所有手填 ID 禁止进 Proxy”和“未选择工具即 unsupported”按上述原产品合同纠偏，其余负例未放宽。
- 53 项后端检查与 58 个 subtest 通过（真实临时 SQLite，包含 T02/T03、地域/手填模型、native 协议/continuation、受控 HTTP）；Node 22 下 typecheck、lint（1 个既有 warning）、前端定向 28 项及 build 通过。前端首次测试因只读 node_modules/.vite-temp 无法启动，追加容器 tmpfs 后只运行尚未执行的测试/build。依赖缓存只读，无安装、真实数据、Key 或 Provider 请求。完整 CI、真实模型与浏览器验收待最终集中执行。
- 用户新目标已授权开发完成后集中验收，并允许使用先前 DeepSeek Key；此前的延期记录仅描述旧批次，不阻止新授权范围的有界调用。生产执行仍延期，其他厂商真实 Key/人工结论另列最终清单；本条不声称真实验收已执行。

### BYOK T03 用途可用状态与实际执行一致（2026-10-20）

- 基线 `main@8a295a7`。对照 T03 的可用选择与 T04/T05 的严格流式入口，发现“已有文本回执但没有受支持流式路由”的模型仍能保存为问答/全文翻译用途，且旧偏好 GET 错误显示 available。先在实际 SQLite 中复现两用途解析不拒绝、旧记录回读误报，再统一设置页筛选、后端保存/解析和快照核验。
- 现这两种用途必须满足当前业务入口的严格路由约束；不兼容的显式选择返回 model_task_unavailable、旧记录 needs_reselection。非流式研究/问题推荐仍按其各自能力证明使用同一模型；默认模型不被扩大为无条件支持所有用途。没有放宽 streaming、增加协议适配器或删除历史记录。
- 成功审计回执新增当前 proxy_alias 的精确核对。T03 旧成功路径 fixture 从本来不能用于 T04 的 deepseek-chat 改为实际支持的 deepseek-flash，其他 owner/版本/撤权/原子保存负例保留；新增错误 alias 回执拒绝及非流式模型跨用途反例。
- 后端 12 项和 2 个 subtest、前端 6 项通过；Node 22 typecheck、变更文件 ESLint 和 build 通过。复用只读缓存、临时 SQLite、network-none 容器；没有安装依赖、真实 Provider/Key/生产操作。完整联合验收在后续整批统一执行。

### BYOK T02 / AG / T09 集中验收发现的差额（2026-10-20）

- 基线 `main@703af0f`。集中完整检查发现探测审计 alias 字段 80 字符与手填模型 160 字符/路由 240 字符合同不一致；最大合法 ID 的 API/字段回归先真实失败，再通过 `0072` 前向迁移扩为 240。不截断模型 ID，不改历史迁移或可信路由。
- 五项 AG 老 fixture 改为真实连接/显式探针/选择快照，并在当前 gateway 边界注入合成响应；保留标题证据更新前零调用、更新中不得提交与目录 GET 无副作用断言。公共 capability schema 和研究关闭/hosted 双门禁分别按现行合同补齐，未放宽授权。
- 完整前端 105 文件/730 用例、typecheck/lint/build，CI 工具 50 用例与依赖锁 160 项通过；完整后端 2671 passed / 16 skipped（2687 个身份对账）、T00 SDK/Proxy 合成 239/239 通过；最终镜像和隔离 G1 的当前状态、首轮失败及环境修正见[集中验收记录](../verification/consolidated-acceptance-2026-10-20.md)。GitHub 两个 runner 当前 offline，实际 CI 不能记为通过。真实 Provider、生产和人工结论继续独立记录。

### BYOK T04/T05/T09 联合验收的统计尾帧与冷索引差额（2026-10-20）

- 继续在 `main@36c24dc` 上运行原 Django→SDK→固定 LiteLLM→合成上游联合流程，发现正常 stop 后的空 choice usage 帧被业务验证器误拒绝。官方 SDK frame 回归先失败复现后修正；仅允许已验证 stop 后的一次精确空统计尾帧，仍消费到干净 EOF，不放宽 Proxy guard、收费次数或路由。
- 研究工具默认 hybrid 在无向量集合的首次启动抛 NotFoundError；实际新 Chroma 目录先失败复现，现默认读取按 0 计数，继续已有授权关键词路径。显式管理/重建集合缺失及其他存储故障继续报错，不自动创建集合或新增搜索服务。
- 联合夹具改走真实用途偏好 PATCH，并使用独占文件 WAL 库、明确断言文件与 journal_mode；原进度/工具往返/取消/截断/零重发断言保留。当前修复与失败/通过证据见[集中验收记录](../verification/consolidated-acceptance-2026-10-20.md)，此批三根完整回归 2686 passed / 16 skipped、2702 身份对账通过；独立联合流程发现缺失原始 finish_reason 被误判成功，后续按下节修复并保留首次 FAIL，真实 Provider 尚未开始。

### BYOK T00/T09 原始非流式终态证明（2026-10-20）

- 现有 LiteLLM 归一化会给缺原始 finish_reason 的 Chat 响应补默认 stop，联合研究负例已真实复现误成功。复用固定版本的成功回调与请求私有原始响应记录，在归一化结果进入业务前校验原始终态、来源、单候选和一致性；未知/伪造记录、重复 JSON 字段与缺终态失败关闭，错误只含静态代码。
- 明确 length 等非成功终态原样保留，业务继续拒绝保存；不修改旧 T00 截断期望、不扩展厂商适配器或放宽流式 guard。通用 Chat alias 缺终态、DeepSeek 研究缺终态与 length 均有实际 SDK/Proxy 负例。
- 最新 T00 SDK/Proxy 241/241、Django 联合 3 项、共享网关 35 项通过；固定 digest 镜像 T00-G 含缺终态/恰好一次派发/错误脱敏共 28 项通过；后续最终候选与真实验收见[集中记录](../verification/consolidated-acceptance-2026-10-20.md)。GitHub CI 与生产未执行。

| 顺序 | 原编号与目标 | 需要完成的真正差额 | 阶段验收 |
|---|---|---|---|
| 第 8 批 A（离线交付已合并） | **BYOK T04 个人模型新闻问答** | T03 + T01 已接入文章阅读器和 per-turn 问答；取消/流式与提交围栏差额由 #118 完成，证据见上；真实验收仍独立保留 | 用户/文章版本/模型尝试/取消/重试负例及 SDK→本地 Proxy→合成上游通过；真实付费上游/UAT `NOT_RUN` |
| 第 8 批 B（差额已合并） | **RSS T09 正文/元数据写入一致性差额** | 先核对当前正文版本、主来源/非主写入、同正文元数据变化与重试提交围栏；仅补实际代码与合成回归 | SQLite 版本/内容读取/安全负例、RSS 原验收矩阵 A09；不提前切源 |
| 后续 | BYOK T13/T14 及 T06–T12 批次验证 | T06–T09 已分别合并；T10–T12 本轮按当前主线实现并提交，前端/纯逻辑定向已验证，后端数据库回归与全量 CI 待集中验证。真实厂商矩阵、部署/人工验收未完成 | 按第 1.4 节与各任务记录区分已实现和 NOT_RUN；不重复移植旧 PR #33–#45 |
| 后续 | RSS T11/T14/T27 | T11 Miniflux URL 来源绑定最小差额 `IMPLEMENTED / TESTED`（#126）；T14 本地搜索/正文回放新差额（#129/#131）已 `IMPLEMENTED / TESTED`，T11/T14 既有授权/本地上下文/hash 绑定读取链本轮已做源码与原合同复核，未发现需重写的后端功能；T14 前端自动朗读/所选译文复制的实测差额本轮修复，见第 1.4 节；T27 真实来源/浏览器联合最终验收 `NOT_RUN` | 继续按 T11/A08、T14/A11 与 T27/A15 合同核验权限、版本、撤权和消费者一致性；合成 CI/G1 不等于正式验收 |
| 后续 | AG-03/04 现存行为复核及 AG-05–07 联合验收 | AG-04 已有 #99；AG-05–07 本轮补齐模型接线、增量恢复与停止/状态操作，详见第 1.4 节。AG-03 的既有预设/owner/幂等/撤销实现已源码复核，当前数据库/并发回归未运行，后端 DB、真实 Provider/后台进程与人工验收未完成 | 保留原编号；已实现与 NOT_RUN 分开记录，不把状态页面或离线检查当正式发布 |
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
