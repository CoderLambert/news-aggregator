# T25：旧入口 fencing 与来源组切换

实现完成，等待主调度最终独立复核/集成；未执行生产切换。基线 `6601948`，任务分支 `task/rss-T25-owner-fencing`。本报告对应同提交产品与测试；最终 SHA 由交付消息和 Git 历史确定。

## 实现与接口

- `api.rss.legacy_fencing.capture_source_token(source_key)` 在旧 Spider 第一个 HTTP 请求之前捕获 source owner/epoch/policy、静态政策 hash、动态 config_version 和已知文章的 URL/revision/body-owner/version。每次真实下载前重验，同一任务不会在收到结果后补令牌。`ingest_item(..., legacy_token=token)` 的短事务复验全部归属，再提交元数据/正文。旧公开 SourcePublication 保持原访问范围；缺记录仅由显式旧入口初始化 personal/legacy，不默认公开。
- 合法 legacy 主来源、两主写均空的旧文章只能在显式获取/入队前原子认领。只读 eligibility 允许这种迁移过渡状态，提交没有 token 仍拒绝；其他来源可在兼容 publication/reading_policy 下增加 NewsSourceItem，不能通过 URL 自动抢占主写或标题。旧 HN→publisher 隐式 promotion 已移除，需明确主写移交。
- 同一运行中新创建的文章已明确归属 legacy，但不在初始快照中；该运行后续分页/detail 只能关联，不能补 token 写已有正文。Dev.to 已排队独立全文任务可在下一次获取前取得合法 token。这是刻意保守的过渡策略。
- 全文 claim 的 FetchLease 同时携带 T07 WriteToken 和来源政策快照；获取前、续租/完成、成功/失败提交检查 owner/epoch、主写/version、URL/revision、政策版本/当前批准。`commit_candidate` 和 `correct_article_identity` 无 token 拒绝；调用方必须在获取前捕获。抓取/引擎 I/O 不在 SQLite 写事务中，SQLite 首写取得 writer reservation，不依赖行锁。
- FeedState prepare/checkpoint/304/defer、分类修正与显式 source/identity repair 也检查来源及主写；维修 plan 保存 guard、apply 同事务复验，undo 是新的当前状态审核，不恢复旧 epoch/body-owner-version。
- 标题/摘要/正文变化前同事务归档旧兼容译文，再清相应当前字段；正文真实字节变化才增加 revision/更新精确 hash，同字节不会改旧状态/hash/译文。流水线译文晚到不能覆盖新源字符串；新结果以 `origin=legacy-bound` 保存精确 source_text/source_hash/translation_hash，旧兼容副本 `origin=legacy`，不伪造 provider。T14 可在当前 ACL 和源 hash 匹配下读取绑定记录。
- 按 T11 协调，在 `has_full_content` 仅对带 `_rss_access_user` 的 API 对象使用 `body_authorized_news`；无用户属性的内部 writer 判断维持服务语义。

## C11 命令

```sh
python backend/manage.py rss_migration plan --manifest /explicit/manifest.json --source-ids 1,2 --environment isolated
python backend/manage.py rss_migration apply --manifest /explicit/manifest.json --source-ids 1,2 --environment isolated
# 上一条仍是 dry-run；实际写入必须增加 --execute。
python backend/manage.py rss_migration verify --manifest /explicit/manifest.json --source-ids 1,2 --environment isolated
```

manifest 是 `schema_version=1, kind=rss_source_migration` 的明确操作映射，不是 T24 始终 `production_ready=false` 的静态 inventory。复用 T24 `canonical_feed` 识别共享物理 Feed；不按名称猜文章/引擎数字身份。

必要字段：

- `id` UUID、`environment`、`app_sha`；`target.database/device/inode/engine_instance_uuid/account_id/engine_base_url`；`allowlist.databases/engine_base_urls`。
- `sources[]` 含 `source_id/expected_owner/expected_epoch/expected_policy_version/target_owner/binding_id`（或 `binding_ids`）、V1 all `association_policy`。回 legacy 必须有可验证的旧 `legacy_source_keys`，新 RSS-only 来源不能回旧栈。
- `body_takeover[]` 明确 `news_id/expected_url/expected_body_owner_version`、唯一旧 `expected_owner_source_id` 或 `expected_owner_binding_id`、目标 `target_binding_id`（miniflux）。plan 只读验证，apply 不推断或批量抢占未列文章。
- `drain.fenced_version=app_sha` 与 `old_processes[{pid,start_ticks,role}]`。使用 `/proc/PID/stat` 的启动代数核验排空，不杀进程；旧无 fence 进程仍活着时保持 paused，不移交主写。生产必须包括 app/legacy 角色快照。操作者须在部署同机 PID 命名空间中提供完整旧进程清单；不能把自报清单当成部署编排证明。

执行过程：共享旧来源最小组检查 → Source paused/epoch+1 → 排空检查 → 显式主写 CAS/version+1 → 按有效引用计算物理 Feed 政策 → 事务外 EngineAdapter PUT+GET 确认 → 再验所有 source/政策/主写/operation/receipt → 激活目标 owner/epoch+1。引擎失败保持 paused，同 manifest 可恢复或只读 verify；往返 epoch 和主写版本单调增加。既有未完成 FeedOperation 阻止切换，控制期间新 operation/版本变化阻止激活。移除的旧链接也纳入物理 Binding 对账；其他已启用且有 ChannelSubscription 的 miniflux 来源或 miniflux editorial_pin 保持引擎采集，legacy/paused pin 不启用引擎。

生产 execute 还检查批准环境/来源范围/时间窗/change_reference、封存 SHA/digest/实际 schema exact-match、配对 SQLite/PG 备份身份与 allowlist 路径/hash；开发合成测试不要求生产封存。verify 是本地已确认结果与不变量的只读核查，不谎称每次 verify 都重新访问引擎。所有实际生产授权/部署排空/备份获取仍属于后续受批流程。

## 实测证据

环境：Python 3.12.14、Django 6.1.2、pytest 9.1.1；只读复用 `/tmp/newshub-rss-coordinator-venv/bin/python`。pytest 临时 SQLite、子进程独立文件库；没有读取用户/生产 DB，没有改模型/迁移。统一命令前缀：

```sh
RUN_MAIN=true DJANGO_DB_PATH=/tmp/rss-t25-test-base.sqlite3 PYTHONPATH=backend:crawler \
 /tmp/newshub-rss-coordinator-venv/bin/python -m pytest -q
```

该前缀加以下路径实测 **397 passed，43.15s，退出 0**（最终 pin/译文与旧 Binding 补丁另跑专项）：

```text
backend/api/tests/rss/test_owner_fencing.py
backend/api/tests/rss/test_body_commit.py
backend/api/tests/test_news_ingestion.py
backend/api/tests/test_full_content_status_service.py
backend/api/tests/test_full_content_worker.py
backend/api/tests/test_news_source_repair.py
backend/api/tests/test_category_corrections.py
backend/api/tests/test_budgeted_download_handler.py
backend/api/tests/test_feed_state.py
backend/api/tests/test_ingestion_content_consumers.py
tests/crawler/test_devto_hn_contracts.py
tests/crawler/test_source_matrix.py
tests/crawler/test_ingestion_identity.py
tests/crawler/test_crawl_only_mode.py
tests/crawler/test_source_retirement.py
tests/crawler/test_feed_receipts.py
tests/crawler/test_feed_lifecycle.py
```

**最终 T25 专项：33 passed，6.70s，退出 0**；命令为上述前缀加 `backend/api/tests/rss/test_owner_fencing.py`。最终状态服务相关追加验证 `test_owner_fencing.py test_full_content_status_service.py` 为 62 passed，7.09s，退出 0（随后新增 official_html 正例在 33 项专项内通过）。

T25 专项覆盖晚到 RSS/全文拒写、真实下载 handler 获取前捕获与后续请求拒绝、同 Feed 多 Source 最小组、主写移交/ABA、政策与配置变化、归档故障事务回滚、已运行旧 PID 拒绝、失败 paused/可重试、dry-run `connection.total_changes` 零变化、独立文件 SQLite 完整切换/重复执行/回 legacy、精确正文/译文/用户收藏和聊天关系保留、无引用旧 Binding 停采、非 miniflux pin 不激活、新译文精确 hash 绑定。FakeEngine 明确断言不在事务内，返回结构完整的确认 receipt；它不代替真实 Miniflux 验收。

旧测试仅将绕过 HTTP 的合成夹具改为显式获取前 token/legacy 所有权；相同正文不刷新 revision、HN 不自动抢主写、运行内新文章不追授 token 是 C02/C04 新合同的明确断言。无 token 拒写和 stale 全部保留专项验证。

## 未执行与覆盖边界

- 仅支持 `association_policy={version:1,mode:all}`。未知过滤和静态 keyword_filter 明确 blocked；不能清除旧过滤来扩大采集。T09 需按 T24 获批覆盖映射扩展共同 validator。
- 未连接真实 Miniflux、未操作生产、未执行旧生产服务排空/重启、未取得或恢复生产配对备份、未封存最终兼容镜像；T26/T29/T30 门禁仍待各自任务。
- 全仓 CI/构建未本地重复；提交后 CI 结果另由主调度记录。T11 读取 guard 在本分支缺其模块时不会被未标记的内部对象触发；完整 API 集成由主调度验证。
- 首个独立审查已由主调度完成 source_migration，按意见修复 pin；最终补丁和全任务仍需主调度独立复核。失败只暂停，不删正文/译文/关系，不反向迁移、不恢复整库，不自动回旧进程。

独立复核补丁：其它来源普通引用必须同时 `enabled=True + owner=miniflux + ChannelSubscription 存在`；有 miniflux editorial_pin 可无订阅保活，legacy/paused pin 仍不启用。当前 manifest 明确目标 miniflux 按批准映射启用。增加订阅/无订阅/有效 pin 三种返回 legacy 专项。

复核补丁验证：上述命令前缀加 `backend/api/tests/rss/test_owner_fencing.py`，35 passed，7.07s，退出 0；`git diff --check` 通过。
