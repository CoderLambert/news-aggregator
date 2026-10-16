# 可验收任务、合并顺序与完成证据

状态：REVIEW_REQUIRED。当前仅完成规划审计；产品任务均NOT_STARTED，不存在已验收开发基线/任务PR。

代码审核基线：`878b69081f8d5b3ae965bcf1c855390b059caa33`。共37个主任务节点（T00–T36，含证据任务、开发任务及T29汇总门禁）；实际逐源切换工单数量N须T24在授权副本盘点后确定。最终执行图为37+N节点，不能将未知N写成0或宣称已全部拆完生产来源。N未知阻塞T29冻结及执行，不阻塞其他已定义接口的实现。每个来源工单只处理一个source_id，不在一个PR机械按目录或一次迁移全站。

## 任务队列

| ID | 独立交付 | 前置 | 合同 | 当前状态 |
| --- | --- | --- | --- | --- |
| [T00](tasks/T00/task.md) | 验证 Miniflux 原生引擎合同并锁定版本 | G0 | C01, C03, C06 | NOT_STARTED / G0待审 |
| [T01](tasks/T01/task.md) | 验证 RSSHub HTTPS 网关与受支持路由 | T00 | C01, C03, C07 | NOT_STARTED / G0待审 |
| [T02](tasks/T02/task.md) | 部署隔离的原生 Miniflux 与 PostgreSQL | T00 | C01 | NOT_STARTED / G0待审 |
| [T03](tasks/T03/task.md) | 交付两库备份恢复工具与严格发布协议 | T02, T05, T11 | C01, C02, C09 | NOT_STARTED / G0待审 |
| [T04](tasks/T04/task.md) | 封装官方 Miniflux SDK 与受控单篇修复 | T00 | C03 | NOT_STARTED / G0待审 |
| [T05](tasks/T05/task.md) | 建立唯一身份、来源所有权及兼容扩展模型 | T00 | C02, C04, C05, C06, C08 | NOT_STARTED / G0待审 |
| [T06](tasks/T06/task.md) | 转换已有 HTML 并保持代码与安全边界 | T00 | C04 | NOT_STARTED / G0待审 |
| [T07](tasks/T07/task.md) | 接收正文版本并阻止内容退化覆盖 | T05, T06 | C04 | NOT_STARTED / G0待审 |
| [T08](tasks/T08/task.md) | 执行持久控制意图与幂等引擎连接 | T04, T05, T35 | C02, C03, C05 | NOT_STARTED / G0待审 |
| [T09](tasks/T09/task.md) | 同步新条目并持久化每页检查点 | T07, T08 | C02, C06 | NOT_STARTED / G0待审 |
| [T10](tasks/T10/task.md) | 对账所有保留条目并恢复长时间故障 | T09 | C06 | NOT_STARTED / G0待审 |
| [T11](tasks/T11/task.md) | 统一个人来源可见性与正文读取权限 | T05, T07 | C05, C04 | NOT_STARTED / G0待审 |
| [T12](tasks/T12/task.md) | 提供用户隔离的已读与未读状态 | T11 | C05, C08 | NOT_STARTED / G0待审 |
| [T13](tasks/T13/task.md) | 保留阅读体验并移除首访自动抓取 | T09, T11 | C04, C05 | NOT_STARTED / G0待审 |
| [T14](tasks/T14/task.md) | 让翻译、问答、研究和 TTS 只消费授权内容 | T10, T11, T13 | C04, C05, C10 | NOT_STARTED / G0待审 |
| [T15](tasks/T15/task.md) | 核验来源目录快照格式与许可证 | G0 | C07 | NOT_STARTED / G0待审 |
| [T16](tasks/T16/task.md) | 导入版本化目录并提供关键词搜索 | T05, T15 | C07, C05 | NOT_STARTED / G0待审 |
| [T17](tasks/T17/task.md) | 通过引擎发现网址中的 Feed 候选 | T04, T08, T11 | C03, C05, C07 | NOT_STARTED / G0待审 |
| [T18](tasks/T18/task.md) | 解析批准的 RSSHub 参数并部署可选网关 | T01, T02, T16, T17 | C03, C07 | NOT_STARTED / G0待审 |
| [T19](tasks/T19/task.md) | 直接订阅公开 Feed 并复用个人分组 | T08, T11, T16, T17 | C02, C05, C07 | NOT_STARTED / G0待审 |
| [T20](tasks/T20/task.md) | 交付关键词与网址发现的一键订阅界面 | T13, T16, T17, T19 | C07, C05 | NOT_STARTED / G0待审 |
| [T21](tasks/T21/task.md) | 安全预览并导入导出当前用户 OPML | T19 | C07, C05 | NOT_STARTED / G0待审 |
| [T22](tasks/T22/task.md) | 提供 OPML 选择确认和部分失败恢复界面 | T20, T21 | C07 | NOT_STARTED / G0待审 |
| [T23](tasks/T23/task.md) | 显示真实连接健康与同步落后状态 | T10, T19, T20 | C06, C07 | NOT_STARTED / G0待审 |
| [T24](tasks/T24/task.md) | 盘点来源覆盖差异并形成逐源迁移清单 | G0 | C02, C05, C11 | NOT_STARTED / G0待审 |
| [T25](tasks/T25/task.md) | 切换单一来源所有者并隔离旧任务晚写 | T03, T10, T14, T19, T24 | C02, C11 | NOT_STARTED / G0待审 |
| [T26](tasks/T26/task.md) | 在备份副本演练迁移与兼容回滚 | T12, T14, T22, T23, T25, T36 | C09, C11 | NOT_STARTED / G0待审 |
| [T27](tasks/T27/task.md) | 完成预生产真实来源与浏览器联合验收 | T26 | C04, C05, C06, C07, C11 | NOT_STARTED / G0待审 |
| [T28](tasks/T28/task.md) | 执行一个获批来源的生产试点 | T27 | C09, C11 | NOT_STARTED / G0待审 |
| [T29](tasks/T29/task.md) | 逐源审核其余切换结果并汇总放行 | T28 | C09, C11 | NOT_STARTED / G0待审 |
| [T30](tasks/T30/task.md) | 退出旧进程并验证重启不会复活 | T29 | C11, C09 | NOT_STARTED / G0待审 |
| [T31](tasks/T31/task.md) | 删除旧采集代码并拆出仍需的安全工具 | T30 | C10, C11 | NOT_STARTED / G0待审 |
| [T32](tasks/T32/task.md) | 瘦身依赖并完成唯一部署入口 | T31 | C01, C10, C11 | NOT_STARTED / G0待审 |
| [T33](tasks/T33/task.md) | 验证最终单栈回归、资源与恢复合同 | T32 | C01, C04, C05, C06, C09, C11 | NOT_STARTED / G0待审 |
| [T34](tasks/T34/task.md) | 执行获批最终发布并封存迁移证据 | T33 | C09, C11 | NOT_STARTED / G0待审 |
| [T35](tasks/T35/task.md) | 交付轻量同步运行时并验证无模型预加载 | T00, T04, T05 | C01, C03 | NOT_STARTED / G0待审 |
| [T36](tasks/T36/task.md) | 封存具备完整来源隔离的兼容回滚版本 | T03, T13, T25 | C02, C04, C05, C09, C11 | NOT_STARTED / G0待审 |

每项的目标/范围/技术方案见task.md，专项案例/命令/预期见tests.md；report.md目前均是未执行模板，不能把文件存在视为完成。

## 开发与合并规程

1. G0通过后，主控只选前置任务已验收合并、合同已冻结且无互斥文件的任务。上游验证任务先取得隔离环境及所需凭据；实际运行缺失标BLOCKED。
2. 从主控登记的已验收集成SHA创建独立分支与worktree。当前规划分支不是未来开发基线，不从未验收的兄弟PR堆叠开发。
3. 先编写/确认验收及反例，限定文件和资源锁；schema/model/migration由T05串行拥有，新增需求先ADR，不在下游偷偷增加列。
4. 专项、类型/静态/契约、必要实际运行通过；由独立Agent检查实现与冻结合同。P0/P1修复，证据关联修复SHA。
5. 填report.md的真实环境/命令/退出码/样本/CI/PR/风险/回滚，PR关联任务ID和验收文档。
6. 主控检查分支保护和必需CI后按依赖合并，不使用admin绕过；更新任务状态/集成SHA，重新计算ready集。查询保护API403只意味着未知，不是允许省略检查。
7. 每批按ACCEPTANCE-MATRIX回归；失败立即停止依赖开发，先修复，再重算队列。

状态：NOT_STARTED→READY→IN_PROGRESS→REVIEW→DONE；条件缺失为BLOCKED并明确解除项。DONE必须满足代码/专项/API或DB契约/必要实际验收/独立审核/PR提交CI/文档/无未声明副作用全部要求。不以mock、编译或单测替代实际验收。

## 首批建议

G0后证据批次：T00（引擎真实合同及版本）、T15（目录快照/许可证）、T24（来源及数据兼容盘点），至多3项；各自独立，但T24的实际计数需要获授权副本，没有时只完成静态部分并保留BLOCKED。

T00验收后第一组实现候选：T02（原生隔离部署）、T04（SDK适配）、T06（纯内容转换）。T00已经锁定版本及公共契约，三个任务各自在不同文件/测试范围工作；依赖声明集中由主控串行集成。T05模型迁移另开串行任务，不能与任何模型写任务并行。RSSHub验证T01可用空闲名额推进，不阻断native路径。

## 变更记录

本轮只有规划文档。三项用户明确确认已记录ADR-002/003/004，其他技术合同/参数/任务拆分等待规划PR审核及T00证据。实际来源工单未实例化是公开阻塞，不是允许依赖未知接口；C11已定义它们的输入、测试、锁、输出和回滚，T24补实际ID后须审核更新任务清单再运行。
