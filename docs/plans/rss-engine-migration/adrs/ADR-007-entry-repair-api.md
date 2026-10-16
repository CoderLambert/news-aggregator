# ADR-007：区分刷新与持久单篇正文修复

状态：PROPOSED，G0条件批准协议/隔离验证方案，G1再以T00实际契约验证冻结运行可行性。

## 问题与证据

2.3.3普通refresh非force，SDK fetch_entry_content默认update_content=false；容易虚构修复成功/上游持久化。

证据：[BASELINE-AUDIT.md](../BASELINE-AUDIT.md)、[OPERATIONS-AUDIT.md](../OPERATIONS-AUDIT.md)、[UPSTREAM-VERIFICATION.md](../UPSTREAM-VERIFICATION.md)。原始方向见[ARCHITECTURE.md](../ARCHITECTURE.md)，不改变Miniflux/PG/RSSHub分工。

## 决议与影响

官方SDK优先，允许最小注入受限session/transport落实总deadline与wire/解压后字节预算，仅最小扩展固定fetch-content的update_content=true参数，随后重新GET验证；刷新与修复为独立FeedOperation动作。

不自建爬虫或完整客户端。副作用GET仅由显式POST入队执行，页面GET/预览不触发。SDK扩展不满足则BLOCKED并更新ADR。

## 验收与回滚

T00/T04/T08验证持久结果、失败/未知结果核对、配额和授权；API文档/SDK/源码参考UPSTREAM-VERIFICATION。

对应任务与合同见[ARCHITECTURE-DECISIONS.md](../ARCHITECTURE-DECISIONS.md)、[INTERFACE-CONTRACTS.md](../INTERFACE-CONTRACTS.md)。任何新的架构变更须另立ADR审核；本ADR不授予生产修改、数据删除或批量回填权限。
