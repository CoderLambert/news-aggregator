# RSS 架构迁移规划审核入口

本 PR 只修订 docs/plans/rss-engine-migration/ 下规划文档，代码审计基线为 878b69081f8d5b3ae965bcf1c855390b059caa33；没有产品实现、数据库操作或生产切换。状态：REVIEW_REQUIRED。

用户确认的 [ARCHITECTURE.md](ARCHITECTURE.md) 原文保留。对 514410b 的审核修订补齐共享来源/文章所有权、政策更新、历史译文、基础元数据及停更权限；收敛 SDK 包装、审批、任务依赖和验收成本。细节见 [修订报告](PLANNING-REPORT.md)。

建议入口：[决议](ARCHITECTURE-DECISIONS.md) → [接口](INTERFACE-CONTRACTS.md) → [数据迁移](DATA-MIGRATION.md) → [任务](TASKS.md) / [依赖](DEPENDENCIES.md) → [验收](ACCEPTANCE-MATRIX.md) / [回滚](ROLLBACK.md)。历史源码/运维/上游证据保留为审计参考，其旧流程建议由修订合同覆盖。

26 个有效交付单元，11 个合并索引；T00–T36 历史编号均保留，合并不代表产品 DONE。来源迁移使用统一 manifest 和逐源结果，不再扩成 37+N 工单。首批建议 T00/T06/T16；T05 核心合同确认后尽早进入，T24 静态盘点可独立推进。

研究本地正文/保留联网搜索、独立已读/保留 ReadingDay、共享 Feed 管理员统一模式等已确认方向保持。实际运行均 NOT_RUN；缺 DNS/Token/副本/生产授权只阻塞对应运行或上线门禁，不冻结无关开发。本次文档/PR 修订不包含合并或后续产品实现。

校验命令见 [VALIDATION.md](VALIDATION.md)。
