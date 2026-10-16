# T28：执行一个获批来源的生产试点

状态：PLANNED / 等待规划审核；实现尚未开始。基线：`878b69081f8d5b3ae965bcf1c855390b059caa33`。

## 目标、范围和合同

开始前必须提供来源ID/执行人/窗口/备份点/兼容SHA/批准凭据。先暂停该源旧owner、排空/fence、启用Miniflux，观察并按阈值继续或暂停。未经批准仅dry-run。

修改范围：仅获批准的单一source_id试点工单与证据。目标追踪：ARCHITECTURE.md 第 10–11 节；详细合同 [C09](../../INTERFACE-CONTRACTS.md#c09)、[C11](../../INTERFACE-CONTRACTS.md#c11)；附加决议见 [ARCHITECTURE-DECISIONS.md](../../ARCHITECTURE-DECISIONS.md)。

## 依赖与阻塞

前置：[T27](../T27/task.md)。前置任务必须验收并合并，基线以主控记录的集成 SHA 为准，不能仅依赖未合并分支。RSSHub相关前置只适用于实际RSSHub来源，native路径按DEPENDENCIES中的条件门禁执行。

阻塞：规划未审核；对应 C09/C11 未冻结；缺特定生产授权、实际来源ID或受测回滚基点则 BLOCKED。发现新模型需求或合同冲突时，提交独立ADR并暂停依赖任务，不在本任务顺带改模型或增加服务。

## 实施与并发边界

从前置合并后的已验收 SHA 建立 `rss/t28` 分支，只包含本任务。互斥资源：`production-writer`、`source-cutover`。schema/model/migration仅T05所有，后续新DDL先立独立合同变更任务；API全局路由/公共types由主控串行集成，不允许多任务同时修改。最多3项开发任务，同文件重叠即串行。

先确认 tests.md 的验收fixture和反例，再实现；不得新增爬虫/XML解析器/原网页提取器/通用任务平台。任务级专项通过后做独立审核；P0/P1修复后才提交合并。

## 独立验收

1. 生产授权精确覆盖该source_id而非泛指重构。
2. 用户数据/身份/hash正确，新内容后台入库首访只读。
3. 故障可回兼容版本并保留新增数据，不运行自动DB恢复。
4. 试点验收后才允许逐源扩展。

## 交付、审核和回滚

实现、测试及必要的实际运行证据归档于本目录的 report.md（大日志使用校验和及受控工件链接）。记录提交/PR/CI、基线与目标SHA、独立审核人和问题修复SHA。满足全部完成定义后才改DONE；缺真实条件不能PASS。

回滚：按 ROLLBACK.md，先暂停目标来源/全部写入，使用获批兼容版本；恢复旧调度另需授权，新Feed仅暂停。 通用审核、批次回归和生产闸门见 [TASKS.md](../../TASKS.md) 与 [ROLLBACK.md](../../ROLLBACK.md)。
