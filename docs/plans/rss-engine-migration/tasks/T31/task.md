# T31：删除旧采集代码、依赖并统一部署入口

状态：IN_PROGRESS，隔离候选开发中，尚未集成/发布。候选基线：6a2cc025c338ef0308024151be4fbd796f7f3a39。交付单元：旧栈清理（含 T32）。

## 目标与范围

先抽离联网搜索等仍需安全工具，再删除 Scrapy/旧 Feed parser/网页 Provider/full worker 及依赖；同步 CI/脚本/镜像/文档和上一版本残留角色退出。

修改范围：crawler/、article_fetcher 旧专属模块、依赖、Docker/Compose、CI、部署文档。行为以 [C01–C11](../../INTERFACE-CONTRACTS.md) 为准，架构方向见 [ARCHITECTURE.md](../../ARCHITECTURE.md)。

## 依赖与执行条件

集成前置：[T30](../T30/task.md)。

表中前置约束本交付的集成验收/完成，不禁止按已审接口和 fixture 独立开发。T30 运行停止为前置；历史迁移/数据库列可保留惰性，不同发布强制 drop。最终镜像整体复验归 T33

同一关键写入函数/迁移串行修改；公共路由、依赖、types 和 Compose 使用协调后的串行合并，不因共享文件冻结整个任务。独立工作可从已验收基线开分支，合入前 rebase/解决冲突并跑受影响契约；不得把 fixture 通过写成真实运行通过。

## 专项验收

1. 静态 import 和运行追踪无隐藏抓取。
2. 研究搜索/索引/频道 worker 保留。
3. 新镜像无旧抓取包。
4. 从过渡版本升级能停止旧角色且默认启动不复活。

专项反例与命令见 [tests.md](tests.md)。只验证本任务风险，不复制无关的重启/权限/生产授权测试。上线门禁和批次全量见 [ACCEPTANCE-MATRIX.md](../../ACCEPTANCE-MATRIX.md)。

## 交付与恢复

在 [report.md](report.md) 记录实现/环境/命令/实际结果、SHA/PR/CI、风险和相关证据；同 SHA/配置的公共证据可链接复用。产品仍 NOT_RUN。实质架构/权限语义变化补 ADR，字段/参数调整走普通评审。

恢复遵循 [ROLLBACK.md](../../ROLLBACK.md)：暂停受影响动作或回受测兼容版本，保留数据，不默认 reverse migration/恢复全库。生产切换/恢复/发布只按具体批准范围执行，本规划修订不授权生产操作。
