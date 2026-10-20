# 通用 RSSHub 本地交付，等待用户验收

已按用户要求停止剩余测试并部署本地版本。当前镜像 `newshub:rsshub-9703410c9f5d`，app与rss-sync一致；原worktree HEAD887194ab加脏改动，未提交/推送。生产未部署。

入口 `http://127.0.0.1:18080/channels`。强制刷新后可粘贴 `rsshub://freecomputerbooks`、`rsshub://36kr/newsflashes`、`rsshub://hackernews/newest?limit=3`，也支持其他合法命名空间和参数；不再逐条添加路由白名单。Twitter继续暂停。没有新增来源账号或凭据要求；需要认证的上游不保证可用。

保留已有频道、Feed、账号、正文、个人分类和发布审核。原Feed13保持原地址/版本哈希。无新数据库迁移，升级前已保存一致SQLite备份和配置副本。新通用来源采用摘要、Feed-only与七天下界，不额外启动Miniflux正文抓取。

网络边界变为固定站点网关 + RSSHub内部sandbox + 专用公网出口代理。Miniflux原有私网拒绝开关和精确网关CONNECT代理保留；RSSHub无法直接出网，统一出口拒绝私网/元数据/Fake-IP等目标。DoH仅供此本地RSSHub出口使用，不改宿主配置。详情见[运行说明](../../ops/rss/local/README.md)。

停止前已有定向结果：后端111项通过，UI30项通过，构建/类型检查完成；真实隔离RSSHub直接返回FreeComputerBooks、HackerNews、36kr的200结果。它们不等于通用订阅在真实本地Miniflux中的最终验收。

**未完成或失败：** 出口探测在8个私网/IPv6等拒绝样例之后，于外部`httpbingo`跳转样例的状态/历史断言失败；用户要求停止后未继续定位或重跑。该项不能记为PASS。新的全量回归、独立复核、通用路由的Miniflux完整流程与浏览器验收均未完成，由用户直接实测；不宣称全面验证通过。

本地应用、Worker、RSSHub运行状态已确认；具名隔离实验服务正在清理，正式本地服务保留。原始过程记录在 `.superpowers/sdd/2026-10-21-rsshub-generic/`。
