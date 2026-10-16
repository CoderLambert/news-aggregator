# T19：直接订阅 Feed 并复用个人分组

状态：PLANNED，产品未实现。代码基线：878b690。交付单元：订阅服务。

## 目标与范围

复用 Source/ChannelSubscription/Group，直接 URL 输入先交付；目录 ID/发现 token 使用同一服务，在 T20 接线。不再由 Spider 注册表决定普通来源可订阅性。

修改范围：backend/api/rss/subscriptions.py、channel_catalog。行为以 [C01–C11](../../INTERFACE-CONTRACTS.md) 为准，架构方向见 [ARCHITECTURE.md](../../ARCHITECTURE.md)。

## 依赖与执行条件

集成前置：[T05](../T05/task.md)、[T08](../T08/task.md)、[T11](../T11/task.md)。

表中前置约束本交付的集成验收/完成，不禁止按已审接口和 fixture 独立开发。直接 URL 开发不依赖 T16/T17；对应输入分支在 T20 验收前集成，RSSHub 条件依赖 T18

同一关键写入函数/迁移串行修改；公共路由、依赖、types 和 Compose 使用协调后的串行合并，不因共享文件冻结整个任务。独立工作可从已验收基线开分支，合入前 rebase/解决冲突并跑受影响契约；不得把 fixture 通过写成真实运行通过。

## 专项验收

1. 并发幂等和本人组归属。
2. 注册中退订/A 退订 B 保留。
3. 正常公开 Feed 无开发 Spider 审批。
4. 新源 personal、停更历史权限保持。

专项反例与命令见 [tests.md](tests.md)。只验证本任务风险，不复制无关的重启/权限/生产授权测试。上线门禁和批次全量见 [ACCEPTANCE-MATRIX.md](../../ACCEPTANCE-MATRIX.md)。

## 交付与恢复

在 [report.md](report.md) 记录实现/环境/命令/实际结果、SHA/PR/CI、风险和相关证据；同 SHA/配置的公共证据可链接复用。产品仍 NOT_RUN。实质架构/权限语义变化补 ADR，字段/参数调整走普通评审。

恢复遵循 [ROLLBACK.md](../../ROLLBACK.md)：暂停受影响动作或回受测兼容版本，保留数据，不默认 reverse migration/恢复全库。生产切换/恢复/发布只按具体批准范围执行，本规划修订不授权生产操作。
