# T24：盘点来源差异和共享切换组

状态：PLANNED，产品未实现。代码基线：878b690。交付单元：来源盘点。

## 目标与范围

静态来源与授权一致性副本取并集，生成一份 source manifest；记录旧规则/对象/模式/政策/publication/身份/用户关系及旧译文字段，按共享 Feed 标记切换组。

修改范围：来源 manifest 格式和脱敏盘点证据。行为以 [C01–C11](../../INTERFACE-CONTRACTS.md) 为准，架构方向见 [ARCHITECTURE.md](../../ARCHITECTURE.md)。

## 依赖与执行条件

集成前置：无。

表中前置约束本交付的集成验收/完成，不禁止按已审接口和 fixture 独立开发。真实副本缺失时标该部分 BLOCKED；静态清单可先完成，不阻塞 T25 合成测试或其他开发

同一关键写入函数/迁移串行修改；公共路由、依赖、types 和 Compose 使用协调后的串行合并，不因共享文件冻结整个任务。独立工作可从已验收基线开分支，合入前 rebase/解决冲突并跑受影响契约；不得把 fixture 通过写成真实运行通过。

## 专项验收

1. 旧选择规则与新 Feed 差异逐源可追溯。
2. 代码/动态来源并集不漏。
3. 同 Feed 多来源切换组完整。
4. unsupported 保留原公开性/历史且不暗留 Spider。

专项反例与命令见 [tests.md](tests.md)。只验证本任务风险，不复制无关的重启/权限/生产授权测试。上线门禁和批次全量见 [ACCEPTANCE-MATRIX.md](../../ACCEPTANCE-MATRIX.md)。

## 交付与恢复

在 [report.md](report.md) 记录实现/环境/命令/实际结果、SHA/PR/CI、风险和相关证据；同 SHA/配置的公共证据可链接复用。产品仍 NOT_RUN。实质架构/权限语义变化补 ADR，字段/参数调整走普通评审。

恢复遵循 [ROLLBACK.md](../../ROLLBACK.md)：暂停受影响动作或回受测兼容版本，保留数据，不默认 reverse migration/恢复全库。生产切换/恢复/发布只按具体批准范围执行，本规划修订不授权生产操作。
