# T17 网址发现进度

状态：接口与持久意图集成，实际引擎发现组合等待 T08 worker。所有请求仅排队/查询本地数据，无网站 HTTP、临时订阅或 XML 解析。

`normalize_input` 支持域名和 HTTPS Feed/网站网址；复用 T08 canonicalizer 保留业务 query/path，拒绝用户凭据、私网字面地址及凭据 query。resolve 按本人+URL 合并在途请求，复用15分钟成功结果（包括零候选），默认20次/小时持久配额。签名候选绑定本人/规范URL/成功发现操作/15分钟；订阅仍需再次准入。预览不返回未授权文章，本阶段 cached_articles 为空。

`POST /api/rss/discovery/resolve/` 返回缓存200或异步202，操作轮询后用 `discovery_operation_result` 生成本人候选token。`resolve_candidate_token` 给 T19/OPML 复用。既有session/CSRF、只读和v1错误协议保留。

Python3.12.14、独立合成SQLite：

`RUN_MAIN=true DJANGO_DB_PATH=/tmp/newshub-rss-discovery-tests.sqlite3 PYTHONPATH=backend:crawler /tmp/newshub-rss-coordinator-venv/bin/python -m pytest -q backend/api/tests/rss/test_discovery.py backend/api/tests/rss/test_operations.py`

23 passed/3.02s，日志 `/tmp/newshub-rss-t17-tests.log`。覆盖危险输入、0/1/多候选、user/token/expiry、成功状态绑定、在途合并、缓存过期、配额、无网络/无订阅。真实发现超时、最终worker与HTTP轮询组合未验证，不以fixtures声称通过。
