# T19 订阅与显式控制接口进度

状态：服务/API与T08/T09/T11已集成，T27真实浏览器订阅→后台采集→读取通过；上线采用gate0候选范围，无生产操作。

直接URL、活跃目录Feed ID、本人发现候选token统一进入subscriptions.subscribe；新来源personal，reading_policy由当前服务器来源政策决定；普通公开文章为standard，已观察原生Feed为public_feed，受限/非文章保留摘要政策。RSS_FULL_CONTENT_ENABLED默认0时为feed；显式开启且准入允许时普通新源默认full_content，原生与混合来源仍feed。已存在绑定沿用受当前政策约束的管理员模式。复用ChannelSubscription/Group/Member；规范URL及group set绑定Idempotency-Key，20并发同请求一条关系/本人操作视图。用户组跨账号404，批次全事务回滚。旧来源legacy绑定不被隐式新建并行采集，要求受控迁移。

物理binding复用，操作actor隔离。取消注册中的本人关系会取消本人视图并收敛物理引用；其他用户仍引用时保持，最后引用取消才关闭，文章/译文/已读历史保留。删组不退订，重复旧请求不会复活已退订关系。channel_catalog对Miniflux来源独立于旧Spider注册表。

提供本人订阅列表/POST/DELETE、本人操作GET（发现成功时返回本人签名候选）、显式Feed刷新/文章修复、管理员版本化模式变更。刷新/修复限频，文章/来源/策略与当前绑定在事务中校验，网络交T08。

Python3.12.14、独立合成SQLite实测：

- 订阅/发现/已读组合36 passed/4.57s，`/tmp/newshub-rss-t19-tests.log`。
- 控制API/只读策略矩阵28 passed/4.41s，`/tmp/newshub-rss-t19-controls.log`。
- 完整订阅专项（含20线程并发）9 passed/3.89s，`/tmp/newshub-rss-t19-concurrency.log`。

命令：`RUN_MAIN=true DJANGO_DB_PATH=/tmp/newshub-rss-subscription-concurrent.sqlite3 PYTHONPATH=backend:crawler /tmp/newshub-rss-coordinator-venv/bin/python -m pytest -q backend/api/tests/rss/test_subscriptions.py`。

真实注册→同步→阅读、最终ACL/worker组合与OPML调用已由T27验证。RSSHub受控别名仍受T18公网/凭据门禁限制（带额外参数/能力的目录模板明确拒绝直接订阅）。订阅来源数量与发现频率上限可配置；不把HTTP202当引擎已连接。

最终准入补充：首次create原子附加服务器EntryURL过滤、raw GET确认字段、主线程发送前复核当前政策；gate关闭阻止管理员full/显式refetch，保留禁用/降级路径。T04独立审查与真实正反例见[政策报告](../../../../../ops/rss/feed-policy/report.md)，redirect绕过仍为全文上线阻塞。全量业务23de733回归2397 passed/16 live skipped。
