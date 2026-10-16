# T29：逐源审核其余切换结果并汇总放行

状态：PLANNED / 等待规划审核；实现尚未开始。基线：`878b69081f8d5b3ae965bcf1c855390b059caa33`。

## 目标、范围和合同

这是汇总门禁，不承载批量开发/切换：T24得到实际source_id后，按T29模板实例化独立task/tests/report并形成明确DAG；每项只切换一个来源或经批准停更，顺序执行。未知实际来源数量不伪造总数。

修改范围：tasks/T29-SOURCE-ID 的单源工单；总清单。目标追踪：ARCHITECTURE.md 第 10–11 节；详细合同 [C09](../../INTERFACE-CONTRACTS.md#c09)、[C11](../../INTERFACE-CONTRACTS.md#c11)；附加决议见 [ARCHITECTURE-DECISIONS.md](../../ARCHITECTURE-DECISIONS.md)。

## 依赖与阻塞

前置：[T28](../T28/task.md)。前置任务必须验收并合并，基线以主控记录的集成 SHA 为准，不能仅依赖未合并分支。RSSHub相关前置只适用于实际RSSHub来源，native路径按DEPENDENCIES中的条件门禁执行。

阻塞：规划未审核；对应 C09/C11 未冻结；缺特定生产授权、实际来源ID或受测回滚基点则 BLOCKED。发现新模型需求或合同冲突时，提交独立ADR并暂停依赖任务，不在本任务顺带改模型或增加服务。

## 实施与并发边界

从前置合并后的已验收 SHA 建立 `rss/t29` 分支，只包含本任务。互斥资源：`source-cutover`。schema/model/migration仅T05所有，后续新DDL先立独立合同变更任务；API全局路由/公共types由主控串行集成，不允许多任务同时修改。最多3项开发任务，同文件重叠即串行。

先确认 tests.md 的验收fixture和反例，再实现；不得新增爬虫/XML解析器/原网页提取器/通用任务平台。本节点仅汇总；不得在此PR内一次实施所有来源迁移。

## 独立验收

1. 每个实际来源都有独立工单、批准、范围差异和回滚证据。
2. 正常源真实接入或记录获批准的unsupported/history-only。
3. 所有子工单验收后汇总才PASS，不用平均成功率掩盖失败来源。
4. 未授权生产/未定义来源ID时BLOCKED，禁止自动批量切换。

## 交付、审核和回滚

实现、测试及必要的实际运行证据归档于本目录的 report.md（大日志使用校验和及受控工件链接）。记录提交/PR/CI、基线与目标SHA、独立审核人和问题修复SHA。满足全部完成定义后才改DONE；缺真实条件不能PASS。

回滚：按 ROLLBACK.md，先暂停目标来源/全部写入，使用获批兼容版本；恢复旧调度另需授权，新Feed仅暂停。 通用审核、批次回归和生产闸门见 [TASKS.md](../../TASKS.md) 与 [ROLLBACK.md](../../ROLLBACK.md)。
