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
| T19 | 主调度、rss_t00 / gpt-6.1-sol high | integrated / gate-off candidate | 9305fd3、0f1f00d、a9fb061→c9173c3 | subscriptions、HTTP控制、旧订阅委托 | 20并发、幂等/用户隔离；统一来源准入/首次规则/发送前fence；全文门禁默认关闭，真实direct拒绝与redirect负向证据已审 |
| T17 | 主调度 | integrated | 5b756cf | discovery、resolve路由 | 23专项；T08真实发现0/1/3与timeout通过；浏览器待T27 |
| T13 | 主调度 | integrated / synthetic browser accepted | 081a19a、2e58353、9149e54 | 0056、read-state、读取/显式修复前端 | 自动抓取移除；个人已读+操作轮询；早期580前端、75后端组合；新UI组合36通过 |
| CI基线修复 | 主调度 | integrated | 7f79671 | 两个旧测试文件 | 10专项通过；registry夹具与HOLDER SIGTERM竞态最小修复，CI待跑 |
| T24 | 主调度 | integrated tooling / 真实副本 blocked | 集成分支 | migration_inventory.py、scripts/rss-inventory.py、自有测试 | 57静态来源；6专项通过；显式SQLite副本只读hash导出器已实现；真实副本和覆盖处置待补 |
| T14 | rss_t04 / gpt-6-astra high | integrated | a0482ed→7654371；15f1bdc→ba73437 | stored_readers、translation/speech/research | 当前ACL/hash/revision与旧译文保留；0058/0059根已合；隔离hash相同及SSE临时锁已补最小修正并独立审查 |
| T03 | rss_t00 / gpt-6.1-sol high | integrated | 3cae565→4b32468；845789d→4ac939e | scripts/rss/recovery、rollback最小扩展、ops/T03 | 非作者审查；117专项、25最终专项与真实PG+SQLite fresh/overwrite/replay通过，证据截至0058；0059及app兼容T26 |
| T09 | rss_t05 / gpt-6-astra high | integrated | b980399→f03da66；a93f1bf→9043a99 | sync/reconciliation/runtime、ops/T09 | 固定H/full retained、独立lease、双GET前fence、T08/T21交接；62最终专项/150关联回归及真实engine故障PASS；health DTO已接线，额外分类按当前授权过滤 |
| T21 | 主调度 | integrated partial | 94baab7、9f6671b、0f1f00d、f03da66 | 0057、opml/API/UI/worker | 预览确认、逐项队列重试、本人多组导出和恢复UI；T09每10秒推进；T27真实浏览器选择/跳过/多组/进度/导出PASS |
| T20 | 主调度 | integrated partial | 0f1f00d及当前批次 | 发现/目录/频道与连接健康 | health读取匹配instance/account/mode的60秒heartbeat；14相关UI与typecheck/lint/build通过，T27真实浏览器PASS |
| T18 | rss_t00 / gpt-6.1-sol high | integrated partial / production gate blocked | 2210e16→e4e62fd；本机验收 287cbea | routes.py、默认关闭gateway/ops/T18 | RSSHub真实本机token验证Trending 13项、Issue 20项；85 route contracts与合成TLS/Nginx边界PASS；公网网关与Miniflux publisher auth/no-redirect仍BLOCKED |
| T26 | rss_t04 / gpt-6-astra high | integrated synthetic candidate / seal blocked | b39d8a9→53003f2 | ops/T26工具/候选证据 | 56旧表34非空保留、两完整app镜像往返、0059真实两库恢复及恢复后T09同步PASS；主调度独立审查，真实副本及完整wrapper host权限BLOCKED |
| T27 | rss_t05 / gpt-6-astra high | integrated synthetic browser / public partial | 87c47fc→60a421d；0f86dee→e768f2e | ops/T27、自有浏览器/真实来源验收 | fresh真实浏览器全链与gate1自动摘要/主题/TOC PASS；12篇公开取样，Julia原站对照PASS、Fowler完整性FAIL，保留Uber失败及其它未知，不宣称总体成功率 |

后续 T29/T30/T31/T33生产与退出阶段未授权，禁止提前激活删除。

## 验证环境与证据规则

Python 3.12 独立环境 `/tmp/newshub-rss-coordinator-venv`；测试指定独立合成DB路径。Agent各自隔离环境/DB/端口，主调度做跨模块验证，不重复专项。CI逐集成批次核对。T00真实引擎及T02隔离镜像已有证据；真实副本尚无通过证据；T27合成真实浏览器全链已通过，T26合成最终0059配对恢复已通过但未封存。

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

- 第二批修后stored-reader/health/access组合66 passed（12.35s），另迁移/旧endpoint/Compose组合59已通过项复用，修复项重新确认；`/tmp/newshub-rss-b2-fix2-tests.log`。前端当前全量90文件、591 passed（11.13s），`/tmp/newshub-rss-b3-frontend.log`；后端第三批在跑。

- 第三批全后端：2210 passed、2 failed、13 live skipped（225.08s）。两个失败仅旧SSE测试仍期待异常；产品已按安全错误event返回且不含译文。修正断言后AI读者/争用/同步专项67 passed（6.46s），覆盖当前分类ACL小修；日志`/tmp/newshub-rss-b3-tests.log`、`/tmp/newshub-rss-final-reader-tests.log`。当前完整结果由新push CI再确认。
- 最终schema makemigrations --check --dry-run无变更；base+workspace+RSS三Compose显式合成环境config --quiet退出0（未启动服务）。

- T18/T26集成后工具/路由/Nginx组合94 passed、2 live skipped（0.25s），`/tmp/newshub-rss-candidate-tools-tests.log`；T26 live cleanup5pass及完整演练复用精确image/harness证据。G2生成fixture补显式public/legacy/body_owner，8专项通过（3.29s）。
- 发现新增Feed采集默认与ARCH4.1缺口：统一feed模式及缺少worker发送前来源政策复核。rss_t00在`task/rss-feed-admission-policy`修正，rss_t04只读独立审查未知/mixed Feed受限目标的Miniflux规则边界；无DDL/生产动作。T27继续合成浏览器与实际来源取样，后补受影响默认模式联动。

- 72a193e远端前端CI通过；两次后端运行在collection停留超过20分钟，本地同命令2318 tests collected/1.03s。下一批为collection加120秒栈转储及5分钟超时以获取实际阻塞证据，未把异常标为通过。
- 生产全文门禁待集成：RSS_FULL_CONTENT_ENABLED默认0、web/sync同值，避免未验证redirect目标政策时自动或显式抓取；当前HTTP政策403/Compose专项9 passed（5.72s）。

- 最终政策补丁独立审查通过（仅gate0候选）；作者199专项/38同步非refetch通过，根合入后包含全部refetch的三root全量 **2397 passed、16 live skipped，240.62s**（业务SHA23de733），日志`/tmp/newshub-rss-final-batch-tests.log`。隔离夹具显式gate1，生产app/sync默认gate0，UI隐藏不可执行修复。
- CI停滞根因证据：7082d2b日志已显示2326项收集完成，停在OPML超大参数名前；本地该单行长1,048,643字符。7128ba3为4个参数赋短名称，收集总输出由约1.3MB降至262KB，新远端已进入真正后端测试。保留120秒栈诊断与5分钟收集上限；不把取消运行计为通过。
- 最终完整Dockerfile `production` image build（业务23de733）PASS，Node22 frontend-build PASS；image `sha256:34233ab97c4f39570dfa1993df2d5327324a21811d32760279e8fd64aabb7dbe`、UID/GID10001。未推镜像或部署。
- 完整镜像本地G1 TLS/CSRF/只读API/匿名搜索/静态资源/Mermaid/深链/SSE PASS，cleanup PASS，证据`ops/rss/integration/g1-report.json`与截图。首次失败是G1旧seed缺SourcePublication，1796192补明确public/legacy/owner；9夹具专项PASS（3.44s），之后fresh项目通过。Playwright1.62.0独立smoke venv，不改变共享测试解释器。

- T27 最终证据 e768f2e 已集成：普通用户默认自动摘要链在首次 News GET 前仅采集一次，订阅→可见29.944s（单例非p95）；实际主题/TOC PASS。原站逐项对照 Julia 原生正文 PASS、Fowler 主体可读但导语/Related Work 缺失且致谢前移，完整性 FAIL；未添加自定义提取器。合成浏览器范围已回填T13/T20/T21。
- 1796192 远端前端、后端全量测试和生产设置检查通过；发布脚本阶段失败于旧 G1 seed 测试的单行 literal_eval。随新版 heredoc 修正 AST 提取，保持原 Mermaid 内容断言；最终提交重新执行全部 CI。最终 CI 状态以 PR78 当前 head 检查为准，不用历史 head 代替。
- 最后受影响验证：发布语法与release/export-static/preflight四组shell行为检查全部PASS；G1 shell显式使用独立解释器后PASS，日志`/tmp/newshub-rss-final-shell-g1.log`。T27证据审计+G1/G2夹具组合15 passed、1 live skipped（3.34s）。
- PR #79已合入main，PR #80已合入集成分支。集成worktree快进同步c23db6c（#80）并cherry-pick #79修复为287cbea；其中crawler registry修复此前已存在，只新增worker SIGTERM竞态断言。当前本地分支领先origin一提交，尚未push。
- 同步后本机验收：`tests/crawler/test_crawl_all_serialization.py tests/backend/test_full_content_worker_process.py` 10 passed/29.01s；`DiscoverDialog`与`AddChannelDialog.validation` 9 passed；frontend typecheck、lint、build PASS。实际RSSHub fine-grained public-only Token下Trending HTTP200/13项、Issue HTTP200/20项；容器healthy且仅127.0.0.1:1200，文件0600/目录0700，日志没有PAT格式字符串。证据`ops/rss/T18/local-acceptance.json`；真实公网gateway/Miniflux publisher认证重定向门禁仍BLOCKED。PR #80 push CI通过；PR CI第一次完整通过，自动重试产生一个无步骤/无日志的2秒后端失败记录；本地受影响测试均通过。
