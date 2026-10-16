# ADR-005：分开文章关联、读取和主写权

状态：修订提案，等待规划审核；用户已确认的产品语义保持。本文件不授权生产切换、恢复或删除数据。

保留 News.url 唯一与旧 PK/FK；复合 EngineEntryMap 防止跨实例数字 ID 碰撞。完全相同规范 URL、身份和政策兼容时允许增加频道关联，不需要授予第二 Feed 主写权；无法证明兼容的冲突留记录，不覆写或扩大权限。

C02 明确唯一正文主写者及 body_owner_version；Source epoch、政策版本、任务 lease 分开。旧正文接管只转换写入权，不改历史文本/provenance/hash。新旧写入都检查文章级主写权，不能仅凭自己来源仍为 legacy 覆盖已接管文章。

publication=public/personal 与 paused/停更独立。历史只读不是第三种可见性；共享 Feed 的旧来源按最小切换组处理，成员查询保留旧关系并接入新映射。

T05/T07/T09/T11/T25/T26 分别验证约束、提交、成员、权限、切换和往返保留。没有为迁移拆分文章主表、重建用户关系或建设通用冲突审核平台。

事实依据：[BASELINE-AUDIT.md](../BASELINE-AUDIT.md)、[OPERATIONS-AUDIT.md](../OPERATIONS-AUDIT.md)、[UPSTREAM-VERIFICATION.md](../UPSTREAM-VERIFICATION.md)。实施入口：[接口合同](../INTERFACE-CONTRACTS.md)、[任务清单](../TASKS.md)、[验收矩阵](../ACCEPTANCE-MATRIX.md)。
