# T06：安全转换已有 HTML 并保持代码文本

状态：PLANNED，产品未实现。代码基线：878b690。交付单元：纯转换。

## 目标与范围

锁定 nh3/markdownify；只处理已取得字符串，解析相对资源后安全清理和 Markdown 转换，不识别网页主体、不访问网络、不用旧代码修复器。

修改范围：backend/api/rss/content.py、转换依赖/fixture。行为以 [C01–C11](../../INTERFACE-CONTRACTS.md) 为准，架构方向见 [ARCHITECTURE.md](../../ARCHITECTURE.md)。

## 依赖与执行条件

集成前置：无。

表中前置约束本交付的集成验收/完成，不禁止按已审接口和 fixture 独立开发。纯函数专项即可验收；无需生产授权、引擎、重启/租约/跨用户等通用反例。浏览器渲染在 T13/T27 验证

同一关键写入函数/迁移串行修改；公共路由、依赖、types 和 Compose 使用协调后的串行合并，不因共享文件冻结整个任务。独立工作可从已验收基线开分支，合入前 rebase/解决冲突并跑受影响契约；不得把 fixture 通过写成真实运行通过。

## 专项验收

1. 脚本/event/危险 scheme/内部媒体拒绝。
2. 标题表格列表引用代码保真。
3. 单条超限明确拒收。
4. 同输入/版本确定 hash 且不改历史正文。

专项反例与命令见 [tests.md](tests.md)。只验证本任务风险，不复制无关的重启/权限/生产授权测试。上线门禁和批次全量见 [ACCEPTANCE-MATRIX.md](../../ACCEPTANCE-MATRIX.md)。

## 交付与恢复

在 [report.md](report.md) 记录实现/环境/命令/实际结果、SHA/PR/CI、风险和相关证据；同 SHA/配置的公共证据可链接复用。产品仍 NOT_RUN。实质架构/权限语义变化补 ADR，字段/参数调整走普通评审。

恢复遵循 [ROLLBACK.md](../../ROLLBACK.md)：暂停受影响动作或回受测兼容版本，保留数据，不默认 reverse migration/恢复全库。生产切换/恢复/发布只按具体批准范围执行，本规划修订不授权生产操作。
