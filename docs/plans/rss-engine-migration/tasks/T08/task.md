# T08：执行幂等控制意图与政策收敛

状态：PLANNED，产品未实现。代码基线：878b690。交付单元：控制 worker。

## 目标与范围

实现固定 register/set_enabled/update_feed_policy/discover/refresh_feed/refetch_entry；短事务意图、事务外网络、有限重试/租约。跨用户共享物理注册但本人操作视图隔离。

修改范围：backend/api/rss/operations.py、rss_sync_worker 壳。行为以 [C01–C11](../../INTERFACE-CONTRACTS.md) 为准，架构方向见 [ARCHITECTURE.md](../../ARCHITECTURE.md)。

## 依赖与执行条件

集成前置：[T02](../T02/task.md)、[T04](../T04/task.md)、[T05](../T05/task.md)。

表中前置约束本交付的集成验收/完成，不禁止按已审接口和 fixture 独立开发。实现可先用 fake adapter；DONE 需轻量容器及真实引擎操作集成，生产授权不是开发前置

同一关键写入函数/迁移串行修改；公共路由、依赖、types 和 Compose 使用协调后的串行合并，不因共享文件冻结整个任务。独立工作可从已验收基线开分支，合入前 rebase/解决冲突并跑受影响契约；不得把 fixture 通过写成真实运行通过。

## 专项验收

1. 20 次注册一物理绑定。
2. 响应丢失/取消注册/最后引用收敛。
3. 旧政策修复不执行或发布，配置核对后恢复。
4. 控制不占 SQLite 写事务且短读容量保留。

专项反例与命令见 [tests.md](tests.md)。只验证本任务风险，不复制无关的重启/权限/生产授权测试。上线门禁和批次全量见 [ACCEPTANCE-MATRIX.md](../../ACCEPTANCE-MATRIX.md)。

## 交付与恢复

在 [report.md](report.md) 记录实现/环境/命令/实际结果、SHA/PR/CI、风险和相关证据；同 SHA/配置的公共证据可链接复用。产品仍 NOT_RUN。实质架构/权限语义变化补 ADR，字段/参数调整走普通评审。

恢复遵循 [ROLLBACK.md](../../ROLLBACK.md)：暂停受影响动作或回受测兼容版本，保留数据，不默认 reverse migration/恢复全库。生产切换/恢复/发布只按具体批准范围执行，本规划修订不授权生产操作。
