# 当前代码交付与剩余执行门禁

核对基线：`main@cd83d88c01ae2d073b8a660e795e8494d58f896e`。这是代码和剩余边界核对，不是全项目验收通过。当前任务状态仍以 [现行开发索引](FEATURE-DEVELOPMENT-2026-10-17.md) 为唯一入口。

本轮实际合并：BYOK T09–T12 [#135](https://github.com/CoderLambert/news-aggregator/pull/135)、[#136](https://github.com/CoderLambert/news-aggregator/pull/136)、[#137](https://github.com/CoderLambert/news-aggregator/pull/137)、[#138](https://github.com/CoderLambert/news-aggregator/pull/138)；AG-05–07 [#139](https://github.com/CoderLambert/news-aggregator/pull/139)、[#140](https://github.com/CoderLambert/news-aggregator/pull/140)、[#141](https://github.com/CoderLambert/news-aggregator/pull/141)；RSS T14 阅读选择、复制及自动朗读 [#142](https://github.com/CoderLambert/news-aggregator/pull/142)。它们已在远程 main，原工作区数据库和两份未跟踪文档保留。

## 功能和实际证据

| 原编号 | 当前代码/证据 | 尚未证明或执行 |
|---|---|---|
| BYOK T00 / T00-G | `tools/byok_t00_probe/`、`ops/shared-litellm-proxy/` 已有合成 SDK/Proxy、原生终态保护与固定镜像配置；历史 CI 证据保留在现行索引 | 正式镜像/网关部署与真实上游尚未完整验收。当前可信模型目录仅含 DeepSeek Chat/Flash，文章流仅 Flash；不能把连接供应商列表说成六厂商全部可用 |
| BYOK T01–T03 | 当前连接身份、凭据/worker 围栏、显式能力探针、五用途偏好与不可变选择快照已合并 | 真实凭据轮换/恢复、生产迁移和真实账户流程未验收；本轮未重建环境重跑 DB |
| BYOK T04 | 文章助手逐轮模型/费用同意、终态验证、取消与历史隔离已有实现和历史合成证据 | 仅开放已验证终态路由；其他厂商流式路径未验证，保持关闭 |
| BYOK T05–T08 | 有界/分段私人翻译、明确取消重试、详情/问答/TTS 结果选择已合并 | 真实模型长文、并发真实账户与人工 UAT 未运行；旧 T05 SQLite 失败记录保留，不因后续一次成功删除证据 |
| BYOK T09–T10 | #135/#136：首次研究、模型锁定续问、服务端原生续接、只读重连与 run/lease/CAS | 本轮前端/纯函数定向通过；后端 DB、真实模型工具轮次和生产/UAT 未运行 |
| BYOK T11–T12 | #137/#138：首次 GET 零推理、显式个人生成与私有缓存；本人调用与未知 Token 记录 | 前端/实际纯函数定向通过；新表迁移与数据库/API 全链、真实 usage 未运行 |
| BYOK T13-A–F / T14 | 保留原六厂商逐卡合同；当前运行时不绕过未验证厂商路由 | 六卡真实文本/流/工具证据、正式镜像/预算/双用户与最终产品验收仍未完成。首轮只有 DeepSeek 可申请有界真实调用 |
| AG-00–02 | 既有元信息、确定性规则、可信公共来源证据与人工确认边界 | 原标注集/真实模型技术验证、真实来源与人工验收仍未完成 |
| AG-03 | `channel_grouping.py` 现存 owner 写锁、预设校验、预览/快照、幂等增量应用、人工抑制与撤销已源码复核；既有 `test_smart_channel_workspace.py` 覆盖跨账号、过期、同名冲突与撤销后人工决定 | 本轮不重复实现相同功能，也不把源码核对当数据库/并发测试。当前 DB 回归未运行 |
| AG-04 | #99 的向导、预览恢复、键盘/焦点与移动布局保留；本轮 AG-05 相关界面定向通过 | 真实浏览器/390px 真机 UAT 未运行 |
| AG-05–07 | #139–141：已验证模型与个人/site 授权、派发 CAS/未知不重发、增量恢复、状态面板及停止操作 | 新迁移/数据库并发、正式后台进程、真实 Provider 与发布未验收 |
| RSS T00/T02/T03/T04/T05/T06/T07/T08/T09 | 原引擎合同、角色/备份恢复、身份/安全转换/写入、控制意图和同步已集成；T09 后续写入差额已合并；原 [清单](rss-engine-migration/TASKS.md) 与逐任务报告保留 | 原 A4 条件、真实引擎/来源、真实数据两库恢复和生产拓扑尚未证明；不能把 integrated 等同生产完成 |
| RSS T11/T13/T14 | `rss/access.py` SQL/StoredArticle；`stored_readers.py` hash/owner/历史；research 本地授权证据；TTS 每段重检；T13 阅读状态保留。#142 的两个用户缺陷先失败复现再修正，13 个相关前端用例按变更最终通过，typecheck/build 通过 | 本轮只有前端变更；未重新运行后端 DB 或真实 AI/TTS。真实首访/来源/浏览器联合验收仍在 T27 |
| RSS T16/T17/T18/T19/T20/T21 | 目录、发现、可选 RSSHub、直接订阅与 OPML 确认/恢复已集成并有局部修复 | 真实连接健康、RSSHub 公网认证/TLS/回流、任意重定向别名协议及 OPML 真实浏览器路径仍需分别验收；隐藏不满足条件的模板不是已验收支持 |
| RSS T24/T25/T26/T27 | 已有盘点/切换 fencing/恢复工具及合成报告，入口见 `rss_migration`、`ops/rss/T26/`、`ops/rss/T27/` | 授权真实副本清单、成对备份恢复、兼容镜像封存、来源质量/浏览器联合验收没有当前完整证据 |
| RSS T29/T30/T31/T33（含合并索引 T28/T32） | 生产试点、停止旧角色、删除旧代码及最终单栈发布合同保留 | **尚未执行**。T31 代码删除也依赖真实 T30 停止前置；不能提前删除仍被使用的旧栈来制造“开发完成” |
| NH28–NH31 / AG-07 发布 | [operator 门禁](../deployment/NH28-NH31-operator-acceptance.md)、备份恢复与证据工具已存在 | 真实授权/密钥恢复、源许可/质量、容量/移动端及人工发布签署未完成 |

## 本轮验证边界

- 已按用户要求跳过已知本地 pytest/PyYAML 缺失，未安装/重建运行环境；没有复制真实 SQLite 数据或读取真实密钥。
- #135 的完整 CI 因前后端 self-hosted Runner 失联失败，annotations 已核实。其后按明确授权使用 `[skip ci]` 集中批次验证，没有修改 CI 工作流或把失败/跳过改记 PASS。当前 main 尚无本轮全量 CI 通过证据。
- 各任务的 typecheck、前端定向、build、实际纯函数执行与源码结构检查只证明各自范围；历史 CI 报告也不等于当前全项目验收。
- 本轮没有执行付费 Provider、生产迁移/切源、服务停止、真实数据恢复、旧栈删除或部署。

## 下一阶段可确认的操作范围

1. **继续只做代码交付**：把上述真实验收/生产执行单元明确延期；遇到可复现功能缺口继续修复，不为补测试数量新建底座。此选择不等于原全项目发布验收通过。
2. **单独进入 DeepSeek 有界真实验收**：先指定隔离环境、官方通用 Key 的本地受保护引用和具体子卡；建议候选范围为最多 6 次实际请求、每次输出上限 256 Token、仅短合成提示、无自动重试/回退，不动生产。当前没有实际发出请求，不能从这份清单推导已获授权或已通过。
3. **准备具体生产试点**：先指定主机/项目、来源或最小共享组、窗口、允许停止的旧角色，以及受保护备份/加密材料引用；复用现有 T24/T26/T27/T29 工具准备精确 SHA 与恢复点，完成后再按原合同签署实际切源/发布。没有目标和批准范围时不操作生产。

真实调用边界来自冻结 [BYOK T13 合同](https://github.com/CoderLambert/news-aggregator/blob/ed58afa7a72ae905e2a2ffc315d968ca3634b8f2/docs/features/byok/tasks/T13-providers.md)：“首轮仅 DeepSeek 获准 PROVIDER_REAL，且须在其单独子卡实际执行前获用户确认有界测试”。生产边界来自 [T29](rss-engine-migration/tasks/T29/task.md) 的具体生产批准、[T31](rss-engine-migration/tasks/T31/task.md) 的 T30 停止前置与 [operator 门禁](../deployment/NH28-NH31-operator-acceptance.md) 的明确人工签署。没有因此中断本轮已授权的开发或合并。
