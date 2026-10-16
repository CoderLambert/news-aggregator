# T21：交付 OPML 预览、确认、导出与恢复界面

状态：PLANNED，产品未实现。代码基线：878b690。交付单元：OPML（含 T22）。

## 目标与范围

listparser 只读上传字节，预览 token 绑定 user/file/expiry；确认校验所选项/本人组后保存 request_hash。领域模型、API、UI 同一交付。

修改范围：backend/api/rss/opml.py、导入迁移、frontend RSS 导入组件。行为以 [C01–C11](../../INTERFACE-CONTRACTS.md) 为准，架构方向见 [ARCHITECTURE.md](../../ARCHITECTURE.md)。

## 依赖与执行条件

集成前置：[T19](../T19/task.md)。

表中前置约束本交付的集成验收/完成，不禁止按已审接口和 fixture 独立开发。组件可先独立于发现页实现，公共入口串行接线；真实上传浏览器在本任务或 T27 复用同版本证据

同一关键写入函数/迁移串行修改；公共路由、依赖、types 和 Compose 使用协调后的串行合并，不因共享文件冻结整个任务。独立工作可从已验收基线开分支，合入前 rebase/解决冲突并跑受影响契约；不得把 fixture 通过写成真实运行通过。

## 专项验收

1. 恶意 XML/深度/大小和凭据拒绝且预览零网络。
2. 确认后幂等、不同选择重放 409。
3. 部分失败只重试失败项。
4. 本人多组导出/再导入幂等，无账号全量/secret。

专项反例与命令见 [tests.md](tests.md)。只验证本任务风险，不复制无关的重启/权限/生产授权测试。上线门禁和批次全量见 [ACCEPTANCE-MATRIX.md](../../ACCEPTANCE-MATRIX.md)。

## 交付与恢复

在 [report.md](report.md) 记录实现/环境/命令/实际结果、SHA/PR/CI、风险和相关证据；同 SHA/配置的公共证据可链接复用。产品仍 NOT_RUN。实质架构/权限语义变化补 ADR，字段/参数调整走普通评审。

恢复遵循 [ROLLBACK.md](../../ROLLBACK.md)：暂停受影响动作或回受测兼容版本，保留数据，不默认 reverse migration/恢复全库。生产切换/恢复/发布只按具体批准范围执行，本规划修订不授权生产操作。
