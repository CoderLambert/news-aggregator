# RSS 迁移开发执行状态

2026-10-16。用户已通过独立会话交接授权修订规划的隔离实现、任务分支提交推送和开发 PR；不授权 main 合并、生产切源、停服务或部署。文档中的历史 REVIEW_REQUIRED/仅规划授权说明由本次开发授权更新，生产门禁仍有效。

基线：PR #77 head `17d48915bbacd6a448578c64676a6dac4c2f263e`，main `878b690`。集成分支 `feat/rss-engine-integration-20261016`，worktree `/tmp/newshub-rss-integration-20261016`。原工作区数据库改动及两份未跟踪文档保留。

状态语义：ready 可开发；running 实现中；blocked 仅列具体受阻证据；review 待审；integrated 已集成；accepted 已满足该任务验收。integrated 不代表生产验收。

| 任务 | 负责人 / 模型 | 状态 | 分支 / SHA | 独占文件 / 依赖 | 证据、阻塞与下一步 |
| --- | --- | --- | --- | --- | --- |
| T00 | rss_t00 / gpt-6.1-sol high | integrated / A4 partial | 7ca5ff1→72ab3a1 | tests/rss_engine_contract、ops/rss/T00 | 离线16+真实13通过；主调度Python3.12复跑13通过；公网HTTPS/DNS/网关门禁保留 |
| T06 | rss_t06 / gpt-6.1-sol high | integrated | ebf8eac→5ae2c44 | rss/content.py、转换测试、requirements转换依赖 | 30专项通过；主调度审查；浏览器/T07组合待验 |
| T16 | rss_t16 / gpt-6.1-sol high | integrated | 81ad293→d0472c1；2bd6705→3a56b0d | directory.py、directory_models.py、0052、固定种子许可 | 41项真实元数据，19专项通过；按日worker与用户状态待T09/T20接线 |
| T05 | rss_t05 / gpt-6-astra high | integrated | 35a7d29→df93a48；364e13a→05ff8e3 | rss/models.py、0053–0055 | 46专项与96直接回归通过，根独立审查 |
| T04 | rss_t04 / gpt-6-astra high | integrated | 89b5b34→7ad76ae；6975200→ece2f33 | rss/engine.py、SDK依赖 | 41专项通过；根审查修正HTTP文章URL及未知结果 |
| T02 | rss_t00 / gpt-6.1-sol high | integrated | 27a436c→c32aea1；c9cfb88→21bbd10 | Dockerfile、可选Compose、轻量运行壳 | 实际Python3.12镜像58MB/ORM/凭据隔离/单进程锁通过；5专项与65部署回归通过；sync_ready=false待T08/T09 |
| T07 | rss_t05 / gpt-6-astra high | integrated | 3f9e20e→214fb08；6d4b393→6601948 | content_store/legacy_translation | 87专项组合通过；根非作者审查正文CAS及原子译文；下游旧写待T25 |
| T11 | rss_t04 / gpt-6-astra high | integrated | b9d717c→da2365c | access、现有读取入口 | 非作者审查；72专项直接回归通过；空正文旧修复状态缺口由T14集成修正 |
| T08 | rss_t00 / gpt-6.1-sol high | integrated | ea7221e→1af2f2c | operations/control_worker/runtime | 48专项与最终轻量镜像真实六动作、0/1/3发现、20actor→1Feed通过；unknown配置缺DTO规则证据保持门禁 |
| T25 | rss_t05 / gpt-6-astra high | integrated | 8317854→efe5f09；cf2faa0→3e42cd8 | legacy_fencing/source_migration、旧写入口 | 非作者审查；397直接组合、最终35专项；显式获取前token和可恢复切换；生产未执行 |
| T19 | 主调度 | integrated / batch review | 9305fd3及0f1f00d | subscriptions、HTTP控制、旧订阅委托 | 20并发、幂等/用户隔离；T14非作者发现缺header重放校验已修；真实组合待T09 |
| T17 | 主调度 | integrated | 5b756cf | discovery、resolve路由 | 23专项；T08真实发现0/1/3与timeout通过；浏览器待T27 |
| T13 | 主调度 | integrated / browser pending | 081a19a、2e58353、9149e54 | 0056、read-state、读取/显式修复前端 | 自动抓取移除；个人已读+操作轮询；早期580前端、75后端组合；新UI组合36通过 |
| CI基线修复 | 主调度 | integrated | 7f79671 | 两个旧测试文件 | 10专项通过；registry夹具与HOLDER SIGTERM竞态最小修复，CI待跑 |
| T24 | 主调度 | running / 真实副本 blocked | 集成分支 | migration_inventory.py、scripts/rss-inventory.py、自有测试 | 57静态来源；6专项通过；显式SQLite副本只读hash导出器已实现；真实副本和覆盖处置待补 |

| T14 | rss_t04 / gpt-6-astra high | integrated / final corrections | a0482ed→7654371 | stored_readers、translation/speech/research | 当前ACL/hash/revision与旧译文保留；0058/0059根已合；全量发现隔离hash相同及SSE临时锁两边界，作者补最小修正 |
| T03 | rss_t00 / gpt-6.1-sol high | integrated | 3cae565→4b32468；845789d→4ac939e | scripts/rss/recovery、rollback最小扩展、ops/T03 | 非作者审查；117专项、25最终专项与真实PG+SQLite fresh/overwrite/replay通过，证据截至0058；0059及app兼容T26 |
| T09 | rss_t05 / gpt-6-astra high | integrated / category ACL correction | b980399→f03da66 | sync/reconciliation/runtime、ops/T09 | 固定H/full retained、独立lease、双GET前fence、T08/T21交接；62最终专项/150关联回归及真实engine故障PASS；health DTO已接线 |
| T21 | 主调度 | integrated partial | 94baab7、9f6671b、0f1f00d、f03da66 | 0057、opml/API/UI/worker | 预览确认、逐项队列重试、本人多组导出和恢复UI；T09每10秒推进，浏览器待T27 |
| T20 | 主调度 | integrated partial | 0f1f00d及当前批次 | 发现/目录/频道与连接健康 | health读取匹配instance/account/mode的60秒heartbeat；14相关UI与typecheck/lint/build通过，真实浏览器待T27 |

| T18 | rss_t00 / gpt-6.1-sol high | running / live blocked | task/rss-T18-gateway / 4ac939e | routes.py、自有gateway配置/ops/T18 | 默认关闭声明式模板；DNS/TLS/token缺失，仅阻塞网关live |
| T26 | rss_t04 / gpt-6-astra high | running / production seal blocked | task/rss-T26-rehearsal / 7654371+T03/T09 | ops/T26工具/候选证据 | 合成0051→0059旧列/PK/FK/译文保持首轮PASS，真实完整app候选与两库恢复进行中；真实副本缺失 |

继续可开发：T27真实来源/浏览器。T29/T30/T31/T33生产与退出阶段未授权，禁止提前激活删除。

## 验证环境与证据规则

Python 3.12 独立环境 `/tmp/newshub-rss-coordinator-venv`；测试指定独立合成DB路径。Agent各自隔离环境/DB/端口，主调度做跨模块验证，不重复专项。CI逐集成批次核对。T00真实引擎及T02隔离镜像已有证据；真实副本/浏览器尚无通过证据；两库恢复已有T03真实隔离0058证据，T26最终0059进行中。

分支保护查询 GitHub API 返回403（账号/仓库计划限制），保护规则 UNKNOWN；仍执行仓库CI，不推断无要求。

## 批次证据

- 开发草稿PR：https://github.com/CoderLambert/news-aggregator/pull/78，规划PR #77未改。
- Python3.12 T00：`/tmp/newshub-rss-t00-py312/bin/python ops/rss/T00/run_live.py`，13 passed/18.49s；日志 `/tmp/newshub-rss-t00-py312.log`，仅新建临时项目，自动清理。
- 首次全后端批次：1182 passed，1 failed，然后中止卡住的合成下载测试。失败/等待均因旧离线夹具仍依赖真实DNS；日志 `/tmp/newshub-rss-b1-baseline-tests.log`。生产校验未修改，1c9e259修复受控DNS并给模拟启动等待上限，相关10测试通过。
- 核心schema合入后批次重跑：`RUN_MAIN=true DJANGO_DB_PATH=/tmp/newshub-rss-coordinator-unused.sqlite3 PYTHONPATH=backend:crawler /tmp/newshub-rss-coordinator-venv/bin/python -m pytest -q tests/ backend/api/tests/ scripts/deploy/tests/`，1846 passed、13 live skipped，107.80s、退出0；日志 `/tmp/newshub-rss-b1-integration-tests.log`。测试含核心schema/转换/静态盘点/T00离线，T16功能后合入另补专项。
- PR78在5ae2c44的前端与后端release gates均通过（含image及隔离G1 smoke）；不将旧head结果当后续代码证明。

- PR78在2e58353的前端/后端/release/image/隔离G1 smoke均通过（push与PR运行），不代表后续head。
- 第二集成批backend：119 failed、1639 passed、13 skipped，162.23s，日志`/tmp/newshub-rss-b2-tests.log`。大部分是旧测试未显式创建publication/owner/token，T14相关60余项由任务作者处理，根修其它读取/旧ingestion夹具；也发现合法legacy空正文提前403和排队状态误隐藏，修产品而非放宽ACL。修后目录/OPML/旧读取组合129 passed（19.35s）；更广fixture组合初轮193 passed/15 failed，12项为测试helper机械拼写已修，另3项按正文主写/来源政策新合同明确测试。
- OPML/发现UI36 passed、typecheck/lint通过；全前端/构建第二批运行中。真实生产副本仍未提供，仅阻塞真实演练/上线。

- 第二批扩大回归：删除已移除中文外链抓取函数的旧测试引用后，2107 passed、19 failed、13 skipped，212.33s；日志`/tmp/newshub-rss-b2-final2-tests.log`。19项含旧fixture/行为断言、0059归档预期、Compose新增web身份，以及2个产品边界；逐项修复并验证，不用旧绿色CI冒充当前head。
- 连接健康UI：14 passed（957ms），typecheck/lint/build通过；`/tmp/newshub-rss-health-ui.log`、`/tmp/newshub-rss-health-lint.log`、`/tmp/newshub-rss-health-build.log`。当前健康不联网，过期/错误身份heartbeat显示unknown。
