# NewsHub RSS 架构迁移规划审核入口

本PR只提交规划文档；没有产品实现、迁移、生产配置或来源切换。最新代码审计基线：`878b69081f8d5b3ae965bcf1c855390b059caa33`。规划状态：REVIEW_REQUIRED。

建议阅读顺序：[架构原文](ARCHITECTURE.md) → [审计事实](BASELINE-AUDIT.md) / [运维](OPERATIONS-AUDIT.md) / [上游](UPSTREAM-VERIFICATION.md) → [独立决议](ARCHITECTURE-DECISIONS.md) → [接口合同](INTERFACE-CONTRACTS.md) → [数据迁移](DATA-MIGRATION.md) → [任务](TASKS.md) / [DAG](DEPENDENCIES.md) → [验收](ACCEPTANCE-MATRIX.md) / [回滚](ROLLBACK.md)。

37个已定义主节点，每项含task/tests/report；T29是汇总门禁，实际单源工单N须授权盘点后实例化，因此最终节点数37+N。所有产品报告仍NOT_STARTED/NOT_RUN。首批建议T00/T15/T24证据工作；T00后可安排T02/T04/T06首组实现，最多3项且文件不重叠。

用户已确认：采用审核原文；研究只读同步正文/保留联网搜索；新增独立已读状态；共享Feed模式统一管理。其余技术ADR/初始参数/详细计划等待本PR审核。完成定义不降低，真实条件缺失标BLOCKED，规划审核不代表生产授权。

本轮验证、独立审核与PR信息见[PLANNING-REPORT.md](PLANNING-REPORT.md)。
