# T13 阅读与个人已读交付进度

状态：代码已集成，显式 Miniflux 修复已接 T08/T09/T19；T27 合成真实浏览器联合验收已通过。未进行生产操作。

已实现：0056 NewsReadState 领域表；GET/PATCH `/api/me/news/{id}/read-state/`，缺记录 false/version0，显式写入用当前用户和文章 ACL，SQLite 首写保留后检查 expected_version。相同状态幂等，不推断 ReadingDay、不修改统计、不因正文更新或退订清除历史。接口使用 session/CSRF、个人 no-store、v1 错误格式，原站点只读和账号切换保护保留。

详情增加显式已读/未读按钮，查询缓存按用户和文章隔离，更新携带版本及 viewer header；冲突刷新确认状态，不假报成功。首访不再自动 POST 获取正文，已有排队任务仅附加只读轮询。available 可读；新内容代码复制保持原文，旧修复仅 explicit legacy。

验证（Python3.12.14，Node本地环境，独立临时DB）：

- 0056 空库迁移与 makemigrations --check：通过。
- `RUN_MAIN=true DJANGO_DB_PATH=/tmp/newshub-rss-readstate-tests.sqlite3 PYTHONPATH=backend:crawler /tmp/newshub-rss-coordinator-venv/bin/python -m pytest -q backend/api/tests/rss/test_reading_state.py backend/api/tests/rss/test_body_commit.py backend/api/tests/test_public_policy.py`：75 passed/6.12s。覆盖 A/B/匿名、退订保留、版本、严格输入、真实 session CSRF、只读及正文事务组合。
- 前端 typecheck/lint/build 通过；`npm run test:run`：87文件、580测试通过/9.04s。新按钮5测试，前一批自动抓取/Markdown相关36测试。
- 日志：`/tmp/newshub-rss-t13-backend.log`、`/tmp/newshub-rss-t13-readstate-frontend.log`、`/tmp/newshub-rss-t13-readstate-build.log`。

T27 真实浏览器已覆盖：390px 移动视窗与实际键盘操作、浅/深主题切换后的代码逐字符保留、真实目录点击滚动、A/B/匿名隔离、已读/收藏重载、退订后不可读、授权 fake AI、普通用户订阅摘要 Feed 后后台自动提取并首次打开即读、显式管理员修复。自动路径仅合成夹具启用全文能力，首次 News GET 前恰有一次原文请求；生产门禁仍默认关闭。详情及截图见 [T27 报告](../T27/report.md)。未验证：真实用户数据、真实手机软键盘、付费 AI/TTS provider 输出及用户最终签收；不以合成浏览器证明这些项目。

后续集成：显式修复仅当前授权且owner/binding/full_content模式已就绪时显示，POST refetch后轮询actor操作，pending_sync直到T09按fence接受或拒绝才结束；GET/打开/hover不入队。服务端查询full_content_provenance的时间推断字段采用SQL投影，列表仍不加载正文/provenance大字段。
