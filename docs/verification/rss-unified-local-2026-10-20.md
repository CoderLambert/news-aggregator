# RSS 频道统一、旧采集退役及本地默认来源验收

本轮对应 RSS T16/T19/T20/T31 的实际差额，按用户授权整合 PR [#154](https://github.com/CoderLambert/news-aggregator/pull/154) 和 [#157](https://github.com/CoderLambert/news-aggregator/pull/157)，不代表所有历史 RSS/BYOK 发布任务已验收。

整合基线为 `main@8f7fed66cb66bdccc88bd2dd95f8f96e4a3288c2`；两项来源提交分别为 `cf28863`、`019f0616`。本地应用镜像 revision 为 `8159fa673c15bc135dcf89b314b79a75dfeb8ae5`；此后 `236f852` 修复宿主维护 UID/备份访问，`34112c8` 修复 CI 残留测试路径，未改动应用运行代码。最终交付 head、完整 CI 和 mergeCommit 以 [PR #158](https://github.com/CoderLambert/news-aggregator/pull/158) 为准，不能用 Draft 快检或本地结果替代完整门禁。

## 实现范围

- 删除 Scrapy、旧全文抓取服务及对应管理入口/依赖，保留仍使用的安全 HTTP、来源策略、历史原文和迁移围栏。`sync_channel_catalog` 不再自动恢复静态频道。
- 统一来源列表、频道列表、单项/批量/直接订阅资格；没有真实 Feed、当前策略未应用或来源授权失效时，不创建订阅。待验证请求只保留控制操作，不提前赋予文章访问权。缓存按用户及 history/subscribe 用途隔离。
- 同一引擎身份下公开 Feed 和原文复用，个人关系和私人内容仍分别授权；个人来源不自动公开，凭据/私人令牌 Feed 拒绝进入公共共享链路。编辑固定引用独立于个人订阅；最后一个普通引用移除后停采，历史原文保留。
- `rss_initialize` 默认预览；本地包装器显式 `--apply --reset-content` 才清理。先停写并做配对备份，保留用户、模型配置和审计；清除新闻、来源、订阅、私人内容及派生索引，并撤销旧导入/正文完成交接，防止重放回流。相同清单重跑保留新数据。
- 十个来源使用版本清单 `curated-tech-ai-dev-v1`，SHA256 `1f9a9e30d8437584d7787eaf91abf6eaf3b4d0cc29fb28ece3a88d9a95bb73eb`。应用/同步默认开启允许的正文提取，尊重显式关闭；已采样原生全文 Feed 直读。提取成功仍显示完整性未确认。

主要文件为 `backend/api/rss/{initialize,subscriptions,operations,control_worker,engine,sync}.py`、`backend/api/services/channel_catalog.py`、迁移 `0073/0074`、`frontend/src/{pages/ChannelWorkspace.tsx,services/channelQueries.ts,services/newsQueries.ts}` 和 `scripts/rss/initialize.py`。操作及配对恢复见[本地初始化说明](../deployment/local-rss-initialize.md)。

## 隔离验证记录

所有自动测试使用合成账号、临时数据库及无真实模型密钥的独立资源；未把实际本地业务备份复制进测试。原工作区的 SQLite 和未提交文件保持原状。

| 检查及命令范围 | 结果与证据 |
|---|---|
| `bash ops/ci/benchmark-xdist.sh`，Python 3.12、三根完整矩阵、串行敏感模块及两 worker | 应用代码 `327e408`：2044 PASS / 16 SKIP，2060 测试身份对账，无重试；`backend-delivery-final.log` |
| Node 22：`npm run typecheck`、`npm run lint`、`npm run test:run -- --maxWorkers=2`、`npm run build` | 706 PASS / 100 文件，类型/构建通过；已有 hook 依赖 warning 保留；`frontend-final-counter.log` |
| UID/备份维护最终回归 `scripts/deploy/tests/test_rss_initialize.py` | `236f852`：6 PASS；应用 UID 的 SQLite `BEGIN IMMEDIATE`/rollback 写权限预检通过，无内容修改 |
| 快速安全回归：safe_http、retired_ingestion、research_csrf、nginx_templates | `34112c8`：80 PASS；CI unittest 50 PASS。原入口引用已删除模块，先记录真实 CI 失败及路径存在性红例，再修复两个阶段入口 |
| 真实 Miniflux 日期边界：`tests/rss_engine_contract/live_date_boundary.py` | 1 PASS：旧文在正文 HTTP 请求前过滤，恰好边界及时区等价时间正确，后续 poll 保留下界 |
| 合成实例配对备份/恢复 | SQLite 逻辑导出一致，用户/新闻/收藏/问答/模型配置恢复；PostgreSQL 在独立临时库恢复后校验用户 2、Feed 8、entry 2356，随后删除该测试库 |
| 全新实例初始化及重启 | 两个独立项目均 10 个候选、8 个 ready，失败候选不变为有效频道；32 篇新文章重跑后不删除。先完成控制操作和后续同步，最后才启动应用 |
| 普通来源双用户真实引擎生命周期 | A/B 使用同一物理 Feed；A 退订 B 继续；最后 B 退订后 engine disabled；同一 Feed ID 15 和原文 IDs 保留，无重复抓取 |
| Chromium 桌面及 412px 视口 | PASS：候选禁用、无横向溢出；A 私人历史可见；同一浏览器 logout/login 后 B 无 A 的订阅/分组/问答，B 订阅复用同一 article revision；打开/回读没有抓取或推理 POST |
| 合成镜像 G1 | `8159fa6` 诊断执行 PASS 并清理。此前同版本一次报告不完整，不计 PASS；真实 Provider 与生产不在 G1 证明范围 |
| 合成镜像 G2 | `8159fa6` PASS 并清理：真实 Chromium 验证账号切换、owner/CSRF、停用账号、RSS 管理 UI 与 AI 关闭拒绝；合成用户，不证明真实模型 |

完整本地原始记录位于 `/tmp/newshub-rss-unified-evidence-20261020/`。保留了初始红例、一次前端 ResearchPanel 等待超时（单独诊断 18 PASS，随后限并发全量通过）、G1 不完整执行以及真实本地维护失败日志，没有删除失败记录或削弱断言/skip 预算。可长期审阅的浏览器结果见[JSON](rss-unified-20261020/browser-acceptance.json)、[移动候选列表](rss-unified-20261020/channels-mobile-pending.png)、[阅读与小闻](rss-unified-20261020/reader-chat-completeness.png)；问答内容是隔离合成历史，无真实模型调用。

## 已执行的实际本地初始化

目标仅为 Compose 项目 `newshub-local-uat`，目录 `/home/lambert/.local/share/newshub/uat-20261020`。备份位于其 `backups/rss-unified-20261020/`，目录 700、文件 600，包含应用 SQLite、专用 PostgreSQL、配置和派生内容；不得提交或用于自动测试。备份校验、维护 journal 和原镜像身份保留，可按操作说明配对恢复；只回退代码不能恢复已删除内容。

初始维护在引擎清理后遇到 hardened 容器 `cap_drop=ALL` 下 root 无权写 UID 10001 的 SQLite。停写状态与备份完整保留；按 journal 核对原容器、校验和、引擎空状态及应用尚未初始化后，使用正常应用 UID 从该检查点继续，未重复引擎删除。修复后的包装器使用非 root UID，并在引擎清理前检验 SQLite 写权限；备份临时借给应用 UID，结束/异常均恢复操作用户所有权。

最终 3 个登录账号、1 个 UserAIConnection、1 个模型配置、5 项用途偏好和 24 条 AICallAttempt 的数量及内容哈希在前后与重复执行后完全一致。旧新闻 24、来源 62、订阅 4、分组 1、问答会话 2、收藏 1、研究会话 4 已按授权清除；初始化后来源 10、新闻 30、个人订阅 0。重复执行 `changed=false`，保留 30 篇新闻。

冻结下界为 **2026-10-14 00:00 UTC**。Miniflux 原生规则只有日期精度，本次将“当前减七天”向上取整到 UTC 零点，因此窗口比精确七天短不足一天，确保不采入更旧文章。下界永久保留，不随轮询后移或移除。

| 来源 | 本地最终状态 | 正文模式 |
|---|---|---|
| 阮一峰 | READY | 原生全文 Feed |
| 美团技术团队 | UNKNOWN，`create_outcome_unproven` | 允许引擎提取，未确认创建 |
| OpenAI Blog | READY | 引擎提取 |
| DeepMind | READY | 引擎提取 |
| Hugging Face | READY | 引擎提取 |
| WebKit | UNKNOWN，`create_outcome_unproven` | 原生全文 Feed，未确认创建 |
| V8 | READY | 原生全文 Feed |
| Mozilla Hacks | READY | 原生全文 Feed |
| GitHub Blog | READY | 原生全文 Feed |
| Martin Fowler | UNKNOWN，`create_outcome_unproven` | 允许引擎提取，未确认创建 |

READY 表示绑定及采集策略已确认，不等于所有文章均确认全文。三个未知结果暂停并保留候选，未经核对不得盲目重发创建；Martin Fowler 在隔离实例成功，不能据此把实际目标状态改为成功。

应用、RSS 同步、Miniflux 和 PostgreSQL 已恢复健康。channel-worker/indexer 保持停止，避免本次维护自动触发用户配置的收费推理；配置保留，未执行生产部署、真实付费模型或绕过登录/付费限制。其他本地预览栈未清理。

## CI 与交付边界

Runner 离线时，本轮只在确认没有 Worker、GitHub busy=false 且 DinD 无容器后，将 `newshub-ci` 三个现有容器的网络命名空间 eth0 MTU 从 1500 临时改为 1280，HTTP 恢复 200、Runner 恢复在线；未改宿主网络、认证或生产服务。Compose 原已声明 1280，本次未在作业运行时重建网络；现存容器重建前应遵循 CI README 的空闲窗口流程。

首轮 Ready [CI #39431887139](https://github.com/CoderLambert/news-aggregator/actions/runs/39431887139) 的 frontend 已通过（706 PASS），另一个 [三轮矩阵 #39431887165](https://github.com/CoderLambert/news-aggregator/actions/runs/39431887165) 每轮 2045 PASS / 16 SKIP、2061 身份对账通过。完整 backend 在 T00 合成研究工具处失败：临时 SQLite 已隔离，但 Chroma 仍沿用生产 `/var/lib/newshub/chroma`，非 root Runner 返回 PermissionError。PR 退回 Draft 后，将 Chroma/TTS 显式绑定同一临时目录，并在 T04 入口核验派生路径归属；CI 契约先红后绿（50 PASS）。未放宽目录权限、研究授权或业务错误断言；须由后续修正提交的完整 CI 重新证明联合流程。

最终合并必须满足 PR #158 最新 head、当前 base 的选中完整 frontend、backend-and-release-gates 和 merge-gate SUCCESS。真实来源/本地浏览器证据限于上述场景；其他历史规模、生产上线、真实模型及人工签署仍不在本次完成范围。

修正提交 `f52461b` 的 [Ready CI #39435429873](https://github.com/CoderLambert/news-aggregator/actions/runs/39435429873) 已通过前端、T00 联合流程和完整后端矩阵，生产镜像仍因 PyPI 约 15 kB/s 的冷下载未完成，随后退回 Draft 处理。镜像未构建完成不计 PASS。MTU、镜像源及跨引擎构建缓存尝试的失败记录均保留；未切换包源、改全局网络、删除门禁或替换共享依赖。

最终采用 [Docker 原生 pip 缓存挂载](https://docs.docker.com/build/cache/optimize/#use-cache-mounts)：生产依赖仍从官方 PyPI 安装，下载缓存独立于镜像层。使用同一 CI 已有的公开包缓存为新建 BuildKit 缓存预热，原缓存只读保留。同一 `anthropic==1.13.0` wheel 的官方 SHA256 校验一致，禁网缓存读取 0.282 秒，对照冷下载约 146 秒；这只证明该包缓存复用，不冒充整套镜像/CI 的通过或统一加速比例。新构建输入仍须重新完成完整 CI、镜像和 G1 门禁。
