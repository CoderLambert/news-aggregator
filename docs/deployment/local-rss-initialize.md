# 本地 RSS 默认来源初始化与配套恢复

本流程对应 RSS T16/T19/T20/T31 的频道与本地清理差额。Miniflux 是唯一常规采集及正文提取引擎；不执行生产部署或模型调用。

## 行为

- `GET /api/sources/?purpose=history` 保持历史查询用途，也是省略参数时的默认值。`purpose=subscribe` 只返回已接入 RSS 的公开来源及当前用户有权查看的个人来源。`can_subscribe` 只有在真实 Feed ID、当前已应用策略和来源授权均有效时才为真；`rss_status` 区分 ready、pending、unknown、error、paused、retired 和 unconfigured。
- 频道页将待验证候选单列。Feed 连接请求在引擎确认前不建立用户订阅或文章访问权。单个和批量频道 API 使用同一资格判断。来源缓存同时绑定用户及用途。
- 相同引擎实例、采集账号和规范化公开 Feed 复用物理绑定及原文。订阅、分组、已读、收藏、私人译文和问答仍分别授权。个人来源不会因为其他人订阅而公开；凭据或已识别私人令牌地址不能进入共享链路。
- 十个默认来源通过编辑固定引用采集，不给任何账号自动订阅。普通来源没有订阅或固定引用时停止采集；历史内容保留。
- 应用及同步服务默认允许公开来源提取正文，仍尊重显式关闭和来源限制。已采样的原生全文 Feed 保持直读；抓取成功不赋予“已确认全文”标记。阅读和问答只读同一版本的已存正文。

## UTC 日期下界

Miniflux 2.3.3 的原生 `EntryDate=before:YYYY-MM-DD` 在提取前过滤，时间精度为 UTC 日期。初始化将“当前 UTC 时间减七天”向上取整到下一个 UTC 零点，避免收录超过七天的文章。例如 2026-10-20 12:00 UTC 初始化，下界固定为 2026-10-14 00:00 UTC；恰好 UTC 零点初始化则不额外进一日。

这意味着首次窗口可能比精确七天短不足一天。该下界永久保存在绑定中，创建、策略更新和后续轮询均保留；应用同步另有防御检查。不得用每天移动的 `max-age` 规则替代固定下界，也不得在同步之后才丢弃已经触发正文请求的旧文章。

依据：[Miniflux 规则文档](https://miniflux.app/docs/rules.html)、[2.3.3 日期匹配实现](https://github.com/miniflux/v2/blob/2.3.3/internal/reader/filter/filter.go)。隔离真实引擎回归位于 `tests/rss_engine_contract/live_date_boundary.py` 的 `test_frozen_seven_day_rule_filters_before_extraction_and_survives_poll`。

## 预览与执行

首先在本地栈的完整 Compose 文件列表中选择已经包含本次代码的应用和 RSS 镜像。保留现有环境文件和密钥挂载，不把真实凭据复制到测试工作区。

```bash
python3 scripts/rss/initialize.py \
  --project newshub-local-uat \
  --compose-file /absolute/local-stack/compose.yaml \
  --compose-file /absolute/local-stack/unified-rss.override.yaml \
  --backup-dir /absolute/private-backups/first-rss-initialization
```

默认只预览。核对项目、实例 UUID、采集账号、内容数量、日期下界和固定来源后，在同一命令中显式添加 `--apply --reset-content`。

包装器只接受本机 Unix Docker、指定 local/rss 项目、同项目专用数据库卷、相同实例/账号及回环发布端口，并拒绝其他项目共享写卷。它按顺序执行：

1. 验证镜像中的预览命令及实际 Compose/卷身份。
2. 停止应用、RSS 同步、相关 Worker 和 Miniflux，确认容器退出。
3. 使用 SQLite backup API 生成一致快照；备份专用 PostgreSQL、配置及密钥引用到权限 700 的目录，记录校验和。
4. 保留引擎用户、令牌、schema 和序列，仅清除专用账号 Feed/文章。其他账号持有 Feed 时拒绝继续。
5. 应用前向迁移，在同一应用事务中清理内容并写入初始化审计，注册版本化默认来源；账号、通用模型/API 配置、安全策略及审计保留。不会删除 SQLite 文件。
6. 归档并清除 Chroma/TTS 派生内容，先恢复 Miniflux 和同步服务。等待连接请求有界结束，且增量同步在其后完成，再恢复应用。默认等待上限为 1200 秒，可用 `--settle-timeout` 设置 30–1800 秒。

此无模型调用的维护流程保留频道 Worker 与索引 Worker 的配置，但让它们保持停止；旧采集角色也不恢复。后续恢复这些 Worker 应单独核对其授权、队列和模型配置。

底层管理命令 `rss_initialize --local-instance UUID` 也默认预览；变更需要显式 `--apply`、匹配的本地实例标记和本地引擎地址。首次清理还必须提供 `--reset-content --backup-dir DIRECTORY`，其配套备份必须通过实例/账号及完整性校验。正常安装可仅 `--apply` 添加默认来源；若已有历史绑定或内容需要接管，应使用显式清理或既有迁移流程。

## 失败、重复执行与恢复

默认来源清单位于 `backend/api/rss/directory_data/defaults-v1.json`。初始化审计按实例、账号及版本唯一；同版本重跑或重启不会再次清理、新增重复 Feed 或恢复旧静态频道。清单内容变化而版本未变时拒绝执行。

远端结果不明时保留 unknown/manual_blocked 并查询核对，不盲目重发创建或正文请求。失败来源留在候选目录，不能订阅。重试遵守既有次数、租约及 Retry-After。

失败后查看备份目录的 `maintenance.json`。若停在 `collecting_defaults`，保持应用停止，读取预览的 `runtime`，确认操作均结束且 `last_sync_at >= last_operation_at` 后才恢复应用；不要重复内容清理。若已完成初始化，重复 `--apply --reset-content` 只返回现状，不停止服务或修改新数据。

备份目录包含 `application.sqlite3`、`miniflux.dump`、`configuration.tar`、`backup.json` 和派生内容归档。恢复必须暂停同一实例全部写入，配对恢复 SQLite 与 PostgreSQL，并使用备份对应的配置、引擎身份、密钥和应用镜像。仅回退代码不能恢复已清理内容。先在没有真实凭据的独立实例验证恢复流程；不要把真实业务数据库和密钥复制进回归测试。
