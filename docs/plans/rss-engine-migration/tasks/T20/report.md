# T20 发现与订阅界面

状态：已集成；2026-10-17 错误恢复差额 IMPLEMENTED / 专项 TESTED，见 [PR #94](https://github.com/CoderLambert/news-aggregator/pull/94)。以下既往 T27 合成浏览器证据保留为历史记录；本轮真实浏览器、真实来源及生产验收 NOT_RUN。

添加频道入口使用同一弹窗搜索固定本地目录、显式发现网站或直接RSS地址。网站0/1/多候选均要求用户选择；目录/候选token/直接URL统一T19校验，支持本人多组与actor幂等key。公开目录GET只有已有授权文章预览和当前用户订阅状态，未知模板不可执行。OPML从频道管理进入。

连接操作与首次同步分别表达：注册成功只显示来源已连接及后台首次同步提示，不冒充文章ready。个人查询按viewer建键，账号变更取消并清理包含个人来源信息的目录缓存。输入错误可重新查询，原生dialog有焦点/关闭处理。

验证：前端发现0/1/3、直接URL分组/viewer/key、不可执行模板、OPML和现有频道/会话测试共36 passed（1.24s），typecheck/lint通过；后端目录隐私零网络、OPML、订阅与旧读取回归129 passed（19.35s）。日志 `/tmp/newshub-rss-t20-ui.log`、`/tmp/newshub-rss-t20-tests.log`。T27后续已实际验证390px移动端、Enter/Tab/Escape、健康联动与0/1/3候选，不把组件测试当作该浏览器证据。

连接健康补充：个人连接状态与管理员增量/full retained时间独立展示，只有匹配instance/account/sync_worker且60秒内的本地heartbeat可报告engine_ready；无GET网络调用。T20/OPML/频道14项UI通过，typecheck/lint/build通过。Compose app只新增非秘密引擎identity和只读heartbeat卷，rss-sync命令接完整worker；管理员endpoint权限/no-store/未知状态与publish_time_inferred投影均有专项。

## 2026-10-17：按失败阶段恢复（RSS T20）

基线 `2e3254c890f52af626aa7d2400097301bf550d14`；功能提交 [`add9d64e695d74c3edc4841b6dd54a943efbaa1f`](https://github.com/CoderLambert/news-aggregator/commit/add9d64e695d74c3edc4841b6dd54a943efbaa1f)；[PR #94](https://github.com/CoderLambert/news-aggregator/pull/94)。先对照 T16/T17/T19/T20 及旧 PR #78，确认目录、发现和普通订阅校验已有，只修复现有恢复路径的缺口。

发现 POST 失败原先没有可执行恢复动作；保存或连接失败时统一按钮又会误读目录/发现。本轮为目录 GET、发现 POST、发现结果 GET、订阅保存 POST、连接 GET 提供各自恢复动作。订阅重试冻结选择、分组和幂等键；GET 错误停止轮询，恢复不重复订阅。按 viewer 重建会话，旧账号的失败请求、分组和晚到结果不进入新账号。已保存但连接未知时清楚显示两种状态，不虚构已连接/文章 ready。

自动化证据：RSS 专项 **26 passed / 3 files**；频道与 API 关联回归 **32 passed / 4 files**（两组存在重叠）；完整前端 typecheck、两文件 ESLint 与 diff 检查通过。Node `v24.19.0`、主线原锁文件；精确命令见 [tests.md](tests.md)。独立审核代理已检查两文件差异、原接口合同、Workspace API/Modal 及后端操作 DTO，未发现必须修复的 P1/P2；PR CI 未完成前不合并，实际 CI 和合并状态以 PR 为准。

边界：没有改后端、迁移、公共接口、依赖或 Miniflux 架构。真实浏览器/390px 移动端、真实来源连接和人工产品验收本轮 **NOT_RUN**，本交付不冲销 T27 最终验收。
