# T21 OPML 交付进度

状态：UI、T09 worker已集成，T27合成真实浏览器上传/选择/多组/进度/导出PASS；生产NOT_RUN。

领域 DDL 0057 独立保存用户预览、上传 hash、限时签名 token、确认 request hash 与逐项结果。上传最多1MiB/500 feeds，XML实体/DTD/外部引用禁用、深度16和节点10000上限；listparser 只接 bytes，预览不联网。规范化 URL 去重并合并多组，凭据 URL 不保存。

确认严格检查本人预览/选择/分组；新组为用户明确映射，重复确认同请求复用结果，改变选择409。逐项 durable intent 委托 T19；成功项目不重试，明确失败可选项重试，unknown/manual_blocked 不可绕过控制门禁。导出只含本人订阅及多组，序列化XML，不含引擎账号/secret。

实测：Python3.12.14 coordinator venv，独立临时SQLite。`RUN_MAIN=true DJANGO_DB_PATH=/tmp/newshub-rss-t21-tests.sqlite3 PYTHONPATH=backend:crawler /tmp/newshub-rss-coordinator-venv/bin/python -m pytest -q backend/api/tests/rss/test_opml_import.py backend/api/tests/rss/test_subscriptions.py backend/api/tests/rss/test_access_contract.py`：40 passed，7.50s。日志 `/tmp/newshub-rss-t21-tests.log`。0057 空库迁移/无遗漏DDL检查通过，复用 `/tmp/newshub-rss-t21-schema.log`。

此批同时接通旧频道取消订阅到共享引用协调，并给具备当前授权/模式/引擎关联的文章暴露显式RSS修复能力。该早期批次未执行真实上传浏览器；后续T27已验证实际上传及T09队列推进，生产数据仍未使用，CI以执行状态记录的精确head为准。

后续 UI 已接入频道管理：multipart字节上传、选择有效项、显式现有/新建分组映射、确认、个人进度轮询、失败项重试、按记录编号恢复、下载本人OPML。账号切换取消/移除个人查询，并给写请求携带viewer fence。T20/T21相关前端36 passed（1.24s），typecheck/lint通过；日志 `/tmp/newshub-rss-t20-ui.log`、`/tmp/newshub-rss-t20-typecheck.log`、`/tmp/newshub-rss-t20-lint.log`。后端与目录/旧读取回归组合129 passed（19.35s），`/tmp/newshub-rss-t20-tests.log`。真实浏览器结果见[T27](../T27/report.md)，T09每10秒按10项限额推进已接线。

## 2026-10-17：恢复与隔离差额

以上为历史证据。本轮重新核对 main `c841b07a410a475855029359370d18abe9a6c79c`，保留后端实现，只修 OpmlDialog 恢复路径；功能提交 `95479b7c286fa8dca675f73c0849e14d904c4b3c`，[PR #96](https://github.com/CoderLambert/news-aggregator/pull/96)。

新增 15 个组件回归。上传变化后旧预览立即失效；确认失败原样重放 token/选择/分组，不修改已确认意图；进度失败仍保留编号并只读恢复；失败项重试结果未知先读取对账，不盲重试 POST；终态/错误停止自动轮询，旧账号和旧记录响应不污染当前显示。

本地 Node 22.16.0 / TypeScript 5.8.3 仅作 transpileModule 语法检查，两个文件 0 诊断。由于当前容器无法联网安装依赖，项目 typecheck/lint/Vitest 与后端 pytest 本地 NOT_RUN。仓库实际 CI、最终 head 与合并证据统一记录在 #96，成功前不合并。没有新增依赖、后端/权限模型/DDL/公共接口变更，没有删除测试或修改旧断言/skip。

审核方式为主执行者自检，非独立 Agent。真实浏览器/移动端、真实 OPML 来源、生产数据及最终人工验收本轮 NOT_RUN，不能以历史 T27 结果或组件测试替代。
