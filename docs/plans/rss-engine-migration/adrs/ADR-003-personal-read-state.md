# ADR-003：保留阅读统计并新增独立已读状态

状态：用户本轮Q2明确同意。

## 问题与证据

现有ReadingDay是user/news/day遥测，没有可切换已读/未读；不能伪称已有已读表迁移。

证据：[BASELINE-AUDIT.md](../BASELINE-AUDIT.md)、[OPERATIONS-AUDIT.md](../OPERATIONS-AUDIT.md)、[UPSTREAM-VERIFICATION.md](../UPSTREAM-VERIFICATION.md)。原始方向见[ARCHITECTURE.md](../ARCHITECTURE.md)，不改变Miniflux/PG/RSSHub分工。

## 决议与影响

完整保留ReadingDay，新增NewsReadState(user,news)独立状态；无行默认未读，只显式PATCH，不从旧统计回填。

T05预定义schema，T12单独实现；不映射Miniflux共享status，不改变已有阅读统计。

## 验收与回滚

A/B互不污染；正文版本变化/退订不删除状态；ReadingDay计数/PK/FK不变。

对应任务与合同见[ARCHITECTURE-DECISIONS.md](../ARCHITECTURE-DECISIONS.md)、[INTERFACE-CONTRACTS.md](../INTERFACE-CONTRACTS.md)。任何新的架构变更须另立ADR审核；本ADR不授予生产修改、数据删除或批量回填权限。
