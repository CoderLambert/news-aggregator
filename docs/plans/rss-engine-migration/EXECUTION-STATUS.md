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
| T11 | rss_t04复用 / gpt-6-astra high | running | task/rss-T11-access / 21bbd10 | access.py、views/serializers/channel_articles等读取入口 | SQL ACL和StoredArticle开发，根负责独立审查 |
| T08 | rss_t00复用 / gpt-6.1-sol high | running | task/rss-T08-operations / 21bbd10 | operations/runtime、worker命令 | 幂等控制、租约和真实引擎操作集成 |
| T25 | rss_t05复用 / gpt-6-astra high | running | task/rss-T25-owner-fencing / 6601948 | 旧ingestion/full_content_status/crawler网络及pipeline、迁移工具 | 旧获取前token/晚写拒绝与合成切换，真实副本/生产切换未执行 |
| T17 | 主调度 | running / API integrated | 2505faf后续 | discovery.py、resolve路由 | 23发现/控制接口测试通过，真实worker组合待T08 |
| T13 | 主调度 | running / 阅读与DDL integrated | 081a19a | 前端阅读、reading.py、http.py、api.urls、0056 | 首访自动抓取移除/代码保真；个人已读API/UI及0056已实现；580前端与75后端组合通过；显式修复待T08，浏览器待T27 |
| CI基线修复 | 主调度 | integrated | 7f79671 | 两个旧测试文件 | 10专项通过；registry夹具与HOLDER SIGTERM竞态最小修复，CI待跑 |
| T24 | 主调度 | running / 真实副本 blocked | 集成分支 | migration_inventory.py、scripts/rss-inventory.py、自有测试 | 57静态来源；6专项通过；显式SQLite副本只读hash导出器已实现；真实副本和覆盖处置待补 |

其余可开发：T03及后续T09/T14/T17/T19/T20/T21；根据接口与空闲名额滚动派发。T18 网关单独门禁。T26 候选→隔离演练→封存，须含发布schema；T27真实来源/浏览器待后续。T29/T30/T31/T33实际生产与退出阶段未授权，禁止提前激活删除。

## 验证环境与证据规则

Python 3.12 独立环境 `/tmp/newshub-rss-coordinator-venv`；测试指定独立合成DB路径。Agent各自隔离环境/DB/端口，主调度做跨模块验证，不重复专项。CI逐集成批次核对。T00真实引擎及T02隔离镜像已有证据；真实副本/浏览器/两库恢复尚无通过证据。

分支保护查询 GitHub API 返回403（账号/仓库计划限制），保护规则 UNKNOWN；仍执行仓库CI，不推断无要求。

## 批次证据

- 开发草稿PR：https://github.com/CoderLambert/news-aggregator/pull/78，规划PR #77未改。
- Python3.12 T00：`/tmp/newshub-rss-t00-py312/bin/python ops/rss/T00/run_live.py`，13 passed/18.49s；日志 `/tmp/newshub-rss-t00-py312.log`，仅新建临时项目，自动清理。
- 首次全后端批次：1182 passed，1 failed，然后中止卡住的合成下载测试。失败/等待均因旧离线夹具仍依赖真实DNS；日志 `/tmp/newshub-rss-b1-baseline-tests.log`。生产校验未修改，1c9e259修复受控DNS并给模拟启动等待上限，相关10测试通过。
- 核心schema合入后批次重跑：`RUN_MAIN=true DJANGO_DB_PATH=/tmp/newshub-rss-coordinator-unused.sqlite3 PYTHONPATH=backend:crawler /tmp/newshub-rss-coordinator-venv/bin/python -m pytest -q tests/ backend/api/tests/ scripts/deploy/tests/`，1846 passed、13 live skipped，107.80s、退出0；日志 `/tmp/newshub-rss-b1-integration-tests.log`。测试含核心schema/转换/静态盘点/T00离线，T16功能后合入另补专项。
- PR78在5ae2c44的前端与后端release gates均通过（含image及隔离G1 smoke）；不将旧head结果当后续代码证明。
