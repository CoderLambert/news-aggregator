# ADR-002：研究与翻译的正文来源边界

状态：用户本轮Q1明确同意。

## 问题与证据

中文译文链接、研究fetch_article/fetch_webpage和聊天推荐仍调用旧正文Provider或排队，与彻底删除旧提取体系冲突。

证据：[BASELINE-AUDIT.md](../BASELINE-AUDIT.md)、[OPERATIONS-AUDIT.md](../OPERATIONS-AUDIT.md)、[UPSTREAM-VERIFICATION.md](../UPSTREAM-VERIFICATION.md)。原始方向见[ARCHITECTURE.md](../ARCHITECTURE.md)，不改变Miniflux/PG/RSSHub分工。

## 决议与影响

文章翻译仅本地/Miniflux内容；研究保留既有联网搜索，网页正文工具仅查已同步内容。未收录网页返回搜索摘要/链接及能力说明，不偷偷恢复Jina/旧抓取。

这是已确认的能力差异；研究不能承诺任意新URL正文。共同HTTP安全工具可为既有搜索保留，但不能携带旧提取算法。

## 验收与回滚

T14独立契约/真实AI上下文与T31零旧依赖扫描；用户身份/译文历史/研究记录保留。

对应任务与合同见[ARCHITECTURE-DECISIONS.md](../ARCHITECTURE-DECISIONS.md)、[INTERFACE-CONTRACTS.md](../INTERFACE-CONTRACTS.md)。任何新的架构变更须另立ADR审核；本ADR不授予生产修改、数据删除或批量回填权限。
