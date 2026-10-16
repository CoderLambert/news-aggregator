# T18：验证并接入可选 RSSHub 网关与标准路由

状态：PLANNED，产品未实现。代码基线：878b690。交付单元：RSSHub（含 T01）。

## 目标与范围

合并网关可行性与交付，映射声明式模板至受保护 HTTPS gateway；系统认证仅精确 origin/批准 route，不提供用户凭据型 Feed。

修改范围：ops/rss、Nginx profile、backend/api/rss/routes.py。行为以 [C01–C11](../../INTERFACE-CONTRACTS.md) 为准，架构方向见 [ARCHITECTURE.md](../../ARCHITECTURE.md)。

## 依赖与执行条件

集成前置：[T00](../T00/task.md)、[T02](../T02/task.md)、[T04](../T04/task.md)、[T16](../T16/task.md)。

表中前置约束本交付的集成验收/完成，不禁止按已审接口和 fixture 独立开发。缺 DNS/Token 只阻塞 RSSHub 运行/上线；参数验证和模板开发可先完成，native 路径不依赖本任务

同一关键写入函数/迁移串行修改；公共路由、依赖、types 和 Compose 使用协调后的串行合并，不因共享文件冻结整个任务。独立工作可从已验收基线开分支，合入前 rebase/解决冲突并跑受影响契约；不得把 fixture 通过写成真实运行通过。

## 专项验收

1. 真实 DNS/TLS/公网回流和私网防护。
2. 凭据不跨跳转/不进 DTO/OPML/日志。
3. 锁定路由如 Trending 的 Token/返回对象确认。
4. 无需浏览器/Redis/自定义路由。

专项反例与命令见 [tests.md](tests.md)。只验证本任务风险，不复制无关的重启/权限/生产授权测试。上线门禁和批次全量见 [ACCEPTANCE-MATRIX.md](../../ACCEPTANCE-MATRIX.md)。

## 交付与恢复

在 [report.md](report.md) 记录实现/环境/命令/实际结果、SHA/PR/CI、风险和相关证据；同 SHA/配置的公共证据可链接复用。产品仍 NOT_RUN。实质架构/权限语义变化补 ADR，字段/参数调整走普通评审。

恢复遵循 [ROLLBACK.md](../../ROLLBACK.md)：暂停受影响动作或回受测兼容版本，保留数据，不默认 reverse migration/恢复全库。生产切换/恢复/发布只按具体批准范围执行，本规划修订不授权生产操作。
