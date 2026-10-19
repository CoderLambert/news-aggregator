# T14：统一 AI/TTS 本地上下文与译文版本读取

状态：已集成，当前实现与历史专项及 2026-10-20 阅读差额见 report.md 和现行开发计划；真实产品联合验收仍 NOT_RUN。原合同基线：878b690。交付单元：AI 读取。

## 目标与范围

落实已确认 ADR-002，删除中文外链和聊天/推荐问题/研究隐式抓取；保留联网搜索。当前译文按 hash/用户/连接读取，旧任务结果 CAS，旧兼容字段不无条件回退。

修改范围：views、translation/shared_translations、speech、research、read helpers。行为以 [C01–C11](../../INTERFACE-CONTRACTS.md) 为准，架构方向见 [ARCHITECTURE.md](../../ARCHITECTURE.md)。

## 依赖与执行条件

集成前置：[T11](../T11/task.md)。

表中前置约束本交付的集成验收/完成，不禁止按已审接口和 fixture 独立开发。不依赖前端 T13 或对账 T09；用授权快照 fixture 开发，真实阅读/AI 全链在 T27

同一关键写入函数/迁移串行修改；公共路由、依赖、types 和 Compose 使用协调后的串行合并，不因共享文件冻结整个任务。独立工作可从已验收基线开分支，合入前 rebase/解决冲突并跑受影响契约；不得把 fixture 通过写成真实运行通过。

## 专项验收

1. available 传递 scope/revision/hash/完整性。
2. 只有摘要不当全文。
3. 旧异步译文不发布到新源文本且历史保留。
4. 问答/研究/TTS/推荐问题无旧 Provider，联网搜索保留。

专项反例与命令见 [tests.md](tests.md)。只验证本任务风险，不复制无关的重启/权限/生产授权测试。上线门禁和批次全量见 [ACCEPTANCE-MATRIX.md](../../ACCEPTANCE-MATRIX.md)。

## 交付与恢复

在 [report.md](report.md) 记录实现/环境/命令/实际结果、SHA/PR/CI、风险和相关证据；同 SHA/配置的公共证据可链接复用。产品仍 NOT_RUN。实质架构/权限语义变化补 ADR，字段/参数调整走普通评审。

恢复遵循 [ROLLBACK.md](../../ROLLBACK.md)：暂停受影响动作或回受测兼容版本，保留数据，不默认 reverse migration/恢复全库。生产切换/恢复/发布只按具体批准范围执行，本规划修订不授权生产操作。
