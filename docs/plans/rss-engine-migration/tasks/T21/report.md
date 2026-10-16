# T21 OPML 交付进度

状态：IMPLEMENTED_BACKEND；UI 与 worker 接线进行中，生产 NOT_RUN。

领域 DDL 0057 独立保存用户预览、上传 hash、限时签名 token、确认 request hash 与逐项结果。上传最多1MiB/500 feeds，XML实体/DTD/外部引用禁用、深度16和节点10000上限；listparser 只接 bytes，预览不联网。规范化 URL 去重并合并多组，凭据 URL 不保存。

确认严格检查本人预览/选择/分组；新组为用户明确映射，重复确认同请求复用结果，改变选择409。逐项 durable intent 委托 T19；成功项目不重试，明确失败可选项重试，unknown/manual_blocked 不可绕过控制门禁。导出只含本人订阅及多组，序列化XML，不含引擎账号/secret。

实测：Python3.12.14 coordinator venv，独立临时SQLite。`RUN_MAIN=true DJANGO_DB_PATH=/tmp/newshub-rss-t21-tests.sqlite3 PYTHONPATH=backend:crawler /tmp/newshub-rss-coordinator-venv/bin/python -m pytest -q backend/api/tests/rss/test_opml_import.py backend/api/tests/rss/test_subscriptions.py backend/api/tests/rss/test_access_contract.py`：40 passed，7.50s。日志 `/tmp/newshub-rss-t21-tests.log`。0057 空库迁移/无遗漏DDL检查通过，复用 `/tmp/newshub-rss-t21-schema.log`。

此批同时接通旧频道取消订阅到共享引用协调，并给具备当前授权/模式/引擎关联的文章暴露显式RSS修复能力。未执行真实上传浏览器、T09队列推进、最终CI和生产数据。

后续 UI 已接入频道管理：multipart字节上传、选择有效项、显式现有/新建分组映射、确认、个人进度轮询、失败项重试、按记录编号恢复、下载本人OPML。账号切换取消/移除个人查询，并给写请求携带viewer fence。T20/T21相关前端36 passed（1.24s），typecheck/lint通过；日志 `/tmp/newshub-rss-t20-ui.log`、`/tmp/newshub-rss-t20-typecheck.log`、`/tmp/newshub-rss-t20-lint.log`。后端与目录/旧读取回归组合129 passed（19.35s），`/tmp/newshub-rss-t20-tests.log`。真实浏览器待T27，T09接线进行中。
