# RSS 迁移开发执行状态

2026-10-16。用户已通过独立会话交接授权修订规划的隔离实现、任务分支提交推送和开发 PR；不授权 main 合并、生产切源、停服务或部署。文档中的历史 REVIEW_REQUIRED/仅规划授权说明由本次开发授权更新，生产门禁仍有效。

基线：PR #77 head `17d48915bbacd6a448578c64676a6dac4c2f263e`，main `878b690`。集成分支 `feat/rss-engine-integration-20261016`，worktree `/tmp/newshub-rss-integration-20261016`。原工作区数据库改动及两份未跟踪文档保留。

状态语义：ready 可开发；running 实现中；blocked 仅列具体受阻证据；review 待审；integrated 已集成；accepted 已满足该任务验收。integrated 不代表生产验收。

| 任务 | 负责人 / 模型 | 状态 | 分支 / SHA | 独占文件 / 依赖 | 证据、阻塞与下一步 |
| --- | --- | --- | --- | --- | --- |
| T00 | rss_t00 / gpt-6.1-sol high | integrated / A4 partial | 7ca5ff1→72ab3a1 | tests/rss_engine_contract、ops/rss/T00 | 离线16+真实13通过；主调度Python3.12复跑13通过；公网HTTPS/DNS/网关门禁保留 |
| T06 | rss_t06 / gpt-6.1-sol high | integrated | ebf8eac→5ae2c44 | rss/content.py、转换测试、requirements转换依赖 | 30专项通过；主调度审查；浏览器/T07组合待验 |
| T16 | rss_t16 / gpt-6.1-sol high | running | task/rss-T16-directory / 基线17d4891 | directory.py、directory_models.py、models单行、0052 | DDL 81ad293→集成d0472c1；全链迁移/无漂移通过；T05接0053 |
| T05 | rss_t05 / gpt-6-astra high | running / schema integrated | 35a7d29→df93a48 | rss/models.py、0053/0054、自有测试 | 空库迁移/无漂移通过；主调度独立审查政策无漂移；专项待交付 |
| T04 | rss_t04 / gpt-6-astra high | running | task/rss-T04-engine-adapter / 72ab3a1 | rss/engine.py、SDK依赖、自有测试 | 固定SDK1.1.6；C03 DTO/持久修复/配置/响应限制 |
| T02 | 待分配 / gpt-6.1-sol high | ready | task/rss-T02-runtime / 1c9e259 | Dockerfile、Compose、AppConfig、轻量依赖 | T00固定digest已就绪，首个名额接续 |
| CI基线修复 | 主调度 | integrated | 7f79671 | 两个旧测试文件 | 10专项通过；registry夹具与HOLDER SIGTERM竞态最小修复，CI待跑 |
| T24 | 主调度 | running / 真实副本 blocked | 集成分支 | migration_inventory.py、scripts/rss-inventory.py、自有测试 | 57静态来源；6专项通过；显式SQLite副本只读hash导出器已实现；真实副本和覆盖处置待补 |

其余可开发：T02/T04/T24；模型就绪后滚动 T07/T11/T08/T03/T25，再组合 T09/T13/T14/T17/T19/T20/T21。T18 网关单独门禁。T26 候选→隔离演练→封存，须含发布schema；T27真实来源/浏览器待后续。T29/T30/T31/T33实际生产与退出阶段未授权，禁止提前激活删除。

## 验证环境与证据规则

Python 3.12 独立环境 `/tmp/newshub-rss-coordinator-venv`；测试指定独立合成DB路径。Agent各自隔离环境/DB/端口，主调度做跨模块验证，不重复专项。CI待开发PR后核对全部必需检查。真实引擎/副本/浏览器/两库恢复尚无通过证据。

分支保护查询 GitHub API 返回403（账号/仓库计划限制），保护规则 UNKNOWN；仍执行仓库CI，不推断无要求。

## 批次证据

- 开发草稿PR：https://github.com/CoderLambert/news-aggregator/pull/78，规划PR #77未改。
- Python3.12 T00：`/tmp/newshub-rss-t00-py312/bin/python ops/rss/T00/run_live.py`，13 passed/18.49s；日志 `/tmp/newshub-rss-t00-py312.log`，仅新建临时项目，自动清理。
- 首次全后端批次：1182 passed，1 failed，然后中止卡住的合成下载测试。失败/等待均因旧离线夹具仍依赖真实DNS；日志 `/tmp/newshub-rss-b1-baseline-tests.log`。生产校验未修改，1c9e259修复受控DNS并给模拟启动等待上限，相关10测试通过。
- 核心schema合入后批次重跑：`RUN_MAIN=true DJANGO_DB_PATH=/tmp/newshub-rss-coordinator-unused.sqlite3 PYTHONPATH=backend:crawler /tmp/newshub-rss-coordinator-venv/bin/python -m pytest -q tests/ backend/api/tests/ scripts/deploy/tests/`，进行中，日志 `/tmp/newshub-rss-b1-integration-tests.log`。
- PR78在5ae2c44的前端CI两次成功，后端release gates仍进行中；不将旧head结果当后续代码证明。
