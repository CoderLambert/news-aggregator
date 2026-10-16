# T11：统一文章、来源和正文授权读取

状态：PLANNED，产品未实现。代码基线：878b690。交付单元：ACL 与读取。

## 目标与范围

实现 AccessContext/StoredArticle、SQL 与 Python 可读性；授权先于正文/摘要/计数/缓存，scope 筛选不是权限。public/personal 停更历史保持原范围。

修改范围：backend/api/rss/access.py、列表/详情/搜索/统计读取。行为以 [C01–C11](../../INTERFACE-CONTRACTS.md) 为准，架构方向见 [ARCHITECTURE.md](../../ARCHITECTURE.md)。

## 依赖与执行条件

集成前置：[T05](../T05/task.md)。

表中前置约束本交付的集成验收/完成，不禁止按已审接口和 fixture 独立开发。可独立使用 T05 fixture，不以 T07 写入实现为开发前置；与实际内容管线集成在 T26/T27

同一关键写入函数/迁移串行修改；公共路由、依赖、types 和 Compose 使用协调后的串行合并，不因共享文件冻结整个任务。独立工作可从已验收基线开分支，合入前 rebase/解决冲突并跑受影响契约；不得把 fixture 通过写成真实运行通过。

## 专项验收

1. A/B/匿名直接 ID、列表、搜索/向量、收藏/统计无泄漏。
2. 同 URL 关联不扩大正文权限。
3. 退订/政策撤销立即影响缓存。
4. legacy/complete/available 及公开/个人 paused 一致。

专项反例与命令见 [tests.md](tests.md)。只验证本任务风险，不复制无关的重启/权限/生产授权测试。上线门禁和批次全量见 [ACCEPTANCE-MATRIX.md](../../ACCEPTANCE-MATRIX.md)。

## 交付与恢复

在 [report.md](report.md) 记录实现/环境/命令/实际结果、SHA/PR/CI、风险和相关证据；同 SHA/配置的公共证据可链接复用。产品仍 NOT_RUN。实质架构/权限语义变化补 ADR，字段/参数调整走普通评审。

恢复遵循 [ROLLBACK.md](../../ROLLBACK.md)：暂停受影响动作或回受测兼容版本，保留数据，不默认 reverse migration/恢复全库。生产切换/恢复/发布只按具体批准范围执行，本规划修订不授权生产操作。
