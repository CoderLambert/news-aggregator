# T09：同步元数据、正文并完成全保留条目对账

状态：PLANNED，产品未实现。代码基线：878b690。交付单元：同步（含 T10、T23 后台）。

## 目标与范围

同一进程实现新增、固定上界 keyset 对账、游标和健康指标；按 C04 字段表写元数据/摘要，按 C02 适配频道成员/分类/地区查询。

修改范围：backend/api/rss/sync.py、reconciliation.py、channel_articles.py、worker 调度。行为以 [C01–C11](../../INTERFACE-CONTRACTS.md) 为准，架构方向见 [ARCHITECTURE.md](../../ARCHITECTURE.md)。

## 依赖与执行条件

集成前置：[T07](../T07/task.md)、[T08](../T08/task.md)。

表中前置约束本交付的集成验收/完成，不禁止按已审接口和 fixture 独立开发。DONE 需实际引擎故障集成；字段/游标算法可先用 fixture。来源质量和浏览器归 T27

同一关键写入函数/迁移串行修改；公共路由、依赖、types 和 Compose 使用协调后的串行合并，不因共享文件冻结整个任务。独立工作可从已验收基线开分支，合入前 rebase/解决冲突并跑受影响契约；不得把 fixture 通过写成真实运行通过。

## 专项验收

1. 写入后 kill/丢响应/DB busy 重放不漏。
2. 旧日期新 ID、低 ID 晚提交及老正文变化最终收敛。
3. 相同 HTML 仍检查元数据/政策/成员且非主写 Feed 不覆写。
4. cleanup 不删本地，健康记录完成时间/lag 而非仅开始时间。

专项反例与命令见 [tests.md](tests.md)。只验证本任务风险，不复制无关的重启/权限/生产授权测试。上线门禁和批次全量见 [ACCEPTANCE-MATRIX.md](../../ACCEPTANCE-MATRIX.md)。

## 交付与恢复

在 [report.md](report.md) 记录实现/环境/命令/实际结果、SHA/PR/CI、风险和相关证据；同 SHA/配置的公共证据可链接复用。产品仍 NOT_RUN。实质架构/权限语义变化补 ADR，字段/参数调整走普通评审。

恢复遵循 [ROLLBACK.md](../../ROLLBACK.md)：暂停受影响动作或回受测兼容版本，保留数据，不默认 reverse migration/恢复全库。生产切换/恢复/发布只按具体批准范围执行，本规划修订不授权生产操作。
