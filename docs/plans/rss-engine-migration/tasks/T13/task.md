# T13：保留阅读体验并提供个人已读状态

状态：PLANNED，产品未实现。代码基线：878b690。交付单元：阅读（含 T12）。

## 目标与范围

详情可读 available/unknown，移除首访自动抓取，新代码不修复改写；增加用户已读 DDL/API/组件，ReadingDay 原统计保持。显式重试通过操作 API。

修改范围：frontend 阅读组件/helper/types、backend/rss/reading.py、已读迁移。行为以 [C01–C11](../../INTERFACE-CONTRACTS.md) 为准，架构方向见 [ARCHITECTURE.md](../../ARCHITECTURE.md)。

## 依赖与执行条件

集成前置：[T11](../T11/task.md)。

表中前置约束本交付的集成验收/完成，不禁止按已审接口和 fixture 独立开发。依据固定 API fixture 可并行开发；真实修复和后台预获取在 T27 联合验收，不依赖 T09 才开始 UI

同一关键写入函数/迁移串行修改；公共路由、依赖、types 和 Compose 使用协调后的串行合并，不因共享文件冻结整个任务。独立工作可从已验收基线开分支，合入前 rebase/解决冲突并跑受影响契约；不得把 fixture 通过写成真实运行通过。

## 专项验收

1. 首次打开/hover/搜索/切组无 fetch-full。
2. 代码复制/表格/TOC/主题/移动端保真。
3. A 已读不影响 B 且不修改 ReadingDay。
4. 正文更新/退订不重置已读，重复修复使用本人操作视图。

专项反例与命令见 [tests.md](tests.md)。只验证本任务风险，不复制无关的重启/权限/生产授权测试。上线门禁和批次全量见 [ACCEPTANCE-MATRIX.md](../../ACCEPTANCE-MATRIX.md)。

## 交付与恢复

在 [report.md](report.md) 记录实现/环境/命令/实际结果、SHA/PR/CI、风险和相关证据；同 SHA/配置的公共证据可链接复用。产品仍 NOT_RUN。实质架构/权限语义变化补 ADR，字段/参数调整走普通评审。

恢复遵循 [ROLLBACK.md](../../ROLLBACK.md)：暂停受影响动作或回受测兼容版本，保留数据，不默认 reverse migration/恢复全库。生产切换/恢复/发布只按具体批准范围执行，本规划修订不授权生产操作。
