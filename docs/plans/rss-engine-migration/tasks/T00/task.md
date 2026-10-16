# T00：验证最小引擎合同并锁定运行版本

状态：PLANNED，产品未实现。代码基线：878b690。交付单元：引擎验证。

## 目标与范围

候选 Miniflux/PG/SDK 的 API、分页、持久修复、清理和私网防护做最小隔离实验。大范围真实来源质量归 T27；不验证自建 transport 框架。

修改范围：tests/rss_engine_contract/、ops/rss 版本证据。行为以 [C01–C11](../../INTERFACE-CONTRACTS.md) 为准，架构方向见 [ARCHITECTURE.md](../../ARCHITECTURE.md)。

## 依赖与执行条件

集成前置：无。

表中前置约束本交付的集成验收/完成，不禁止按已审接口和 fixture 独立开发。真实引擎与镜像 digest 缺失时仅此运行证据 BLOCKED，T05/T06/T16 仍可开发

同一关键写入函数/迁移串行修改；公共路由、依赖、types 和 Compose 使用协调后的串行合并，不因共享文件冻结整个任务。独立工作可从已验收基线开分支，合入前 rebase/解决冲突并跑受影响契约；不得把 fixture 通过写成真实运行通过。

## 专项验收

1. API/分页上下界和空库可复现。
2. read/unread 90 天配置与 created_at 语义核对。
3. 普通刷新与 update_content=true 持久修复区别。
4. 受控私网/重定向/凭据与异常响应拒绝。

专项反例与命令见 [tests.md](tests.md)。只验证本任务风险，不复制无关的重启/权限/生产授权测试。上线门禁和批次全量见 [ACCEPTANCE-MATRIX.md](../../ACCEPTANCE-MATRIX.md)。

## 交付与恢复

在 [report.md](report.md) 记录实现/环境/命令/实际结果、SHA/PR/CI、风险和相关证据；同 SHA/配置的公共证据可链接复用。产品仍 NOT_RUN。实质架构/权限语义变化补 ADR，字段/参数调整走普通评审。

恢复遵循 [ROLLBACK.md](../../ROLLBACK.md)：暂停受影响动作或回受测兼容版本，保留数据，不默认 reverse migration/恢复全库。生产切换/恢复/发布只按具体批准范围执行，本规划修订不授权生产操作。
