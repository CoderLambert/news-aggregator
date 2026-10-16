# RSS 迁移的部署、旧入口与恢复基线审计

> 证据版本说明：本文保留对 878b690 / 上游候选版本的静态审计事实，不是运行证明。514410b 之后的任务编号、并行/审批/DDL/transport 和验收建议由修订后的 [决议](ARCHITECTURE-DECISIONS.md)、[接口合同](INTERFACE-CONTRACTS.md)、[任务](TASKS.md) 覆盖；不得把历史建议当作额外前置。

本报告审计代码基线为 `878b69081f8d5b3ae965bcf1c855390b059caa33`。它记录仓库中的实现及后续验收缺口，不证明生产镜像、实际开关、已启动进程、来源成功率或资源指标。本次仅交付规划文档，不执行产品测试、数据库命令、迁移、回填、来源切换或生产操作；未读取 `.env` 或凭据。下面的命令均为后续开发任务可复用的验收入口，不能标为本次已执行通过。

## 现有部署边界

| 边界 | 代码证据 | 迁移合同要求 |
| --- | --- | --- |
| 开发 Compose | `compose.yaml:2`、`:20` 挂载宿主 `backend/`；`README.md:74`–85 介绍默认 `docker compose up` | 与生产不可混称；分别验收默认安装与已有数据接管 |
| 生产 Compose | `compose.prod.yaml:35`–41 是一次性 migrate；`:44` 使用不可变镜像；`:55` app 使用 host 网络；`:155`–161 是独立持久卷 | 保留 NewsHub SQLite、既有 Nginx/BYOK 网络；新增 Miniflux 专用 PG，不迁移业务库 |
| 镜像边界 | `Dockerfile:19`–28 安装 Torch、全部 requirements 并复制 crawler；`:38`–54 定义非 root production target | rss-sync 必须有锁定依赖的轻量 target，不能继承需要 Torch/抓取依赖的当前 runtime-base |
| 迁移时机 | `scripts/docker-entrypoint.sh:4`–10 仅 development 自动 migrate；`scripts/docker-migrate.py:19`–31、`:52`–60 使用 SQLite 目录锁 | 保持一次性迁移与锁；Miniflux/PG 运维必须有自己的版本与恢复合同 |
| 模型预加载 | `backend/api/apps.py:16`–24 通过测试/`NEWS_CRAWL_ONLY`/`RUN_MAIN` 条件抑制 embedding preload | rss-sync 的依赖、命令与启动验收需证明不导入模型，不能只保证主循环不调用它 |
| 智能频道 worker | `compose.workspace.prod.yaml:9`–12 解释 loopback BYOK 的 host 网络需求；`:27`–34 限制卷与凭据 | 保留现有功能和信任边界；它也是 SQLite writer，备份停写不得遗漏 |

README 的 Python 要求为 ≥3.11（`README.md:61`），Docker 与 CI 固定 Python 3.12（`Dockerfile:9`、`.github/workflows/ci.yml:49`）；README 称 Django 6（`:52`），requirements 只有 `django>=4.2`（`backend/requirements.txt:1`）。后续版本锁定以实际解析和运行验证为证据，不能把文案当作锁文件。

## 旧采集入口删除与保留矩阵

迁移阶段允许不同来源由不同引擎拥有，但同一来源只能有一个 owner。最终清理必须验证宿主已部署入口和重启行为；删除仓库文件不等于卸载现有 cron、systemd unit 或容器。

| 职责或入口 | 证据 | 最终动作与验收要求 |
| --- | --- | --- |
| 常驻 Scrapy 调度 | `compose.yaml:36`–63、`compose.prod.yaml:80`–102；`backend/api/management/commands/crawl_worker.py:137` 调用 `crawl` 子进程 | 按来源 fence，验收后删除服务、命令、调度执行与专属健康检查 |
| 常驻全文 worker | `compose.yaml:65`–92、`compose.prod.yaml:104`–129；`backend/api/management/commands/auto_fetch_full_content.py:40`–61 | 最终删除旧执行行为及进程；显式重试转引擎操作 |
| 禁用但仍常驻的全文 worker | `auto_fetch_full_content.py:68` 明确禁用模式仍产生心跳 | 仅设 `FULL_CONTENT_WORKER_ENABLED=0` 不算进程已退出 |
| Scrapy 代码与专属 pipeline/handler | `crawler/news_crawler/spiders/`、`crawler/news_crawler/pipelines.py`、`crawler/news_crawler/download_handlers.py` | 真实来源替代/停止更新通过后删除，不能留下隐藏抓取兜底 |
| 手动及 cron 抓取 | `scripts/crawl_cron.sh:12`、`scripts/crawl_once.sh:21`–24、`scripts/news-cron:72` | 清理所有旧执行入口与定时启用路径 |
| 一键启动旧调度 | `scripts/news:14` 调用 crawler start，`:9` 指向 news-cron | 新入口显式启动新角色；重启后不复活旧调度 |
| systemd 抓取 | `scripts/news-aggregator-crawl.service:6`–7、`scripts/news-aggregator-crawl.timer:5`–8 | 记录实际安装实例，经批准停用或卸载；本规划不操作宿主配置 |
| 全文 cron/CLI | `scripts/fetch_full_content_cron.sh:44`；管理命令 `fetch_full_content`、`backfill_full_content_scrapy`、`fetch_article_url`、`compare_providers` | 移除旧抓取执行与教程；需要的重试使用有配额的 FeedOperation |
| 旧 Feed parser | `backend/api/services/feed_support.py:6`、`:44` | 移除运行引用及 feedparser；历史迁移按兼容需要冻结保留 |
| 全文提取 Provider | `backend/api/services/article_fetcher/`；`full_content_worker.py:190` 调用旧入口 | 删除站点提取、HTTP 正文获取与多 Provider 回退；先清理共用能力依赖 |
| 共享安全能力 | `backend/api/services/source_probe.py:11`、`source_policy.py:243`、`research/tools.py:25`、`:31` 等仍依赖 article_fetcher | 明确新的通用模块归属，验证保留用途；不能整目录删除导致其他产品断裂 |
| 内容入库与版本保护 | `backend/api/services/news_ingestion.py:14`–15 依赖旧候选/validator | 保留去重、版本保护职责，移除旧采集候选和调度副作用 |
| 向量索引 | `compose.yaml:94`–122、`compose.prod.yaml:131`–153 | 保留；不能把移除索引成本算作 RSS 架构收益 |
| 智能频道 | `compose.workspace.yaml:7`、`compose.workspace.prod.yaml:8` | 保留产品能力与必要 worker，纳入所有 writer 清单 |
| 旧网络 overlay | `compose.host-network.yaml:5`–8 仅指向 crawler/full-content | 最终清理并说明现有本机 override 的升级路径 |
| 依赖 | `backend/requirements.txt:9`、`:10`、`:19` 为 Scrapy、scrapy-playwright、feedparser | 依赖图和运行验证后移除；`:14`–15 的 sentence-transformers/ChromaDB 保留 |

本机部署教程也会重新启动旧系统：`docs/deployment/local-source.md:66`–81 指导启动全文、采集、索引和智能频道 worker，`:99`–109 指导旧正文入队与 cron。最终运维交付须同步 README、启动说明、示例配置、CLI 与本机部署文档。

## AI 中实际存在的旧提取依赖

“保留 AI”和“删除旧提取器”不能通过删除两个定时容器同时实现：

- `backend/api/services/llm_translator.py:170`–180 的 `fetch_and_verify_chinese_content` 使用 `TrustedNewsJinaProvider` 获取中文译文链接，`backend/api/views.py:635`–638 有实际调用。
- `backend/api/services/research/tools.py:1007`–1035 的 `fetch_webpage` 使用同一 Jina Provider；`:25` 依赖 Provider 内的 `_open_url`，`:1019` 依赖执行范围。

必须通过独立 ADR 锁定这些功能转向本地内容/引擎的行为或可接受的产品降级，并建立兼容验收。不得将旧 Provider 改名搬家后认定删除完成；在合同未定前依赖该边界的删除任务阻塞。

## 现有备份与恢复的实际约束

现有能力仅覆盖 NewsHub SQLite，不覆盖 Miniflux PostgreSQL：

- `scripts/deploy/backup.sh:106`–108 使用 SQLite online backup。volume 模式 `:115`–117 拒绝任何运行中的容器挂载目标卷，必须先停所有 writer；不能只停止 crawler，也不能只复制活动主文件忽略 WAL。
- `scripts/deploy/restore.sh:63`–95 要求 snapshot、sidecar、release manifest。覆盖已有目标必须同时提供 `--replace --writers-stopped --prior-backup`；volume 模式 `:119`–121 也要求没有运行容器挂载该卷。
- `scripts/deploy/sqlite_snapshot.py:558`–568 校验 prior backup 与当前目标的逻辑内容一致，恢复库迁移集合匹配目标 manifest；它不是任意 SQLite 文件覆盖工具。
- `scripts/deploy/deploy.sh:8`、`rollback.sh:8` 的固定停服列表没有未来 rss-sync，workspace 分支分别在 `:173`、`:161` 添加 channel-worker。新角色必须加入停写、失败关闭、健康和恢复流程。

新增恢复合同必须覆盖一致性 SQLite 快照、PG 原生备份、引擎版本与实例身份、Feed 映射、受保护凭据、恢复顺序和恢复后完整对账。RSSHub 缓存可重建；OPML 不能备份正文、译文、研究和用户关系。两库恢复不等于分布式原子快照，必须声明恢复点和恢复点后的数据影响。

## release manifest 和回滚的阻塞

`scripts/deploy/release_manifest.py:50`–74 严格校验 schema v1/v2/v3 及字段，目前 capability 仅支持 `full_content_worker`、`channel_worker`。`:402`–408 无条件把 crawler 和 indexer 加入目标服务。最终删除 crawler 前必须同步升级 manifest、deploy、rollback、SQLite snapshot 的 manifest 校验和相关测试，不能只改 Compose。

`scripts/deploy/rollback.sh:238`–247 要求数据库 migration 集合与目标 manifest **完全相等**。即使后续迁移全部为 additive，直接把旧兼容镜像交给当前 rollback.sh 也会被拒绝。架构所需的“保留新数据，退回兼容过渡版本”不能写成已经由现有脚本支持。

冻结回滚合同时必须选择、证明可运行的兼容基点与 schema 范围，并完成独立审核和隔离演练；不得简单用“迁移集合是子集”代替 schema/内容状态兼容验证。普通应用回滚不恢复数据库；灾难恢复单独授权，明确恢复点与潜在数据损失。对旧系统从未支持的新 Feed，只能暂停，不能宣称自动退回 Spider。

## 原生 RSS 与 RSSHub 分别放行

原生 RSS 的引擎部署、同步、内容和安全验收是独立 gate。RSSHub 还必须额外通过受保护的公共 HTTPS Feed 网关、真实公网 DNS、TLS、专用认证、批准路由和限额、公网回流验收；不能关闭 Miniflux 私网防护来绕过失败。

当前仓库没有 Miniflux、PG 或该 Feed 网关的运行证据。RSSHub gate 未通过时，RSSHub profile 标记 BLOCKED；已通过原生 RSS gate 的范围可单独推进。路由模板不是健康实例，公共演示实例不能作为生产依赖。

## 已有 CI 定义与后续命令

`.github/workflows/ci.yml:11`–36 定义 frontend job；`:38`–99 定义 backend-and-release-gates，包括三个测试根、synthetic `check --deploy`、离线 shell 测试、非 root production image 和隔离 G1 域名烟测。主控实际查询分支保护/rules API 返回 403，故保护规则和必需状态检查名称无法确认，标记待核验；不据工作流名称假定保护配置，不绕过已有保护或必需 CI。

前端命令在 `frontend/` 执行，CI 使用 Node 22：

```bash
npm ci
npm run typecheck
npm run lint
npm run test:run
npm run build
```

后端与离线运维命令在仓库根执行，使用隔离依赖和 synthetic 配置，CI 环境为 `PYTHONPATH=backend:crawler RUN_MAIN=true`：

```bash
backend/venv/bin/python -m pytest --collect-only -q tests/ backend/api/tests/ scripts/deploy/tests/
backend/venv/bin/python -m pytest -q tests/ backend/api/tests/ scripts/deploy/tests/
bash -n scripts/deploy/smoke.sh scripts/deploy/deploy.sh scripts/deploy/rollback.sh scripts/deploy/backup.sh scripts/deploy/restore.sh scripts/deploy/tests/test_release_scripts.sh
bash scripts/deploy/tests/test_release_scripts.sh
bash scripts/deploy/tests/test_export_static.sh
bash scripts/deploy/tests/test_preflight.sh
bash scripts/deploy/tests/test_local_domain_args.sh
```

`scripts/run_tests.sh:31` 仅跑 `tests/backend/`，`:54` 另跑 crawler；未覆盖 `backend/api/tests/`、`scripts/deploy/tests/` 或前端 Vitest/typecheck/lint，不能充当统一验证入口。`scripts/deploy/local-domain-smoke.sh:185` 明确 G3 task/worker acceptance 尚未实现；现有 G1/G2 不能代替真实引擎、来源和故障恢复验收。

## 安全并行的写入边界

接口和 DTO 冻结后，隔离引擎部署/备份与 SDK 客户端可在互不重叠的文件范围并行；纯内容转换与目录 snapshot/search 可并行。T05 拥有核心模型，目录/已读/OPML 模型随领域功能交付；migration 编号和共享文件串行合并，消费者可按已审接口/fixture 提前开发。

release manifest、停写/备份、rollback 与 Compose 会修改共同运维文件，按功能拆分独立开发，共享文件串行合并；只有真实资源或同一关键算法冲突才串行执行。前端可消费冻结的 fixture 开发，但同一发现/添加组件不能由两任务并行修改。最终旧系统删除依赖全部来源替代或明确停止更新、AI 提取边界决议、恢复演练及零旧入口运行证据，不与来源迁移抢跑。
