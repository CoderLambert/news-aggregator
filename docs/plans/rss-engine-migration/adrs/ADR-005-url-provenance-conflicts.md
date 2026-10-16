# ADR-005：保留 URL 唯一约束并隔离来源冲突

状态：PROPOSED，待本规划PR独立审核。

## 问题与证据

News.url全局唯一且多个逻辑频道可收同文；不同政策的正文可能借复用News扩大可见范围。

证据：[BASELINE-AUDIT.md](../BASELINE-AUDIT.md)、[OPERATIONS-AUDIT.md](../OPERATIONS-AUDIT.md)、[UPSTREAM-VERIFICATION.md](../UPSTREAM-VERIFICATION.md)。原始方向见[ARCHITECTURE.md](../ARCHITECTURE.md)，不改变Miniflux/PG/RSSHub分工。

## 决议与影响

保留旧PK与URL唯一；增加复合EngineEntryMap及body主写绑定。仅身份/政策均证明兼容时复用News；否则隔离冲突并记录阻塞，不覆盖正文或提升权限。

不为RSS换底层顺带拆文章表或重建用户FK；某些跨Feed冲突会等待人工审查，这是明确边界。

## 验收与回滚

T05唯一键及原FK、T07正文CAS、T11跨来源/用户泄漏、T26副本迁移共同通过；政策证据不足即BLOCKED。

对应任务与合同见[ARCHITECTURE-DECISIONS.md](../ARCHITECTURE-DECISIONS.md)、[INTERFACE-CONTRACTS.md](../INTERFACE-CONTRACTS.md)。任何新的架构变更须另立ADR审核；本ADR不授予生产修改、数据删除或批量回填权限。
