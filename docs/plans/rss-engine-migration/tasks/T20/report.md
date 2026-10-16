# T20 发现与订阅界面

状态：IMPLEMENTED_PARTIAL，健康DTO已接线，真实浏览器验收待T27。

添加频道入口使用同一弹窗搜索固定本地目录、显式发现网站或直接RSS地址。网站0/1/多候选均要求用户选择；目录/候选token/直接URL统一T19校验，支持本人多组与actor幂等key。公开目录GET只有已有授权文章预览和当前用户订阅状态，未知模板不可执行。OPML从频道管理进入。

连接操作与首次同步分别表达：注册成功只显示来源已连接及后台首次同步提示，不冒充文章ready。个人查询按viewer建键，账号变更取消并清理包含个人来源信息的目录缓存。输入错误可重新查询，原生dialog有焦点/关闭处理。

验证：前端发现0/1/3、直接URL分组/viewer/key、不可执行模板、OPML和现有频道/会话测试共36 passed（1.24s），typecheck/lint通过；后端目录隐私零网络、OPML、订阅与旧读取回归129 passed（19.35s）。日志 `/tmp/newshub-rss-t20-ui.log`、`/tmp/newshub-rss-t20-tests.log`。真实浏览器移动端/键盘与引擎健康联动未执行。

连接健康补充：个人连接状态与管理员增量/full retained时间独立展示，只有匹配instance/account/sync_worker且60秒内的本地heartbeat可报告engine_ready；无GET网络调用。T20/OPML/频道14项UI通过，typecheck/lint/build通过。Compose app只新增非秘密引擎identity和只读heartbeat卷，rss-sync命令接完整worker；管理员endpoint权限/no-store/未知状态与publish_time_inferred投影均有专项。
