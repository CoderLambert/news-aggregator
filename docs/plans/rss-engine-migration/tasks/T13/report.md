# T13 阅读与个人已读交付进度

状态：部分集成，显式 Miniflux 修复接线待 T08/T19；浏览器联合验收待 T27。未进行生产操作。

已实现：0056 NewsReadState 领域表；GET/PATCH `/api/me/news/{id}/read-state/`，缺记录 false/version0，显式写入用当前用户和文章 ACL，SQLite 首写保留后检查 expected_version。相同状态幂等，不推断 ReadingDay、不修改统计、不因正文更新或退订清除历史。接口使用 session/CSRF、个人 no-store、v1 错误格式，原站点只读和账号切换保护保留。

详情增加显式已读/未读按钮，查询缓存按用户和文章隔离，更新携带版本及 viewer header；冲突刷新确认状态，不假报成功。首访不再自动 POST 获取正文，已有排队任务仅附加只读轮询。available 可读；新内容代码复制保持原文，旧修复仅 explicit legacy。

验证（Python3.12.14，Node本地环境，独立临时DB）：

- 0056 空库迁移与 makemigrations --check：通过。
- `RUN_MAIN=true DJANGO_DB_PATH=/tmp/newshub-rss-readstate-tests.sqlite3 PYTHONPATH=backend:crawler /tmp/newshub-rss-coordinator-venv/bin/python -m pytest -q backend/api/tests/rss/test_reading_state.py backend/api/tests/rss/test_body_commit.py backend/api/tests/test_public_policy.py`：75 passed/6.12s。覆盖 A/B/匿名、退订保留、版本、严格输入、真实 session CSRF、只读及正文事务组合。
- 前端 typecheck/lint/build 通过；`npm run test:run`：87文件、580测试通过/9.04s。新按钮5测试，前一批自动抓取/Markdown相关36测试。
- 日志：`/tmp/newshub-rss-t13-backend.log`、`/tmp/newshub-rss-t13-readstate-frontend.log`、`/tmp/newshub-rss-t13-readstate-build.log`。

未验证：真实浏览器移动端/主题/TOC、用户实际数据、完整后台预获取与显式修复操作。T11入口集成与后续 T08 操作接线后补受影响测试，不将组件测试当浏览器证据。
