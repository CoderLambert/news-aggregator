# T18：完成报告

日期2026-10-16。离线参数/关闭配置交付READY_FOR_REVIEW；实际公网/Token门禁BLOCKED，整体T18为PARTIAL，不标DONE，不影响native。

| 记录 | 结果 |
| --- | --- |
| 实现 SHA / PR / CI | task/rss-T18-gateway，基线4ac939e；最终SHA以Git回执为准。PR/CI未执行 |
| T18-A1 BLOCKED | 无真实DNS/公网域名/TLS/回流配置；未证明Miniflux公网到私网重定向/DNS重绑定/IPv6边界。保持FETCHER_ALLOW_PRIVATE_NETWORKS=0，不绕过 |
| T18-A2 PARTIAL | 85离线参数/凭据URL/精确origin+route选择与secret入口专项PASS；实际Nginx+本地测试CA/合成上游验证Basic Auth、头剥离、302拒绝/no Location、500不透传和选定logs无合成secret。真实Token/引擎/DTO/OPML/日志端到端仍BLOCKED |
| T18-A3 BLOCKED | 固定源码确认Trending须GITHUB_ACCESS_TOKEN，输出repository而非完整news；镜像OCI revision与该源码一致。无真实服务Token，未请求真实Trending/Issue、未核对对象质量/Token public-only scope |
| T18-A4 隔离PASS | 固定官方RSSHub仅health验证：UID1000/只读rootfs/memory64项/512MiB容器cap，无Redis服务/浏览器服务/自定义route；实际镜像browserCache空。真实路由质量与完整资源峰值未验证 |
| 命令/版本 | tests.md离线85 passed in0.12s，退出0；verify_isolated.py退出0；sh -n/git diff --check通过。实际Nodev24.22.0/linux-amd64；主机专项Python3.12.14 |
| 证据 | [upstream.lock.json](../../../../../ops/rss/T18/upstream.lock.json)、[实际隔离输出](../../../../../ops/rss/T18/evidence.json)、[接口/限制/复现](../../../../../ops/rss/T18/README.md)。RSSHub digest1945d316…，source8e94b949…、AGPL3保留T16许可证 |
| 实现评审 | 待主调度审查；不会以合成测试替代公网/凭据高风险实际验收 |
| 资源/副作用 | 仅新建newshub-rss-t18-ad699db3742c及临时CA/token/配置，project-label全量检查容器/卷/网络清空；本地固定镜像缓存留审。未动用户DB、existing服务、DNS或生产secret |
| 生产批准/执行 | NOT_RUN；无部署、启用模板、域名申请、main合并或生产变更 |

实现routes.py纯标准库解析/render两种声明式schema，query/percent/路径/URL/凭据选项拒绝；issue仓库还需系统明确批准。gateway_target仅候选计划，gateway_request当前LIVE_APPROVALS为空，即使enabled=true仍失败；公开DTO始终executable=false。T16目录、API/OPML、现有Compose/模型/依赖无改动。

额外明确门禁：EngineAdapter当前create_feed没有publisher Basic Auth配置，API session禁跳转不代表Miniflux publisher禁跳转。未来需协调最小适配/配置和真实运行证明后才能加入reviewed approval；GatewayRequest.follow_redirects=false只是必须落实的合同，不能冒充已实现网络取消/拒绝。Nginx关闭候选不自动附加任何真实secret。

开发完成、集成验收和生产放行分别记录。缺必需运行结果不能标 DONE；其他任务可依已审合同继续开发。详见 [task.md](task.md)、[tests.md](tests.md) 和 [全局验收矩阵](../../ACCEPTANCE-MATRIX.md)。
