# RSS 正文修复工具与本地受限来源验证

后续用户要求已将全局全文能力默认开启，当前运行状态见 [公开来源默认开启记录](RSS-PUBLIC-DEFAULT-ON-2026-10-20.md)。下文保留首轮修复与回退的历史证据。

本次实现已完成工具和界面更新，**持续开启全文采集及最近 7 天全部成功修复未达成**。The Verge 原文页面在加载后显示 “Subscribe to The Verge to continue reading.”；用户仅授权公开文章并明确排除付费/登录受限内容，因此停止剩余补抓，恢复原采集配置，保留已经取得的正文。没有绕过登录、订阅或验证码，没有使用模型或搜索服务。

独立工作区：`/tmp/newshub-rss-body-recovery-20261020`，分支 `task/rss-body-recovery-20261020`。HEAD/base 均为 `8f7fed66cb66bdccc88bd2dd95f8f96e4a3288c2`，本次修改尚未提交。原工作区 `d8afd8588f86066b98ddfff2de967d92ecacaf7c` 的数据库和无关文档未动。未提交、推送、创建 PR 或运行远端 CI（NOT_RUN）。

## 实现与约束

- `backend/api/rss/body_repair.py`：冻结候选/正文版本/订阅策略版本，使用现有 `refetch_fence` 和 `enqueue_operation`；按物理订阅顺序、单篇等待同步确认，25 篇报告一批，持续到候选结束。没有新表、网络客户端或抓取器。
- `rss_repair_bodies`：preview / execute / resume；持久清单、原子写盘、同一数据库的修复进程互斥。稳定任务键使进程中断或清单写入失败后不重复发送；未知结果阻塞该订阅后续任务，恢复时先核对既有任务。限流/过期任务/回写继续由原 worker 负责。
- `rss_repair_policy`：预览、显式目标订阅的版本化启用、CAS 恢复；未授权目标、手工偏好和来源不明的直读订阅保留，并记录原因。原生全文和受限来源继续使用原策略。
- 阅读页、小闻共用完整性文案；可读内容不会自动显示已确认全文。没有新增打开文章或聊天时的补抓。
- 试验期间曾按用户明确授权允许 The Verge 提取；发现动态付费墙后，来源合同代码、运行镜像和采集设置均回退。最终代码差异没有放宽 The Verge 来源合同。

## 本地实际结果

目标：[CoreWeave 文章](https://www.theverge.com/ai-artificial-intelligence/1014045/coreweave-stock-debt-sector-ai)，新闻 19，1161 → 5899 字节，revision 1 → 2，单次 refetch。初始页面快照显示后续正文和结尾，随后动态付费墙出现，无法完成受限条件下的全文确认；仍为 unknown，不宣布已取得完整原文。提取结果也带有空的导航标题，没有把这种附加内容当作完整性证明。

7 天清单共 11 篇：8 个 refetch 回写确认成功、1 个回写因 fence 变化变为 stale、1 个任务回退时 cancelled、1 篇未发出请求。unknown 结果 0。8 个成功包含目标文章既有任务，未重发。共 10 个 refetch intent，每个尝试一次。新闻 18 的正文由既有常规同步更新到 revision 2，因此它的 refetch 回写因旧 revision 被拒绝；不能把该次 refetch 记为成功。共 9 篇存储正文版本更新，均保持 unknown。

| 新闻 | 任务结果 | 修复前字节 | 当前字节 | 正文版本 | 链接 |
|---|---|---:|---:|---|---|
| 13 | success / accepted | 53864 | 54197 | 1 → 2 | [原文](https://www.theverge.com/podcast/1012839/pritzker-ai-privacy-data-centers-flock-congress-laws) |
| 14 | success / accepted | 5097 | 7070 | 1 → 2 | [原文](https://www.theverge.com/gadgets/1013645/apple-mac-mini-m4-lg-c6-oled-deal-sale) |
| 15 | success / accepted | 1247 | 3509 | 1 → 2 | [原文](https://www.theverge.com/tech/1013735/amazon-x-energy-aep-nuclear-indiana) |
| 16 | success / accepted | 1392 | 2026 | 1 → 2 | [原文](https://www.theverge.com/tech/1013028/apple-second-october-product-launch-announcement) |
| 17 | success / accepted | 2462 | 3837 | 1 → 2 | [原文](https://www.theverge.com/gadgets/1013911/sonys-best-noise-canceling-earbuds-are-nearly-100-off-today-only) |
| 18 | failed / stale | 1093 | 11610 | 1 → 2 | [原文](https://www.theverge.com/tech/1013918/miles-plug-vehicle-tracking-data-privacy-specs-price-launch-date) |
| 19 | success / accepted | 1161 | 5899 | 1 → 2 | [原文](https://www.theverge.com/ai-artificial-intelligence/1014045/coreweave-stock-debt-sector-ai) |
| 20 | success / accepted | 1288 | 5315 | 1 → 2 | [原文](https://www.theverge.com/science/1013954/fossil-fuel-power-infrastructure-data-centers-report) |
| 21 | success / accepted | 1212 | 1358 | 1 → 2 | [原文](https://www.theverge.com/tech/1014115/elon-musk-spacex-trump-account) |
| 22 | failed / stale_policy | 1165 | 2950 | 1 → 2 | [原文](https://www.theverge.com/tech/1005073/baseus-security-primesentinel-u2-pro-outdoor-3k-dual-camera-tracking-spotlight) |
| 23 | skipped / preview_stale | 1492 | 1492 | 1 → 1 | [原文](https://www.theverge.com/tech/1014209/google-home-speaker-bug-continuous-download) |

## 验证证据

Python 3.12.15，Django 6.1.2；使用已有应用镜像，`docker run --rm --network none` 挂载独立源码只读，合成数据库在容器 `/tmp`。未挂载真实配置、凭据或数据库。Node 22.23.3；依赖复用已有匹配 lockfile 的 node_modules，没有更改宿主依赖。

- PASS：`test_feed_policy.py test_control_worker.py test_sync_reconciliation.py test_body_repair.py`，170 项。正文修复命令最后增加进程锁及未知取消分类后另跑 6 项通过；最终与 `test_sector_feeds.py` 合跑 50 项通过。
- PASS：`test_body_commit.py test_ai_readers.py test_ai_private_translation_t05.py test_chat_ownership.py test_body_repair.py`，147 项。覆盖旧写入权限、失败留旧文、摘要/完整性、正文变更后的译文/问答版本边界。不同运行包含重复测试，不能相加为独立测试总数。
- PASS：独立任务前端 typecheck、lint、4 个定向文件 25 项、build；本地既有功能叠加版本 typecheck、lint、4 个定向文件 26 项、build。
- PASS：Chrome 真实本地阅读页显示更新后的正文，小闻与阅读页均显示“已获取内容，完整性未确认”。打开、刷新页面和小闻读取空历史前后 refetch 数量均为 10，没有发送聊天或生成推荐问题。
- FAIL → 修复后 PASS：命令首次使用 `Path.open(opener=...)` 写清单失败，修复为标准 `open`；内存测试库的锁目录修正后回归通过。本地叠加版本的旧测试 fixture 缺少既有 hook mock，改用本地原有 fixture 加新增文案断言后通过，没有更改产品逻辑迎合测试。
- NOT_RUN：真实付费模型、非空真实聊天历史回读、生产部署、远端 CI。合成版本隔离测试不能冒充真实模型或历史会话 UAT。

原始日志位于 `/tmp/newshub-rss-body-*.log`、`/tmp/newshub-rss-ui-*.log`。本地逐篇 JSON 与配置备份位于 `/home/lambert/.local/share/newshub/uat-20261020/rss-body-recovery/`，不含模型调用证据。

## 备份与当前运行状态

- SQLite 在线备份：容器 `newshub-local-uat-app-1` 的 `/var/lib/newshub/rss-before-body-repair.sqlite3`；`PRAGMA integrity_check` 为 `ok`。
- Miniflux PostgreSQL 逻辑备份：上述本地目录 `miniflux.before.dump`。配置 `compose.yaml.before`、`translation-fix.override.yaml.before`、`app.env.before`、`translation-redis.app.env.before` 权限为 0600，不打印或提交内容。
- 当前 FeedBinding：desired_mode=feed，policy_version=applied_policy_version=4，ready。应用/同步服务全文开关均为 0；Miniflux 已确认回退直读。
- 当前应用镜像：`newshub:local-rss-body-recovery-final-20261020`，基于当前既有本地镜像叠加工具与 UI，保留无关本地修复；同步镜像恢复 `newshub:rss-local-uat-8f7fed6`。
- 本地启动：在 `/home/lambert/.local/share/newshub/uat-20261020` 使用 `docker compose -p newshub-local-uat -f compose.yaml -f translation-fix.override.yaml -f rss-body-recovery.override.yaml up -d --no-deps app rss-sync`。

## 命令使用与恢复

仅在来源许可、明确本地实例和备份就绪后操作；以下路径需可写。启用开关并不意味着许可已满足，命令仍会拒绝受限来源。目标文章可用 `--target-url`，否则使用最近 7 天发布时间窗口；execute/resume 使用冻结清单，不重新扩展范围。

```sh
python backend/manage.py rss_repair_policy preview --manifest /safe/policy.json --target-feed https://publisher.example/feed
python backend/manage.py rss_repair_policy execute --manifest /safe/policy.json
# 等待既有 rss-sync 把策略版本应用成功后才预览文章
python backend/manage.py rss_repair_bodies preview --manifest /safe/bodies.json --days 7
python backend/manage.py rss_repair_bodies execute --manifest /safe/bodies.json
python backend/manage.py rss_repair_bodies resume --manifest /safe/bodies.json
# 恢复原采集模式，继续由 worker 应用；保留已经取得正文
python backend/manage.py rss_repair_policy restore --manifest /safe/policy.json
```

本次恢复已执行，不需要再次覆盖数据库。完整数据库回滚会丢失用户随后活动，不作为正文修复的默认回退；恢复采集配置、保留正文即可。继续自动提取前，需要能可靠区分 The Verge 公开与受限文章的来源策略；现有域级模式不足以作出该保证，因此这一部分标记 BLOCKED。
