# T05：核心 schema 交付报告

实现状态：IMPLEMENTED，待主调度最终独立复核/集成。仅合成 SQLite 验证通过，不表示生产放行。

## 提交与范围

分支 `task/rss-T05-core-schema`，基线 `5ae2c44`。核心接口首提交 `35a7d29` 已推送；后续提交补系统 actor、专项测试与本报告。主调度已初审首提交的身份约束、互斥主写 FK、精确 hash 和冻结静态政策；最终独立复核尚待执行。任务分支 CI/开发 PR 由主调度统一跟进，本报告不声称远端 CI 已通过。

- `backend/api/rss/models.py`：C02 绑定、来源发布、来源关联、条目映射、正文候选、同步进度、固定操作、拒收/冲突和旧兼容译文快照。
- `backend/api/models.py`：注册上述模型；News 新增主写 FK/版本、精确正文 hash、完整性，并允许 `available` 状态。
- `0053_rss_core_schema`：仅核心 DDL，依赖已存在的目录 `0052`，未修改目录模型/迁移。
- `0054_rss_legacy_compatibility`：既有来源 `public/legacy`，保留静态/动态阅读政策；文章主写归原 source。分批事务，正文每批 20 条；只新增精确 UTF-8 SHA256 和主写归属，不修复/规范化正文，也不改任何旧列、PK/FK、revision/provenance 或译文。
- `0055_rss_system_operation_actor`：允许内部系统意图 actor=null，并以 SQLite 部分唯一索引保证系统 dedupe_key 唯一。
- `backend/api/tests/rss/test_schema_compatibility.py`：11 个参数化后专项案例。

## 下游字段与安全约定

`FeedBinding.engine_instance_uuid` 为 UUID，`account_id/engine_feed_id/engine_entry_id` 为正整数；feed 注册前可为空。实例/账号内 canonical URL 和非空 feed ID 各唯一；`EngineEntryMap(binding,engine_entry_id)` 唯一。绑定是持久身份锚，不得将既有 binding 重分配给重建实例；实例恢复核对属于 T03/T25。Feed URL 必须由准入服务先按 C02 规范化；schema 不执行 URL/DNS/网络准入。`desired_mode` 为 `feed/full_content`，`desired_enabled` 默认 false。

`News.body_owner_source` 与 `body_owner_binding` 最多一个非空，数据库禁止双主写；`body_owner_version` 从 1 开始。旧兼容创建路径暂可留下两个 FK 都空，含义是**未认领，没有获准写入者**；T07 必须拒绝无 claim 的正文提交。T25 为合法 legacy 写前在短事务内显式认领、捕获令牌，提交时检查 source owner/epoch、文章主写/版本及政策，不能把空 FK 当作任意来源可写。接管不得自动改 provenance/hash。

`SourcePublication` 默认 `personal/paused/summary_only`，epoch 和 policy_version 独立且从 1 开始。只对 0054 前既有来源回填 `public/legacy`。迁移后新建 Source 不会隐式建立 publication：T19 必须在创建事务中显式建立个人来源；兼容 legacy 入口由 T25 显式初始化；T11 对缺记录 fail closed，禁止以“缺 publication”推断公开。公开/个人范围独立于暂停，`history_only` 不是落库枚举。

`BodyCandidate` 持有 `entry/news/source` FK、`source_epoch/body_owner_version/source_policy_version/binding_policy_version/expected_revision`、URL、Markdown、raw/canonical hash、conversion_version、完整性与处置状态。重放唯一键包括完整候选内容/版本令牌。`full_content_hash` 是实际接受原文字节的 SHA256；历史 CRLF、空格等保持不动；`full_content_completeness` 初始 unknown，不将旧 complete 强行宣称 verified。旧兼容译文仍留原列，T07 真正替换对应原文前原子归档到 `LegacyTranslationSnapshot`，并按 news/field/source_hash/translation_hash 幂等；T05 不提前清空任何译文。

`FeedSyncState` 的增量 `new_cursor/run_id/upper_id/page_cursor/last_complete_at` 与 `reconciliation_run_id/reconciliation_upper_id/reconciliation_page_cursor/reconciliation_last_complete_at` 分开。同步和操作均使用 `lease_token/lease_epoch/lease_until`，不能将 lease epoch 当作 source epoch。

`FeedOperation` 用户意图的 `(actor,dedupe_key)` 唯一，内部系统意图 `actor=null` 时 `dedupe_key` 独立唯一。T08/T25 系统收敛无需伪造用户；公开 API 必须强制当前用户 actor，查询排除 null，不得接受客户端自选 actor；后台重试保留原授权 actor。`safe_input/safe_result` 仅存固定动作白名单数据，服务必须拒绝任意 HTTP/代码/HTML/secret，schema 不承担服务级校验。`request_hash` 用于同键不同请求冲突判断。

## 实测结果

环境：隔离 worktree `/tmp/newshub-rss-T05`；只读复用解释器 `/tmp/newshub-rss-coordinator-venv/bin/python`。Python 3.12.14、Django 6.1.2、SQLite 3.53.1。所有数据库为 pytest 临时库或 T05 专属 `/tmp/rss-t05-*.sqlite3`，未访问用户业务库。

以下命令统一前缀：

```bash
RUN_MAIN=true DJANGO_DB_PATH=/tmp/rss-t05-test-base.sqlite3 PYTHONPATH=backend:crawler \
  /tmp/newshub-rss-coordinator-venv/bin/python
```

| 实测命令（上述前缀后参数） | 结果 |
| --- | --- |
| `-m pytest -q backend/api/tests/rss/test_schema_compatibility.py backend/api/tests/rss/test_content_conversion.py backend/api/tests/rss/test_migration_inventory.py` | 46 passed，7.88s，退出 0（schema 11） |
| `-m pytest -q backend/api/tests/test_news_ingestion.py backend/api/tests/test_channels.py backend/api/tests/test_shared_translations.py backend/api/tests/test_ingestion_migration.py backend/api/tests/test_channel_migration.py backend/api/tests/test_body_access.py` | 96 passed，12.25s，退出 0 |
| `backend/manage.py migrate --noinput --skip-checks`，DB 改为全新 `/tmp/rss-t05-empty-schema-final.sqlite3` | 从空库至 0055 全部迁移成功，退出 0 |
| `backend/manage.py makemigrations --check --dry-run --skip-checks`，同隔离库 | No changes detected，退出 0 |

T05-A1：分别从 0051 和已有 0052 目录快照升级，逐表比较全部旧列/行，验证原 PK/FK、正文 CRLF/代码空格、hash/provenance/revision、标题/摘要/全文兼容译文、私人/共享译文及任务、订阅/分组、收藏/屏蔽、ReadingDay、Chat/Research 保持；`PRAGMA foreign_key_check` 为空。包含只存在 `full_content_zh` 的文章，以及 missing/legacy/complete 历史状态。目录快照/条目保持。重放兼容回填不覆盖后来明确切换的归属和 publication。

T05-A2：同实例/账号 URL 与 feed ID 冲突、entry 重放、跨实例/账号/Feed 数字碰撞、尚未分配 feed ID 的并发注册；独立文件数据库上的两条真实 SQLite 连接分别竞争 binding、entry、旧译文快照，均恰好一条创建、一条唯一约束拒绝，无行锁假设。

T05-A3：默认 personal、public/personal 各自暂停不改变范围；非法 history_only 拒绝；Source.name/News.url 原唯一约束保留；静态 rss_summary_only 和 SourceConfig summary_only/public_feed 政策不变。

T05-A4：双主写/零主写版本拒绝；候选按政策/归属令牌去重；正文 revision 独立；快照按字段/源 hash/译文 hash 去重；两个同步游标独立；用户/系统操作幂等各自收敛，非法操作类别拒绝。

## 未验证与恢复边界

未运行生产库、真实 Miniflux、全仓 CI、端到端 ACL/正文 CAS、远端操作 worker、真实两库恢复与兼容镜像演练；这些分别由后续任务/集成门禁完成。当前模型提供持久状态及 DB 约束，不能独立证明服务层授权或 fencing 已上线。正文候选接收/覆盖、译文归档原子操作、来源切换、用户 API 均不在 T05 中实现。

schema 升级和 0054 回填必须按部署流程停业务写入；分批回填可重试，不支持与旧二进制同时写入后的在线无损认领。恢复采用保留新增数据的兼容应用回滚，不默认 reverse migration；未触碰生产环境、main 或其他任务文件。
