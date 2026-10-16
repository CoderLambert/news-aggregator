# T09：增量同步与全保留期对账

实现完成，等待主调度最终复核/集成。基线 `efe5f09`，分支 `task/rss-T09-sync`。未操作生产、用户数据库或 main；最终 SHA 由交付消息及 Git 历史确定。

## 实现与接口

- `api.rss.sync.prepare_page()` 在第一次有界 GET 后只捕获身份/URL、本地 News 主写/version/revision、完整 instance/account/feed 身份、SourcePublication owner/epoch/policy、绑定政策及动态批准状态。第二次同范围 GET 才产生正文候选。相同 ID 的 URL、所属 Feed、owner 或政策变化均 stale；新增未捕获的本地 URL 也不能事后授权。这需要每页两次 API GET，不做全库快照、不做来源网络请求。
- `commit_entry(..., reserve=...)` 第一条事务语句取得 SQLite 写保留并复验同步 lease；同短事务处理身份映射、主写归属、元数据、译文归档及 T07 `commit_body`。任何 stale 或 DB 错误回滚该条。已有 News 的 PK、主来源、分类、URL 和用户关系保持；另一个 Feed 仅能在 publication/reading policy 和 personal audience 兼容时关联，不能覆盖正文/标题/摘要。新文章显式认领 body_owner_binding。
- 标题/作者按模型上限明确拒收；HTML 本地安全清理后派生最多 500 字纯文本摘要，空摘要不清旧值；安全 HTTPS 封面不下载。发布时间优先 published_at，否则 created_at，不用抓取 now。来源内容类型使用已批准动态配置或原静态政策，HN/arXiv 等不默认冒充 article。主写覆盖标题/摘要前归档唯一旧译文；正文走 T07 的精确 hash/no-op/摘要保护/缩短隔离。
- `News.full_content_provenance['_sync_metadata']` 独立保存 `publish_time_inferred` 与 `summary_version=rss-summary-v1:500`。body commit 后同事务合并，保留正文 provenance 的其他字段。历史缺标记时间按可信处理，推断日期不覆盖。`api.rss.sync.sync_metadata(news)` 是给 serializer 的只读 helper。标题 hash 沿用原算法；现有搜索索引依 title/content source hash 审计失效，worker 不导入 embedding 或 crawler。
- `api.rss.reconciliation` 持久保存增量固定 H、page_cursor 和独立 retained run/H/cursor。每条事务完成后才提交页游标，崩溃可重复处理。新增游标单调；每 30 秒增量带默认 1000 ID 重叠窗口，首次增量完成后每日全保留期 keyset 对账。大型 sweep 与增量按页交替，各自固定 H，不查询 read/star 或发布时间。清理远端条目不删除本地 News/关系。确定性坏数据落 FeedRejection/IdentityConflict 后推进；暂态网络、SQLite busy、身份/授权竞争不推进。
- 一页重复 URL 保留第一条主写并为后续重复身份记安全 issue，避免预捕获快照反复相互失效。V1 只执行 `{'version':1,'mode':'all'}`；未知关联 filter 使共享 Feed 本轮 fail closed 并记录 issue，需批准后的显式规则支持，不能扩大采集范围。
- `SyncWorker` 通过 T08 `submit_short_read()` 共享唯一 read 槽，ORM 只在主线程。每次最多一个 future，不排 backlog；首次只读 probe 完成才声明 engine_ready。请求期间 lease 过期时排空并丢弃旧响应，不借新 lease epoch 接受旧 GET。refetch 使用原 `safe_input.fence`、intent version、operation request hash/lease epoch；正文结果 accepted/unchanged/quarantined/stale/rejected/conflict 与 pending_sync ack 原子提交。确认 404 终结为 rejected；网络失败保留 handoff。scope 在 SQL 过滤后取第一条，其他实例的旧 handoff 不堵塞当前实例。
- `rss_sync_worker` 集成控制、同步、每 10 秒 `opml.process_imports(limit=10)` 及每日 pinned seed 检查。默认 `rss_runtime` ORM shell 保持兼容。进程持有 SQLite 目录单例锁；超时未归还的 read/control 槽使 supervisor 重启，不能谎称取消远端请求。`--once` 从未完成状态等待首次增量真实完成，最多 120 秒；已有完成记录执行有限 tick 后返回。
- `channel_articles` 分类/地区过滤补充 EngineEntryMap→SourceFeedLink 的 SQL membership，同时保留主来源和旧 NewsSourceItem 语义。

## 健康接口

`api.rss.reconciliation.health_snapshot(instance_uuid, account_id, runtime_status=None)` 返回：

- `engine_ready`、`initial_sync`、`incremental_running`、`full_reconcile_running`：bool。
- `last_successful_incremental`、`last_successful_full_reconcile`：真正完成后的 ISO timestamp 或 null。
- `new_cursor`、`observed_upper_id`：十进制字符串（后者可 null），`lag` 为已观测 ID 上界差或 null，并非条目精确数量。
- `error_class`：安全错误代码或 null；没有 runtime_status 时不默认 engine_ready。

heartbeat 包含 `engine_instance_uuid` 字符串、`account_id` 整数及 timestamp。Web/API 应先核对身份且文件年龄不超过 60 秒，再传 runtime_status；没有秘密配置或 API token。最终 HTTP/页面由 root/T20 接入。

## 实测

环境：主机专项 Python 3.12.14 / Django 6.1.2；只读 `/tmp/newshub-rss-coordinator-venv`，pytest 合成临时数据库。实际容器使用独立 rss-sync 镜像及 T00 pinned Miniflux 2.3.3/PostgreSQL 17.6；镜像 digest、随机 project 和清理结果见 `ops/rss/T09/evidence.json`。

```sh
RUN_MAIN=true PYTHONPATH=backend:crawler /tmp/newshub-rss-coordinator-venv/bin/python -m pytest -q \
  backend/api/tests/rss/test_sync_reconciliation.py \
  backend/api/tests/rss/test_body_commit.py backend/api/tests/rss/test_operations.py \
  backend/api/tests/rss/test_control_worker.py backend/api/tests/rss/test_access_contract.py \
  scripts/deploy/tests/test_rss_runtime.py --disable-warnings
```

关联回归曾实际 **150 passed / 18.24s**。之后增加静态 content_kind 测试时遇到合成迁移已存在同名 HN seed 的 fixture 冲突，已在独立测试中改名该 seed 解决；最后单独运行同命令中的 `test_sync_reconciliation.py`，**42 passed / 3.66s**，覆盖新增完整引擎身份重绑定、startup probe 与 lease 过期后重获拒绝旧响应；未重复全仓。

```sh
docker build --target rss-sync -t newshub-rss-t09:isolated-check .
/tmp/newshub-rss-coordinator-venv/bin/python ops/rss/T09/verify_live.py \
  --image newshub-rss-t09:isolated-check --output ops/rss/T09/evidence.json
```

真实引擎 **PASS**：实际条目写入后子进程 `os._exit(73)`、独立 SQLite writer busy、真实 GET 结果丢弃后重放、仅停止隔离 engine 的网络失败、低 ID 2 晚恢复、旧正文修改、高 ID 5 + 1990 日期、远端全清理而本地保留 5 篇、daemon health `sync_ready=true`。恢复仅把合成 lease 时钟到期提前，未声称测量生产 TTL。publisher 为合成 HTTPS；所有本轮随机项目已销毁。具体边界见 `ops/rss/T09/README.md`。该镜像故障证据随后复用；最后增加的完整 binding identity 快照、跨实例 handoff SQL scope 和 lease 重获防晚写由上述最终 42 项 SQLite 专项验证，未把这些追加检查声称为该镜像中的 live 注入。

最终分类 SQL membership 调整后，T09 + `test_access_contract.py` 联跑 **62 passed / 6.79s**。`git diff --check` 通过。没有运行全仓、真实生产副本恢复或最终 T26/schema 0058 演练。新迁移由 root 串行集成，本任务没有修改任何 models/migration/URL/settings/依赖/Compose。

## 限制与下游

- 未知 filter 保守阻断共享 Feed；仅已批准 all 策略可执行。Source/category 缺失、未知政策及未批准动态配置会保留拒收记录，后续 retained sweep 可在配置修正后收敛。
- 每页两次有界读取，加上转换；当前不以 raw_hash 跳过元数据、政策或身份处理，也不依靠 raw_hash 省略转换。超限响应缩小分页重试；若单条连 adapter 响应上限也超过，则保留游标和错误，不能凭未读身份跳过。
- retained sweep 只覆盖引擎仍保留的条目；引擎已 cleanup 且此前从未读取的条目无法恢复。任务没有伪造完整性 verified。
- 真实故障证据是合成开发证明，不能替代生产备份、批准 manifest、资源预算或来源质量验收。root 负责非作者复核、集成新 schema、HTTP/UI 健康与 inferred 日期接线。
