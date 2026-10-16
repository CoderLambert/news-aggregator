# ADR-004：共享 Feed 使用统一采集模式

状态：用户本轮Q3明确同意，覆盖原文4.1的个人关闭语义。

## 问题与证据

一个Miniflux物理Feed只有一个crawler设置，个人开关会改变其他用户的网络行为。

证据：[BASELINE-AUDIT.md](../BASELINE-AUDIT.md)、[OPERATIONS-AUDIT.md](../OPERATIONS-AUDIT.md)、[UPSTREAM-VERIFICATION.md](../UPSTREAM-VERIFICATION.md)。原始方向见[ARCHITECTURE.md](../ARCHITECTURE.md)，不改变Miniflux/PG/RSSHub分工。

## 决议与影响

mode由站点来源政策和管理员统一决定；V1不提供个人采集模式开关。个人取消不改变仍有他人或editorial_pin引用的Feed。

用户可决定是否订阅，不能以个人权限绕过来源政策。最后引用取消先暂停，不删除本地内容或个人记录。

## 验收与回滚

并发注册/取消的引用收敛；受限源即使管理员也不绕发布者政策；共享状态只采集不承载个人read/star。

对应任务与合同见[ARCHITECTURE-DECISIONS.md](../ARCHITECTURE-DECISIONS.md)、[INTERFACE-CONTRACTS.md](../INTERFACE-CONTRACTS.md)。任何新的架构变更须另立ADR审核；本ADR不授予生产修改、数据删除或批量回填权限。
