# T07：提交正文并保护旧兼容译文与版本

状态：PLANNED，产品未实现。代码基线：878b690。交付单元：正文持久化。

## 目标与范围

实现 C02/C04 CAS；相同 hash no-op，主写/政策改变独立版本。可疑退化候选去重，缩短阈值配置化；首次更改源文本前归档旧兼容译文。

修改范围：backend/api/rss/content_store.py、通用 CAS/legacy snapshot 服务。行为以 [C01–C11](../../INTERFACE-CONTRACTS.md) 为准，架构方向见 [ARCHITECTURE.md](../../ARCHITECTURE.md)。

## 依赖与执行条件

集成前置：[T05](../T05/task.md)、[T06](../T06/task.md)。

表中前置约束本交付的集成验收/完成，不禁止按已审接口和 fixture 独立开发。合成数据可完成本任务；全链旧 worker 晚写在 T25，真实数据回滚在 T26，避免重复全部演练

同一关键写入函数/迁移串行修改；公共路由、依赖、types 和 Compose 使用协调后的串行合并，不因共享文件冻结整个任务。独立工作可从已验收基线开分支，合入前 rebase/解决冲突并跑受影响契约；不得把 fixture 通过写成真实运行通过。

## 专项验收

1. 旧来源/主写/政策/revision 令牌失败拒绝且不推进游标。
2. 同 hash 不增 revision/清译文。
3. 空/错误/摘要退化保留旧正文。
4. 仅 full_content_zh/title_zh/content_zh 的归档中断重放不丢唯一副本。

专项反例与命令见 [tests.md](tests.md)。只验证本任务风险，不复制无关的重启/权限/生产授权测试。上线门禁和批次全量见 [ACCEPTANCE-MATRIX.md](../../ACCEPTANCE-MATRIX.md)。

## 交付与恢复

在 [report.md](report.md) 记录实现/环境/命令/实际结果、SHA/PR/CI、风险和相关证据；同 SHA/配置的公共证据可链接复用。产品仍 NOT_RUN。实质架构/权限语义变化补 ADR，字段/参数调整走普通评审。

恢复遵循 [ROLLBACK.md](../../ROLLBACK.md)：暂停受影响动作或回受测兼容版本，保留数据，不默认 reverse migration/恢复全库。生产切换/恢复/发布只按具体批准范围执行，本规划修订不授权生产操作。
