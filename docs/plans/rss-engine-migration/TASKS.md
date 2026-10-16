# RSS 迁移交付清单与完成条件

状态：REVIEW_REQUIRED；代码基线 878b69081f8d5b3ae965bcf1c855390b059caa33，产品均未实现。修订规划共有 26 个有效交付单元；保留 T00–T36 共 37 个历史编号，其中 11 个为合并索引。来源数量不影响开发节点数量，不再要求 37+N 独立工单。

## 有效交付单元

“集成前置”表示本单元合入集成验收和宣告 DONE 所需的模块/证据；已审合同/fixture 足够时可先独立开发。真实环境条件另列在任务文件，不能把生产 DNS/Token/数据副本/授权一概变成开发前置。

| ID | 交付 | 集成前置 | 状态 |
| --- | --- | --- | --- |
| [T00](tasks/T00/task.md) | 验证最小引擎合同并锁定运行版本 | 无 | NOT_STARTED |
| [T02](tasks/T02/task.md) | 部署原生引擎及轻量同步运行时 | T00 | NOT_STARTED |
| [T03](tasks/T03/task.md) | 扩展发布角色与两库备份恢复工具 | T02, T05 | NOT_STARTED |
| [T04](tasks/T04/task.md) | 封装 SDK、配置更新与持久单篇修复 | T00 | NOT_STARTED |
| [T05](tasks/T05/task.md) | 建立核心身份、权限和同步兼容模型 | 无 | NOT_STARTED |
| [T06](tasks/T06/task.md) | 安全转换已有 HTML 并保持代码文本 | 无 | NOT_STARTED |
| [T07](tasks/T07/task.md) | 提交正文并保护旧兼容译文与版本 | T05, T06 | NOT_STARTED |
| [T08](tasks/T08/task.md) | 执行幂等控制意图与政策收敛 | T02, T04, T05 | NOT_STARTED |
| [T09](tasks/T09/task.md) | 同步元数据、正文并完成全保留条目对账 | T07, T08 | NOT_STARTED |
| [T11](tasks/T11/task.md) | 统一文章、来源和正文授权读取 | T05 | NOT_STARTED |
| [T13](tasks/T13/task.md) | 保留阅读体验并提供个人已读状态 | T11 | NOT_STARTED |
| [T14](tasks/T14/task.md) | 统一 AI/TTS 本地上下文与译文版本读取 | T11 | NOT_STARTED |
| [T16](tasks/T16/task.md) | 验证并导入来源目录及本地搜索 | 无 | NOT_STARTED |
| [T17](tasks/T17/task.md) | 通过引擎发现网址中的 Feed 候选 | T04, T08 | NOT_STARTED |
| [T18](tasks/T18/task.md) | 验证并接入可选 RSSHub 网关与标准路由 | T00, T02, T04, T16 | NOT_STARTED |
| [T19](tasks/T19/task.md) | 直接订阅 Feed 并复用个人分组 | T05, T08, T11 | NOT_STARTED |
| [T20](tasks/T20/task.md) | 交付发现订阅界面与连接健康展示 | T11, T16, T17, T19 | NOT_STARTED |
| [T21](tasks/T21/task.md) | 交付 OPML 预览、确认、导出与恢复界面 | T19 | NOT_STARTED |
| [T24](tasks/T24/task.md) | 盘点来源差异和共享切换组 | 无 | NOT_STARTED |
| [T25](tasks/T25/task.md) | 实现共享来源切换与全部旧写入 fencing | T05, T07 | NOT_STARTED |
| [T26](tasks/T26/task.md) | 演练迁移恢复并封存兼容回滚版本 | T03, T09, T11, T13, T14, T24, T25 | NOT_STARTED |
| [T27](tasks/T27/task.md) | 完成真实来源与浏览器产品联合验收 | T20, T21, T26 | NOT_STARTED |
| [T29](tasks/T29/task.md) | 执行来源试点与后续迁移批次 | T27 | NOT_STARTED |
| [T30](tasks/T30/task.md) | 停止旧运行入口并验证重启 | T29 | NOT_STARTED |
| [T31](tasks/T31/task.md) | 删除旧采集代码、依赖并统一部署入口 | T30 | NOT_STARTED |
| [T33](tasks/T33/task.md) | 验证最终单栈并执行获批发布 | T31 | NOT_STARTED |

T17 的授权缓存预览在 T20 联合接入 T11；T19 的目录/token 分支在 T20 联合接入 T16/T17；T13 的真实修复、T20 的真实健康和原生后台预获取在 T27 联合验证。这些是条件接线，不让基本 UI/直接 URL 功能等待整个后端完成。

## 合并索引

| 历史编号 | 实际交付所有者 |
| --- | --- |
| [T01](tasks/T01/task.md) | T18 |
| [T10](tasks/T10/task.md) | T09 |
| [T12](tasks/T12/task.md) | T13 |
| [T15](tasks/T15/task.md) | T16 |
| [T22](tasks/T22/task.md) | T21 |
| [T23](tasks/T23/task.md) | T09（后台）；T20（界面） |
| [T28](tasks/T28/task.md) | T29 |
| [T32](tasks/T32/task.md) | T31 |
| [T34](tasks/T34/task.md) | T33 |
| [T35](tasks/T35/task.md) | T02 |
| [T36](tasks/T36/task.md) | T26 |

合并不是完成。原 task/tests/report 改为链接索引，不再独立开 PR 或复制验收。T29 内保留“试点通过再扩大”的运行门禁；T33 内保留“最终验证后另核对发布授权”的阶段。T26 在同次演练中先测试候选，再封存兼容基点。

## 工作与合并规则

1. 规划审核后从受审基线建立独立分支/worktree；合同明确即可编写模块和 fixture，不必等所有上游任务 DONE 才开始。
2. 前置集成、共享文件和环境门禁分别管理。共同 urls/types/依赖清单/Compose 通过小型公共接口提交或串行合并解决，必要时 rebase 并跑相关契约；同一写入函数、迁移文件串行修改。
3. T05 仅核心 DDL；T13/T16/T21 拥有各自领域 DDL，迁移编号由集成人串行协调。普通字段/索引/限额变化不另立 ADR；架构、权限语义和兼容边界变化须复核决议。
4. 每项按风险跑专项和适用契约；PR 遵守实际必需 CI。实现均评审，身份/ACL/迁移/恢复等关键风险独立复核；不机械要求每个纯函数/文档任务再启动一个 Agent。
5. 报告记录真实命令/退出码、环境、SHA/PR/CI 和适用工件。公共验收证据在 SHA/配置和相关代码未改变时链接复用；没有真实运行就标 NOT_RUN/BLOCKED。
6. 按 [验收矩阵](ACCEPTANCE-MATRIX.md) 在集成节点跑全量。失败只冻结受影响合入/上线路径，无关开发继续；修复后重跑相关测试。
7. 不绕过分支保护，不自动合并。保护 API 不可见时标未知，不能据此推断无要求。本次授权仅修订文档和 PR。

状态：NOT_STARTED→IN_PROGRESS→REVIEW→DONE；独立记录集成/运行门禁 BLOCKED 及原因。模块可先完成开发测试，任务明确要求的实际运行验收缺失则不能 DONE；它也不自动阻断只依赖接口的独立开发。

## 首批并行建议

首组最多 3 项：T00 最小引擎实验、T06 纯转换、T16 目录/搜索。T05 在核心数据合同确认后应尽早进入下一组，可与 SDK/部署工作并行；T24 静态清单可利用空闲时间推进，副本缺失不冻结其他任务。

T02/T04 可先按候选版本/契约实现，T00 完成后锁定实际制品并集成。T07 与 T11 可在 T05 后独立推进；T14 不依赖阅读 UI/对账；T25 在核心模型/提交服务后用合成数据开发，真实切源在 T29 才要求完整上线门禁。

逐源迁移使用一份 manifest 和逐源结果，按共享 Feed 最小切换组串行执行；特殊政策/失败才单独工单，普通来源不要求独立 task/tests/report/PR。
