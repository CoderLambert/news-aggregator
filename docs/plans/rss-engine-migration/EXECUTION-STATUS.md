# RSS 迁移开发执行状态

2026-10-16。用户已通过独立会话交接授权修订规划的隔离实现、任务分支提交推送和开发 PR；不授权 main 合并、生产切源、停服务或部署。文档中的历史 REVIEW_REQUIRED/仅规划授权说明由本次开发授权更新，生产门禁仍有效。

基线：PR #77 head `17d48915bbacd6a448578c64676a6dac4c2f263e`，main `878b690`。集成分支 `feat/rss-engine-integration-20261016`，worktree `/tmp/newshub-rss-integration-20261016`。原工作区数据库改动及两份未跟踪文档保留。

状态语义：ready 可开发；running 实现中；blocked 仅列具体受阻证据；review 待审；integrated 已集成；accepted 已满足该任务验收。integrated 不代表生产验收。

| 任务 | 负责人 / 模型 | 状态 | 分支 / SHA | 独占文件 / 依赖 | 证据、阻塞与下一步 |
| --- | --- | --- | --- | --- | --- |
| T00 | rss_t00 / gpt-6.1-sol high | running | task/rss-T00-engine-contract / 基线17d4891 | tests/rss_engine_contract、ops/rss/T00 | Docker可用；仅新建隔离引擎，验证实际合同与digest |
| T06 | rss_t06 / gpt-6.1-sol high | running | task/rss-T06-content / 基线17d4891 | rss/content.py、转换测试、requirements转换依赖 | 纯转换；无网络；输出hash/version接口已约定 |
| T16 | rss_t16 / gpt-6.1-sol high | running | task/rss-T16-directory / 基线17d4891 | directory.py、directory_models.py、models单行、0052 | DDL 81ad293→集成d0472c1；全链迁移/无漂移通过；T05接0053 |
| T05 | 待分配 / gpt-6-astra high | ready | 待创建 | 核心models/0053 | 首个空闲槽位优先启动 |
| CI基线修复 | 主调度 | integrated | 7f79671 | 两个旧测试文件 | 10专项通过；registry夹具与HOLDER SIGTERM竞态最小修复，CI待跑 |
| T24 | 主调度 | running / 真实副本 blocked | 集成分支 | migration_inventory.py、scripts/rss-inventory.py、自有测试 | 57静态来源；5专项通过；真实副本导出和覆盖处置待补 |

其余可开发：T02/T04/T24；模型就绪后滚动 T07/T11/T08/T03/T25，再组合 T09/T13/T14/T17/T19/T20/T21。T18 网关单独门禁。T26 候选→隔离演练→封存，须含发布schema；T27真实来源/浏览器待后续。T29/T30/T31/T33实际生产与退出阶段未授权，禁止提前激活删除。

## 验证环境与证据规则

Python 3.12 独立环境 `/tmp/newshub-rss-coordinator-venv`；测试指定独立合成DB路径。Agent各自隔离环境/DB/端口，主调度做跨模块验证，不重复专项。CI待开发PR后核对全部必需检查。真实引擎/副本/浏览器/两库恢复尚无通过证据。

分支保护查询 GitHub API 返回403（账号/仓库计划限制），保护规则 UNKNOWN；仍执行仓库CI，不推断无要求。
