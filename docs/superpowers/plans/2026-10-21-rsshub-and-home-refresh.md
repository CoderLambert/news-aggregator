# RSSHub 接入与首页衔接 implementation plan

> 执行：superpowers:executing-plans，单一实现者；用户已明确要求一起实施。

**Goal:** RSSHub 别名走实际订阅链路，新增 RSS 可选择分类且首页及时更新。
**Architecture:** 扩展已有 routes/EngineAdapter；FeedBinding 保留别名/配置版本；个人分类属于 ChannelSubscription；共用 viewer 查询失效。
**Tech stack:** Django、SQLite、Miniflux2.3.3、React、TanStack Query、Python3.12/Node22。
**Spec:** docs/superpowers/specs/2026-10-21-rsshub-and-home-refresh-design.md

## Global constraints
保留全部旧 dirty 工作；不增加并行采集器、付费服务或宽松 SSRF；真实凭据不入测试；所有写入保留 owner/版本/取消围栏。

## Review focus
RSSHub 参数逃逸、网关 HTTPS 别名绕过、认证/重定向、共享分类跨用户影响、迟到成功和账号切换。

## Task 1 — 服务端地址与网关接入
- [ ] 编写 RED：Twitter别名解析、统一网关规范化/去重、未配置和非法路由、配置变化围栏与认证不外泄。
- [ ] 运行定向 pytest，观察失败。
- [ ] 扩展 routes.py、统一解析模块、模型/迁移、subscriptions/recommendations/OPML、EngineAdapter 和 Worker 围栏。
- [ ] 运行 routes/discovery/subscriptions/recommendations/adapter/control 定向回归。

## Task 2 — 分类与首页衔接
- [ ] 编写 RED：个人分类作用于历史/后续文章，其他用户不受影响；添加表单和详情分类；新增接受和完成刷新首页；账号切换隔离。
- [ ] 观察后端和 Vitest 失败后实现最小变更。
- [ ] 复用分类/分组 API，更新操作提交、owner 分类修改和投影；复用 newsKeys/channelKeys。
- [ ] 运行分类、频道、读者和前端定向回归。

## Task 3 — 集成与本地交付
- [ ] 一次相关后端门禁、前端全套/typecheck/lint/build、迁移漂移检查。
- [ ] 隔离真实引擎验证别名接入及分类；独立最终审查后单轮修复/受影响复验。
- [ ] 构建同版本 app/Worker；一致性备份后迁移并更新本地；桌面/412px 浏览器验证，保留用户数据。
- [ ] 记录准确候选摘要、真实 RSSHub/Twitter 状态、未运行项及回退。重叠产品提交继续延后。


## Local Docker delivery addendum
User authorized local RSSHub service deployment; Twitter skipped. Reuse pinned RSSHub and Nginx, add pinned Squid restricted to exact gateway TLS host. Pass proxy only for server-selected gateway feeds; include proxy in config fence. Preserve native private-network denial. Prove real GitHub RSSHub → Miniflux → subscription → local homepage, and private URL/CONNECT/redirect negatives. Back up local SQLite consistently, apply additive0078/0079, upgrade app/worker together, retain existing identities/bodies/feeds and rollback image. No production deployment.
