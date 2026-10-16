# ADR-006：演练后封存兼容回滚版本

状态：修订提案，等待规划审核；用户已确认的产品语义保持。本文件不授权生产切换、恢复或删除数据。

现有脚本要求 schema exact-match 且角色默认含 crawler。T03 适配工具、服务角色和两库恢复；不依赖阅读 ACL 开发完成，不提供未经演练的生产基点。

T26 合并原 T36：选包含完整 fence、available/ACL/译文读取的候选镜像，在隔离副本完成迁移/应用回滚/两库恢复，通过后封存 SHA/digest/schema/manifest。候选测试不要求先有封存证明；生产 T29 必须已有封存产物。

默认同 schema 最简单。T05 只交付核心 DDL，目录/已读/OPML 随所属功能迁移；后续 schema 变化重新验证兼容目标，不一概要求 ADR，不以 migration 子集当证明。普通回滚保留新数据、不 reverse migration、不恢复库；灾难恢复另决定恢复点/RPO。

复用同版本演练证据，删除旧栈后的最终镜像仍需恢复/重启复验。执行权限沿用已有部署和变更记录，不自建审批文件协议。

事实依据：[BASELINE-AUDIT.md](../BASELINE-AUDIT.md)、[OPERATIONS-AUDIT.md](../OPERATIONS-AUDIT.md)、[UPSTREAM-VERIFICATION.md](../UPSTREAM-VERIFICATION.md)。实施入口：[接口合同](../INTERFACE-CONTRACTS.md)、[任务清单](../TASKS.md)、[验收矩阵](../ACCEPTANCE-MATRIX.md)。
