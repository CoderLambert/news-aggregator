# 频道核验恢复与独立管理列表验收

本地交付已完成。入口：`http://127.0.0.1:18080/admin/rss/channels`。默认待处理已从 3 降为 0；全部 10 个公开频道已通过并可订阅。未部署生产，未提交、推送或创建 PR。

## 版本和范围

基线及当前 Git head：`b03a3dfb41911b06dfb24c31074f4faf60fe8845`；分支 `task/channel-recovery-20261021`，工作区含本次未提交改动。运行版本以 [candidate.json](channel-recovery-20261021/candidate.json) 的源码摘要、镜像 ID 为准，不能只用 Git head 代表这些改动。应用和 RSS Worker 使用相同不可变镜像 ID。

独立工作区位于 `/home/lambert/githubRepos/lambert/news-aggregator-channel-recovery-20261021`。原检出目录的数据库和两份未跟踪文档保持原样。保留了运行中的旧本地候选已有的当前实例目录、资料和订阅隔离修正，以及基础镜像的本地启动行为。

实现范围：新增迁移 0075/0076、持久化发送阶段和恢复关联、原 Worker 恢复/对账与最终围栏、只读分页列表、按管理员隔离的幂等批次及进度、独立页面和详情抽屉、运行概览入口、频道页共用详情入口、专用本地重启边界工具及回归测试。旧空 POST 只对账；新客户端明确提交动作和预期版本。

## 真实来源结果

| 来源 | 结果 | 实际引擎连接 | 说明 |
|---|---|---:|---|
| 美团技术团队 | PASS，可订阅 | 9 | 初次恢复创建成功后因 `/feed/` 与引擎 `/rss.xml` 不同而未确认；通过 Miniflux 唯一同源发现结果复用 Feed 9，没有第二次创建。保留原登记 URL，单独保存有效地址。 |
| WebKit | PASS，可订阅 | 10 | 恢复真实连接，确认当前采集策略。 |
| Martin Fowler | PASS，可订阅 | 11 | 恢复真实连接，确认当前采集策略。 |

[逐来源结果和完整性检查](channel-recovery-20261021/local-results.json)：原七个 Feed ID、十个原登记地址及固定七天日期下界均保持；原有文章没有删除；账号密码及管理权限字段保持。没有运行内容初始化、正文补抓、账号重建或凭据轮换。

旧三个未知操作最晚更新时间晚于旧引擎启动时间，不能证明最后一次可能的创建已结束。因此暂停指定本地控制器，短暂重启同一个 Miniflux 容器，核对停止/启动顺序后记录持久化边界。旧状态、错误和尝试次数均保留，通过明确解决标记解除阻塞。[原十个操作的逐字段保留检查](channel-recovery-20261021/audit-preservation.json) 与 [重启边界证据](channel-recovery-20261021/restart-boundary.json) 已保存。后续美团结果未知也保留，最终由新核验确认唯一连接解决。

## 验证证据

| 检查 | 结果 | 证据和边界 |
|---|---|---|
| Python 3.12 RSS/频道/维护回归 | PASS，662 项 | [原始日志](channel-recovery-20261021/backend-tests.log)。选择 `backend/api/tests/rss`、`test_channels.py`、`test_smart_channel_workspace.py`、`scripts/deploy/tests/test_rss_channel_recovery.py`；不是全仓库 pytest。 |
| 前端完整 Vitest | PASS，101 文件 / 712 项 | [原始日志](channel-recovery-20261021/frontend-tests.log)。包含列表、URL、倒计时、详情焦点、批次和切换账号后迟到响应。 |
| TypeScript | PASS | [日志](channel-recovery-20261021/typecheck.log)。 |
| ESLint | PASS，0 error | [日志](channel-recovery-20261021/lint.log)。有原有 `useSuggestedQuestions.ts` 一条 hook 依赖 warning。 |
| 前端构建 | PASS | 最终 bundle 与运行镜像源码摘要逐文件核对相同。 |
| 独立 Miniflux 2.3.3 | PASS | [结果](channel-recovery-20261021/isolated-engine.json)，真实 HTTPS 合成 Feed、复用旧未知、明确解析失败；不是生产/外部供应商证明。[复现夹具](../../tests/rss_engine_contract/recovery_lab/README.md)。专用容器、网络已清理。 |
| 本地真实引擎 | PASS | 上表三个来源；应用和控制器均为新候选，迁移已显式执行。 |
| 桌面浏览器 | PASS | 初始三个待处理、数量、中文/英文/原始与有效 RSS 搜索、空结果、刷新、后退、25/50、批次、倒计时、详情和 Escape 焦点恢复。 |
| 412px CSS 窄屏 | PASS | [边界数据](channel-recovery-20261021/mobile-metrics.json)：`innerWidth=412`，详情 `x=0`，宽度 393（扣除滚动条），高度 915，无横向溢出。校准了宿主缩放比例，最后恢复视口。 |
| 账号切换真实浏览器 | NOT_RUN | 自动化组件已覆盖迟到提交响应及缓存隔离；没有为了验收退出当前真实账号。 |
| GitHub CI / 全仓库 pytest | NOT_RUN | 本轮没有推送或 PR。 |

安全回归包含：私人来源/其他实例及账号隔离、CSRF、read_only、过期版本、取消、暂停、两个管理员线程合并、没有历史记录时不得创建、只读失败不能转为创建许可、再次超时不得循环创建、同源别名证据及跨域拒绝、列表多 Feed 状态一致性、聚合数量及分页。

明确解析失败可安全分类为 `feed_parse_failed`，不保留上游错误正文。依据 Miniflux 2.3.3 的 [创建处理](https://github.com/miniflux/v2/blob/2.3.3/internal/reader/handler/handler.go) 和 [API 返回](https://github.com/miniflux/v2/blob/2.3.3/internal/api/feed_handlers.go)：原生解析失败通过 HTTP 500 返回。其他未证实的 5xx/超时仍保守对账。

## 复核、决定和风险

进行了一轮独立只读整体复核，发现并修复：只读错误被误用为创建证明、未知连接仍开放订阅、行状态与筛选数量漂移、可变镜像标签不能证明控制器版本一致。定向回归经历失败到通过。随后真实引擎暴露的同源有效地址路径由实现者复核及正/负回归验证，未再做第二轮独立审查。

本轮决定：从最新可用 `origin/main` 隔离实现并保留本地目录隔离修正，代价是测试夹具需显式引擎身份；持久化独立有效地址证据并保留原 URL 锚点，代价是跨域或多候选跳转继续保持未知，需要人工确认。未遗留已知 Important / Critical 发现；大规模目录的数据库查询性能未做基准，不声称性能提升。

维护中修复了两处本地执行问题：旧启动脚本未自动迁移，现已显式完成 0075/0076；`docker cp` 保留宿主 0600 文件 UID 导致非 root 应用不能读重启凭据，现由应用身份创建自己的 0600 证据文件。原有备份和审计保留，没有放宽文件权限。0076 已采用先迁移、再启动新应用和 Worker 的顺序。

回退应先关闭核验恢复入口并暂停该控制器，切回记录的旧应用/Worker 镜像配置，保留新增列和审计表；不要逆向迁移或清理数据。旧代码不认识有效地址证据，回退后禁止重发这些旧未知操作。需要数据恢复时必须另行审核配套备份及引擎状态，不能把代码回退当成数据回退。

## 截图

[桌面初始列表](channel-recovery-20261021/desktop-before.jpg) · [批次接受](channel-recovery-20261021/desktop-batch.jpg) · [倒计时](channel-recovery-20261021/desktop-cooldown.jpg) · [桌面最终结果](channel-recovery-20261021/desktop-final.jpg) · [窄屏列表](channel-recovery-20261021/mobile-list.jpg) · [412px 成功详情](channel-recovery-20261021/mobile-detail.jpg)。
