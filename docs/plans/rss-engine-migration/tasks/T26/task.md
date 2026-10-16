# T26：演练迁移恢复并封存兼容回滚版本

状态：PLANNED，产品未实现。代码基线：878b690。交付单元：迁移演练（含 T36）。

## 目标与范围

选含完整 fence/available/ACL/译文读取的候选镜像，执行 0051→过渡→新同步→应用回滚、两库 restore；全部通过后封存实际 SHA/digest/schema/manifest。

修改范围：隔离两库演练、兼容 release manifest 与报告。行为以 [C01–C11](../../INTERFACE-CONTRACTS.md) 为准，架构方向见 [ARCHITECTURE.md](../../ARCHITECTURE.md)。

## 依赖与执行条件

集成前置：[T03](../T03/task.md)、[T09](../T09/task.md)、[T11](../T11/task.md)、[T13](../T13/task.md)、[T14](../T14/task.md)、[T24](../T24/task.md)、[T25](../T25/task.md)。

表中前置约束本交付的集成验收/完成，不禁止按已审接口和 fixture 独立开发。真实副本和候选镜像是本次演练前提；不要求 OPML/健康 UI 完成或先有已封存基点。最终封存前须包含计划发布的 T13/T16/T21 领域 DDL，模型小提交可先于 UI 集成；早期演练不证明尚未纳入的 schema。RSSHub 样本额外需 T18，native 可先验

同一关键写入函数/迁移串行修改；公共路由、依赖、types 和 Compose 使用协调后的串行合并，不因共享文件冻结整个任务。独立工作可从已验收基线开分支，合入前 rebase/解决冲突并跑受影响契约；不得把 fixture 通过写成真实运行通过。

## 专项验收

1. 原 PK/FK/用户关系及兼容译文保留。
2. 共享切换/旧 worker/旧翻译任务晚写拒绝。
3. 普通应用回滚保留新数据并可读 available/ACL。
4. 两库 restore 身份核对/对账及恢复点明确。

专项反例与命令见 [tests.md](tests.md)。只验证本任务风险，不复制无关的重启/权限/生产授权测试。上线门禁和批次全量见 [ACCEPTANCE-MATRIX.md](../../ACCEPTANCE-MATRIX.md)。

## 交付与恢复

在 [report.md](report.md) 记录实现/环境/命令/实际结果、SHA/PR/CI、风险和相关证据；同 SHA/配置的公共证据可链接复用。产品仍 NOT_RUN。实质架构/权限语义变化补 ADR，字段/参数调整走普通评审。

恢复遵循 [ROLLBACK.md](../../ROLLBACK.md)：暂停受影响动作或回受测兼容版本，保留数据，不默认 reverse migration/恢复全库。生产切换/恢复/发布只按具体批准范围执行，本规划修订不授权生产操作。
