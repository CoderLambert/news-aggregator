# ADR-001：原文、文档位置与任务权威

状态：用户本轮明确采用审核定稿原文，且明确要求plans路径；详细任务拆分等待规划PR审核。

## 问题与证据

指定ARCHITECTURE路径原本不存在，原文第12节仍写features路径及粗T00–T10。

证据：[BASELINE-AUDIT.md](../BASELINE-AUDIT.md)、[OPERATIONS-AUDIT.md](../OPERATIONS-AUDIT.md)、[UPSTREAM-VERIFICATION.md](../UPSTREAM-VERIFICATION.md)。原始方向见[ARCHITECTURE.md](../ARCHITECTURE.md)，不改变Miniflux/PG/RSSHub分工。

## 决议与影响

原文578行逐字入库且不改写；本轮用户要求的plans路径、C01–C11及37项细分任务为新实施入口。

避免误把旧文档任务ID/路径当开发合同；未来引用用本目录和本轮新ID。

## 验收与回滚

原文哈希相等，所有任务链接/DAG一致；完整规划审核后才开发。

对应任务与合同见[ARCHITECTURE-DECISIONS.md](../ARCHITECTURE-DECISIONS.md)、[INTERFACE-CONTRACTS.md](../INTERFACE-CONTRACTS.md)。任何新的架构变更须另立ADR审核；本ADR不授予生产修改、数据删除或批量回填权限。
