# Feed policy：独立审查与候选上线门禁

2026-10-16；审查者：T04/T11/T14 delegated worker。本文记录源码边界与操作要求，不是生产执行记录；生产未操作。实现最终 SHA、专项结果由本次政策补丁报告记录。

## 当前候选范围

- `RSS_FULL_CONTENT_ENABLED=0` 是独立全文抓取能力门禁，web 与 rss-sync 必须取同值。关闭时普通新 Feed 使用 `feed`；管理员显式切换、显式 refetch、遗留 full binding 的新抓取均不得绕过。禁用、暂停、降级到 feed 必须仍可执行。
- `RSS_DEFAULT_FEED_MODE` 只是门禁开放后的默认偏好，单独设为 `feed` 不能证明禁止全文抓取。门禁开放且来源政策允许时，普通公开文章 Feed 恢复 ARCH 4.1 默认自动尝试正文；已确认原生全文 Feed 仍采用 feed 模式。没有永久将普通 Feed 降级的合同变更。
- 当前候选不新增代理或逐条自研抓取器。尚无受限公开域名跳转前阻断证据，因此不能仅因 native block filter 测试通过就开启一般全文能力。RSSHub 的独立 DNS/凭据门禁不阻塞符合本范围的原生 feed 模式。

## 原生规则可证明什么

Miniflux 2.3.3 `CreateFeed` 先复制过滤配置，再立即处理条目；`disabled=true` 也不阻止首次 crawler。因此服务器批准的规则必须与首次 create 原子携带，后续 update 要 GET 核对，不能先抓再补规则。[handler 源码](https://raw.githubusercontent.com/miniflux/v2/2.3.3/internal/reader/handler/handler.go)

`block_filter_entry_rules` 使用 `EntryURL=<RE2>`，多行 block 规则为任一匹配即阻断；无效表达式被忽略。必须证明生成规则在真实引擎有效，不能只以 Python 正则测试代替。该规则只匹配 URL，避免旧 blocklist 对标题/作者/标签的额外匹配。[filter 源码](https://raw.githubusercontent.com/miniflux/v2/2.3.3/internal/reader/filter/filter.go)

常规路径在抓取前过滤，但命中会丢弃整条 entry，不能称为“保留摘要、仅禁正文”。过滤在 URL rewrite 前；显式 refetch 的 `ProcessEntryWebPage` 不执行上述过滤，需另外校验引擎当前 entry URL 和当前来源政策，不能仅信任旧 News URL。[processor 源码](https://raw.githubusercontent.com/miniflux/v2/2.3.3/internal/reader/processor/processor.go)

HTTP redirect 默认跟随。私网 IP 检查不等价于公开出版者域名政策；EntryURL 过滤不覆盖 rewrite 后目标和重定向链。因此直接禁止链接零命中证据不证明跳转保护。[fetcher 源码](https://raw.githubusercontent.com/miniflux/v2/2.3.3/internal/reader/fetcher/request_builder.go)

## 首次上线、降级与关闭门禁

以下是获准环境中的操作顺序。所有资源先按既有 manifest 核对 engine UUID、account ID、项目、两库和镜像 digest；不扫描或修改其它账号、项目或用户库。环境配置查看只能输出非敏感字段，不打印完整 secrets/env。

1. 阻止新的控制请求，停止 rss-sync/其它持有该账号写凭据的调用方。先停止 Miniflux 实例并确认进程退出；仅停止 NewsHub worker 不停止 Miniflux 自有轮询。若仍有请求执行或状态未知，不宣称“零后续请求”。
2. 对含旧数据的引擎，以相同数据卷与固定身份、临时 `DISABLE_SCHEDULER_SERVICE=1` 启动仅 API 的 Miniflux；不要同时启动 collector。该官方配置只禁 scheduler，API create/refetch 仍会产生请求，故仍需保持入口关闭、限制维护操作。[官方配置](https://miniflux.app/docs/configuration.html#disable-scheduler-service)
3. 用固定账号列出全部 feeds，记录 `feed_id / crawler / disabled` 和规则摘要；与本地 FeedBinding 清单逐条对应。未知或无对应项保持 disabled，不认领到其它来源。通过既有维护控制流程把候选允许项降至 `crawler=false`，其它项 `disabled=true`；每次修改 GET 核对。同步本地 desired/applied policy 版本，不只改远端标志后伪称本地已收敛。
4. 核对 web、rss-sync 的有效 `RSS_FULL_CONTENT_ENABLED=0`；全部允许活动 feeds 必须 `crawler=false`。任一未知结果、仍活动的 crawler、规则不符或身份不符均不得恢复 scheduler。关闭应用开关不会自动修改已有远端 feed，不能跳过本步骤。
5. 仅在核对完成后恢复普通 scheduler，再开放 gate-off 的 collector/控制入口。验证普通新 Feed 为 feed、管理员 full/refetch 被拒、feed 刷新正常；保存脱敏清单、时间、配置与镜像标识。此过程不逆向迁移、不恢复旧库，也不自动删除历史正文/译文。

## 重新开放全文能力

先取得独立政策审查及该引擎版本/网络配置的受限目标 redirect/rewrite 验证，明确覆盖范围与未知项；简单更改环境变量不是验收证据。再按 quiesce → 当前来源政策和规则核对 → 更新/GET → 恢复的顺序启用；已有 binding 不因为开关变化自动改成 full。源政策收紧同样需要暂停与远端收敛，不能只更新本地读取权限。

最少验收反例：首次 create 混合允许/禁止直接链接（禁止目标请求数为 0，允许项正常）；大小写、子域、尾点、端口、相似域名；动态 SourceConfig 禁止域名；显式 refetch 引擎 URL 与旧 News URL 不同；gate-off 管理员绕过、遗留 full binding、禁用/降级可达；允许链接跳转到禁止目标单列结果。未通过的跳转项保持未通过，不能与 direct-link PASS 合并。
