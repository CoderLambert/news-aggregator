# T07：正文 CAS 与旧译文保护交付报告

实现状态：IMPLEMENTED，待独立复核/集成。未发布、未连接真实引擎或生产数据库。

## 提交与范围

基线 `05ff8e3`，隔离 worktree `/tmp/newshub-rss-T07`，分支 `task/rss-T07-content-store`。接口首提交 `3f9e20e` 已非强推；后续提交补边界案例、provenance 字段统一和本报告。未修改模型、迁移、settings、路由或其他任务文件。PR/远端 CI 与最终独立复核由主调度统一跟进；本报告不将本地测试等同远端 CI。

- `backend/api/rss/content_store.py`：来源/正文主写/政策/条目身份/URL/revision fence，正文提交、候选隔离与受控处置。
- `backend/api/rss/legacy_translation.py`：精确原文/译文 hash 和幂等旧兼容字段归档辅助。
- `backend/api/management/commands/rss_body_candidate.py`：单候选 accept/reject，默认 dry-run，`--execute` 才执行。
- `backend/api/tests/rss/test_body_commit.py`：46 个参数化后专项案例。

## 下游接口

```python
capture_write_token(*, news_id, source_id, entry_id=None) -> WriteToken
fenced_article(token)  # contextmanager，yield 新鲜 News
archive_changed_translations(news, replacements) -> dict  # 需要一并写入的译文清空字段
commit_body(token, converted, *, content_kind='article', completeness='unknown', evidence=None) -> CommitResult
resolve_candidate(candidate_id, *, decision='accept' | 'reject') -> CommitResult
```

`WriteToken` 冻结 `news_id/news_url/expected_revision`、来源 owner/epoch/policy_version、正文两个主写 FK/version，以及引擎 entry UUID、实例/账号/feed/entry 数字身份和 binding_policy_version。`CommitResult` 包含 status/reason/candidate_id/revision；不会操作 FeedSyncState/cursor。

T09 首先以已审关联规则建立 `EngineEntryMap.news/source_url/disposition='linked'` 和已启用的 `SourceFeedLink`，然后捕获 token。元数据可使用 `fenced_article`，在相同事务先归档将变更字段的旧兼容译文，再显式字段 `QuerySet.update`；标题 hash/摘要索引规则由 T09 实现。不要在嵌套正文提交之后用旧 News 对象全字段 save 覆盖刚提交的正文。

T25 的 legacy 入口捕获 token 时不传 entry；当前来源必须 owner=legacy 且文章正文主写恰为该 source。两个主写 FK 都空不授权写入，不在本服务自动认领。具体 legacy 路径的调用改造、认领与获取前捕获令牌归 T25；此 helper 不代替各路径的采集/元数据规则。

## 原子性与拒收规则

短事务中的第一条语句是对目标 News revision 的无值变化 UPDATE，取得 SQLite 写保留后再重读相关表。这样来源政策、binding 和条目身份的并发写入也不能穿过正文事务；未使用无效的 SQLite `select_for_update` 行锁。整个服务无网络 I/O。当前明确只支持业务库 SQLite。

提交时核对来源 owner/epoch/政策版本、文章主写及版本、entry 映射/URL/数字身份、绑定实例/账号/feed、binding policy/applied policy、绑定 ready/enabled 与来源关联启用状态，随后检查当前阅读政策。未知政策 fail closed；summary_only/rss_summary_only 只接受明确 summary，其他既有已知政策词汇按正文规则处理。政策变更入口必须递增版本；既有 binding/entry 不得被重绑定到重建实例。链接的本地过滤准入属于 T09，不能通过直接构造 token 跳过成员关联规则。

Standalone 正文/处置调用只对 SQLite BUSY/LOCKED 做最多 3 次完整事务重试；如果调用者已经开启外层事务，则直接抛数据库错误，T09 必须重放整个外层事务，不能仅重试已建立旧读快照的内层。stale/DB/API 临时错误不得由调用者推进 cursor。

内容必须来自 T06 `ConvertedContent`，验证精确 canonical hash、原始 hash、转换版本、字节上限和完整性；服务不再访问发布者或重复提取。空、显式错误、明确摘要替换旧 complete/verified 均不覆盖。显式错误包括 evidence.error_code 和严格整段错误标记。summary-only 政策在同 hash 前仍检查，raw hash 不绕过政策。

正文精确相同则不改 News revision/hash/provenance/state，也不清译文；仅可更新已核实 entry 的转换观察信息。正文变更时原子归档 full_content_zh，再清当前显示，revision+1，state=available，使用候选实际完整性。verified 必须绑定当前 canonical hash；新内容不会继承旧 verified。正文 provenance 保存 binding_id、engine_instance_uuid/account_id/engine_feed_id/engine_entry_id、转换/hash 和来源/主写/政策版本。

旧正文长度≥1000 字符且新正文<50% 默认隔离，使用 `getattr(settings, 'RSS_BODY_SHRINK_MIN_CHARS', 1000)` 和 `RSS_BODY_SHRINK_RATIO=0.5` 调整，不推断完整性。候选复用 T05 唯一键，保留转换结果与版本令牌，并在 evidence 的服务端 `_write_identity` 中冻结复合身份。隔离/明确拒绝的同候选重放不自动放行。受控接受只绕过缩短阈值；accept/reject 都重验全部 fence，不能接受已过时候选、改变正文主写或跳过摘要/政策拒绝。

## 译文与故障恢复

`archive_changed_translations` 只处理 title/content/full_content 的实际字符串变化，保存旧原文、唯一旧译文、精确 UTF-8 SHA256 和 origin=legacy，不伪造 provider。它要求活动事务，返回清空对应兼容译文列的更新值；调用者必须与原文更新一起提交。全文译文时间戳一并清空。未改变的字段、私人/共享译文及任务均不修改。新 body 写入和标题/摘要元数据写入共用该辅助。

实测在归档后、正文写入后、以及外层页事务末尾注入中断，News、entry hash、候选、快照和调用者 cursor 一起回滚；随后重放仅归档一个旧副本。归档来源不明的兼容译文只标 legacy 历史，不声称当前译文匹配已被验证。

## 实测命令与结果

环境：Python 3.12.14、Django 6.1.2、SQLite 3.53.1；只读复用 `/tmp/newshub-rss-coordinator-venv/bin/python`，数据库为 pytest 临时 SQLite，环境路径 `/tmp/rss-t07-test-base.sqlite3`。没有用户业务库操作。

```bash
RUN_MAIN=true DJANGO_DB_PATH=/tmp/rss-t07-test-base.sqlite3 PYTHONPATH=backend:crawler \
  /tmp/newshub-rss-coordinator-venv/bin/python -m pytest -q \
  backend/api/tests/rss/test_body_commit.py \
  backend/api/tests/rss/test_schema_compatibility.py \
  backend/api/tests/rss/test_content_conversion.py
# 87 passed，8.00s，退出 0
```

最终统一 provenance 键为 schema 一致的 engine_* 命名后，仅重跑受影响专项：同前缀 `-m pytest -q backend/api/tests/rss/test_body_commit.py`，46 passed，2.97s，退出 0。`git diff --check` 通过。

- T07-A1：20 种 stale 变更（source暂停/epoch/policy、body owner/version、URL/revision、binding政策未应用/停用、entry与复合身份等），均无正文、快照或 cursor 写入。真实第二条 SQLite 连接尝试在归档中修改来源政策被写锁拒绝，事务后可提交；旧 token 随后失效。legacy token 无法越过另一主写者；epoch ABA 失败。
- T07-A2：同精确字节不改旧 hash/provenance/revision/state/译文；政策已变仍拒绝。候选明确拒绝后相同重放保持拒绝。
- T07-A3：空/错误/摘要/不匹配 hash/超字节上限保持旧正文；缩短候选去重、配置阈值、受控接受/拒绝、dry-run、处置时身份/epoch 变化、verified 不继承均通过。
- T07-A4：仅旧兼容全文译文保存其原文/译文精确 hash；标题和摘要共同归档、同值不归档；不同故障点和外层事务回滚后重放不丢唯一副本。

## 未验证与后续门禁

待最终独立复核、远端/全仓 CI、T09 元数据与游标组合、T11 读取授权、T25 全链旧 worker fencing。未执行真实 Miniflux、生产数据迁移、两库恢复或兼容镜像演练；这些不由本服务的合成测试替代。没有 schema 变更，不占用后续迁移编号。

本服务不会增加正文读取权限，也不授权生产切源/接受候选；本次仅在隔离测试执行受控命令。部署恢复仍沿用兼容版本和保留数据库原则，不反向迁移或删除快照。
