# T20：交付发现订阅界面与连接健康展示

状态：PLANNED，产品未实现。代码基线：878b690。交付单元：发现 UI（含 T23 展示）。

## 目标与范围

统一关键词/URL/模板入口、个人分组、订阅状态和错误；使用 T09 健康 DTO 展示连接/同步延迟，不新增爬虫控制台。

修改范围：frontend/src/features/rss/、添加频道入口。行为以 [C01–C11](../../INTERFACE-CONTRACTS.md) 为准，架构方向见 [ARCHITECTURE.md](../../ARCHITECTURE.md)。

## 依赖与执行条件

集成前置：[T11](../T11/task.md)、[T16](../T16/task.md)、[T17](../T17/task.md)、[T19](../T19/task.md)。

表中前置约束本交付的集成验收/完成，不禁止按已审接口和 fixture 独立开发。UI 可先依据 fixture 开发；T09 真实健康和 RSSHub 条件分支在 T27 联合验收，RSSHub 未就绪隐藏可执行入口

同一关键写入函数/迁移串行修改；公共路由、依赖、types 和 Compose 使用协调后的串行合并，不因共享文件冻结整个任务。独立工作可从已验收基线开分支，合入前 rebase/解决冲突并跑受影响契约；不得把 fixture 通过写成真实运行通过。

## 专项验收

1. 关键词/URL 0/1/多候选接线。
2. 目录/token/直接 URL 都调用普通订阅校验。
3. 键盘/移动端/焦点和错误恢复。
4. 连接/initial_sync/ready 不虚构，私有操作不串用户。

专项反例与命令见 [tests.md](tests.md)。只验证本任务风险，不复制无关的重启/权限/生产授权测试。上线门禁和批次全量见 [ACCEPTANCE-MATRIX.md](../../ACCEPTANCE-MATRIX.md)。

## 交付与恢复

在 [report.md](report.md) 记录实现/环境/命令/实际结果、SHA/PR/CI、风险和相关证据；同 SHA/配置的公共证据可链接复用。产品仍 NOT_RUN。实质架构/权限语义变化补 ADR，字段/参数调整走普通评审。

恢复遵循 [ROLLBACK.md](../../ROLLBACK.md)：暂停受影响动作或回受测兼容版本，保留数据，不默认 reverse migration/恢复全库。生产切换/恢复/发布只按具体批准范围执行，本规划修订不授权生产操作。
