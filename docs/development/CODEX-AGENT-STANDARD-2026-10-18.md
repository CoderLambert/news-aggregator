# NewsHub Codex Agent 工程规范 V1.1

审计基线：`main@40728f035eda10f3319a9d16da4803851a6503e5`，2026-10-18。此版本将 PR #108 的草案落实为仓库规则、三个按需 Skills 和确定性的结构检查。**文件交付、CI 通过、Codex 本机加载及开发收益是四项不同的验收；以 PR 的最新实测证据为准。**

## 1. 复审结论与调整

| 草案遗漏/风险 | 本次处理 |
|---|---|
| 子目录 AGENTS 可能没有加载；根目录启动后 `cd` 被误当重新加载 | 根规则明确按任务读取子规则；提供根/子目录和 Worktree 的真实会话验收 |
| 根目录 `tests/`、部署测试、RSS 测试不继承对应业务目录规则 | 增加 `tests/AGENTS.md`、`scripts/deploy/AGENTS.md`；根目录列明跨目录适用映射 |
| 只描述规范，没有检验规则本身 | 新增标准库结构检查及负例测试，检查缺失/超长文件、Skill 元数据、断链、越界链接和 Markdown 围栏 |
| 校验仅跑在后端时，前端独立修改规则可能漏检 | 在既有前端快速预检调用检查器；后端沿用现有 unittest discovery，不新建 Job |
| 多份 AGENTS/Skill/长文档重复复制约束，逐渐相互冲突 | 实际规则文件为操作入口，本说明只解释架构、边界、使用与验收；不再复制全部模板 |
| “T02/T03 未完成”等阶段状态容易成为永久禁令 | 固化“未验证绑定不得调用”的不变量；当前完成状态只标注审计日期，允许按对应任务正式推进 |
| 局部测试没有明确解释 `.env`、共享 Worktree 资源风险 | 要求无真实凭据的隔离测试环境；Worktree 不等于数据库/端口/缓存隔离 |
| Skill 容易在所有任务中触发，或把交接解释为自动提交/部署许可 | 精简触发说明、排除普通查询/文档小改；交接 Skill 不产生新的写入、合并或付费授权 |

不引入 MCP、向量库、Hooks、自定义 Agent 平台、模型锁定或用户级 Codex 配置。不替换原测试框架、包管理器、CI 分流和 Runner。

## 2. 当前模块与架构

```text
React / Vite
  Router(URL) + TanStack Query(server state) + Zustand(client preferences)
          │ Session / CSRF / typed JSON / SSE
Django / DRF + PublicPolicy / capabilities / owner checks
          ├─ 新闻/来源/频道/收藏/阅读 → SQLite WAL
          ├─ RSS operations/control/sync → Miniflux adapter（外部引擎）
          ├─ 内容版本/ACL/写入围栏 → detail / translation / research / TTS
          ├─ BYOK → UserAIConnection / epoch / worker fence → 明确模型与用途绑定 → LiteLLM
          ├─ ChatGPT Subscription → 独立授权、选择与任务链
          ├─ 搜索索引 → 可重建的派生状态
          └─ 镜像/部署/CI → 双 Runner、pytest 混合执行、G1
```

这是代码职责图，不是所有目标已上线的声明。NewsHub 主库是 SQLite；Miniflux 所用 PostgreSQL 不是已替换 NewsHub 主库的证据。旧 Scrapy、旧正文提取和 Worker 仍有兼容职责；不可擅自扩建，也不能在切源验收前直接删除。

| 模块 | 真实入口（仓库相对路径） | 必须保持的边界 |
|---|---|---|
| 权限/模式/入口 | `backend/api/urls.py`、`backend/api/public_policy.py`、`backend/newsaggregator/settings.py` | owner、Session/CSRF、read-only 与能力开关；UI 隐藏不等于鉴权 |
| 新闻存储/身份 | `backend/api/models.py`、`backend/api/services/news_ingestion.py`、`backend/api/services/article_identity.py` | 幂等、主来源、发布时间、短事务和真实正文 |
| RSS 控制与订阅 | `backend/api/rss/engine.py`、`runtime.py`、`operations.py`、`subscriptions.py`、`opml.py` | 引擎身份不可重绑；共享 Feed 不共享私人权限；未知结果需对账 |
| RSS 内容与同步 | `backend/api/rss/sync.py`、`content_store.py`、`access.py` | 版本/写令牌/ACL；网络结果不自行授予写权限 |
| 旧采集兼容 | `crawler/`、`backend/api/services/article_fetcher/`、`backend/api/services/full_content_worker.py` | 仅修授权的兼容与回归，退役依原合同 |
| BYOK | `backend/api/ai_connection_models.py`、`ai_connection_views.py`、`backend/api/services/ai_credentials.py`、`ai_worker_fencing.py`、`ai_execution.py`、`ai_gateway.py` | 加密、owner/epoch/version、模型用途显式绑定、禁隐式站点 Key 回退 |
| ChatGPT Subscription | `backend/api/services/chatgpt_subscription.py`、`chatgpt_subscription_jobs.py`、`backend/api/subscription_views.py` | OAuth/Token/模型选择与 BYOK 分离，不能交叉使用用户凭据 |
| 翻译/消费 | `backend/api/services/shared_translations.py`、`translation_jobs.py`、`stored_readers.py`、`backend/api/translation_sse.py` | 公开共享与私人结果隔离，正文 hash/租约/真实终态 |
| 研究 | `backend/api/services/research/agent_loop.py`、`job_manager.py`、`access.py`、`backend/api/research_views.py` | 持久事件、授权重放、限额、取消与恢复 |
| 智能频道 | `backend/api/services/channel_topics.py`、`channel_grouping.py`、`channel_ai.py`、`backend/api/smart_channel_views.py` | 来源可信证据版本化、人工优先、私人分组、GET 无隐性推理 |
| 前端 | `frontend/src/App.tsx`、`services/`、`context/`、`stores/`、`features/rss/` | URL/Query/Zustand 分工；统一 DTO/CSRF/Abort；viewer 切换阻断旧结果 |
| CI/交付 | `.github/workflows/ci.yml`、`ops/ci/change_scope.py`、`benchmark-xdist.sh`、`scripts/deploy/` | 触发过滤与 Job 分流，串行敏感模块、动态身份门禁、镜像/G1 |

表中同一行的短路径相对于该行已写出的目录；命令必须使用完整实际路径。源码变更后更新入口，不把旧清单当绝对权威。

### 审计日的迁移状态

T01 连接与通用 Worker 撤销围栏已有代码和合成回归；T02/T03 未绑定时 `ai_execution.py` 拒绝个人业务调用。这不是模型业务已端到端启用。推进 T02/T03 时按原合同补全并更新证据，不恢复 `UserProviderCredential` 旧运行路径。

AG-01 的来源身份/可信主题证据已实现；其余 AG 项不能只因文件或测试存在就标完成。RSS 已有 Miniflux 适配与同步/订阅，但最终生产切源、旧链退出和真实来源质量有单独验收。保留原 RSS T00–T36、BYOK T00–T14/T00-G 和 AG-00–AG-07 编号，不建立重复任务体系。

当前任务唯一入口：`docs/plans/FEATURE-DEVELOPMENT-2026-10-17.md`；2026-10-17 的状态快照移入 `docs/plans/archive/FEATURE-DEVELOPMENT-SNAPSHOT-2026-10-17.md`，其旧“当前/下一批”文字不具执行权。RSS `ARCHITECTURE.md`/`TASKS.md`、BYOK T01 Worker 合同及 AG-01 合同/Issue #55 保留目标定义。当前源码与合同分别回答“已实现”和“应该实现”。

## 3. 实际配置层次

| 文件 | 作用 |
|---|---|
| `AGENTS.md` | 简短全局约束、模块导航、授权、验证和 Code Review Rules |
| `backend/AGENTS.md` | Django/SQLite/API/AI/网络与模型边界 |
| `frontend/AGENTS.md` | React 状态、viewer、DTO/CSRF/SSE、验证 |
| `backend/api/rss/AGENTS.md` | RSS 引擎/正文/同步/订阅的专属边界 |
| `tests/AGENTS.md` | 隔离夹具、负例、并发、证据；显式供其他测试目录复用 |
| `scripts/deploy/AGENTS.md` | 部署脚本与合成测试边界，不隐含生产权限 |
| `ops/ci/AGENTS.md` | CI 唯一配置、Runner 安全、覆盖与 Agent 结构检查 |
| `.agents/skills/newshub-impact-analysis/SKILL.md` | 高风险或跨模块改动前的范围分析 |
| `.agents/skills/newshub-verify/SKILL.md` | 改动后的实际验证、完整差异、证据归属 |
| `.agents/skills/newshub-pr-handoff/SKILL.md` | 已授权的 PR 审查/交接，不自动获得写入权限 |

### 加载与上下文预算

Codex 按启动目录发现祖先规则；从仓库根启动，不应假设所有深层规则已加载，shell `cd` 也不是自动重载。根文件指示在修改对应模块前明确读取所需规则。用户/管理员/系统指令及本地 `AGENTS.override.md`、配置上限可能改变实际加载结果；本仓库不修改这些配置。

本项目结构门禁限制根规则 6 KiB、各模块规则 4 KiB、各 Skill 4 KiB、仓库祖先规则链 16 KiB，为用户级指令留余量。这是**工程预算，不是 Token 统计，也不保证 Codex 实际未截断**。Codex 默认 `project_doc_max_bytes` 为 32 KiB，但用户可改变它；以实际会话为准。

Skills 放在根 `.agents/skills/`，供根与子目录会话发现。三个 Skill 只包含指令，无额外模型、MCP、Shell Hook 或进程。明确 `$skill-name` 可以调用；隐式触发取决于描述与模型判断，不是静态测试可以证明的行为。

为无需新依赖地检查 Skill 元数据，本项目采用合法 YAML 的受限写法：`name: plain-kebab-case` 和 `description: "JSON-quoted one-line string"` 两个字段，拒绝重复/额外字段或多行描述。检查器不是通用 YAML 解析器；需要扩展元数据时先调整校验与负例，或明确采用已有成熟解析库。

## 4. 规则与 CI 如何配合

CI 仍只有既有两级分流；**不改路径白名单、路由分类或 Job 调度**。Agent 只读取这些配置，不再维护另一套文件分类表。

本次只在既有 `Fast cross-stack syntax preflight` 加入 `python3 ops/ci/agent_rules.py`。后端原有 `unittest discover -s ops/ci/tests -p 'test_*.py'` 自动发现新回归。这样前端单独修改 `frontend/AGENTS.md` 也能做规则结构检查，不需要重新启动后端测试。

根 `AGENTS.md`、`.agents/**`、CI 文件会按现有规则双跑；子目录规则沿用其路径分类。纯 `docs/**` 文件仍由 GitHub 触发器直接忽略；更改本说明不等于修改实际生效规则。未来若将运行配置放进 docs，须先修改忽略策略。

未知路径或脚本内可捕获的 diff 异常保守双跑；**checkout、路由测试或 changes Job 整体失败仍是 CI 失败，不是已成功回退**。GitHub 大差异路径筛选及 required-check Pending 的已有边界仍按 `ops/ci/change-routing.md` 管理。

路径调度不是完整依赖图。更改响应行为、权限、正文/SSE 协议即使没有改 URL/Serializer 文件，也必须检查另一端消费者；需要时在当前授权内执行手动全量验证，不削减检查或把跳过写为 PASS。

## 5. 开发验证入口

CI 工具链以 workflow/lockfile 为准，审计日为 Python 3.12 / Node 22。不要将用户 Omarchy 的较新 Python/Node 直接当 CI 一致环境，不自动切换系统版本或覆盖共享缓存。

**执行下列后端命令前**：使用无真实 `.env`/Token/Key 的隔离工作树与测试数据库，检查环境来源但不打印秘密。Django development 模式仍可能读取 `.env`；`RUN_MAIN=true` 只影响特定启动路径，不是凭据或数据库隔离。Worktree 的 DB、端口、Compose 项目、venv/node_modules 也要独立管理。

```bash
# 在仓库根，使用已准备的兼容测试环境；按任务替换为真实相关测试
PYTHONPATH=backend:crawler RUN_MAIN=true \
  backend/venv/bin/python -m pytest -q \
  backend/api/tests/test_ai_connections.py \
  backend/api/tests/test_ai_worker_fencing.py

# 前端专项：不使用 watch 模式
(cd frontend && npm run typecheck && npm run lint && \
  npm run test:run -- tests/pages/AIModelSettingsPage.test.tsx tests/services/aiConnectionsApi.test.ts)

# Agent 结构检查：只用标准库，无模型/网络/数据库调用
python3 ops/ci/agent_rules.py
python3 -m unittest discover -s ops/ci/tests -p 'test_agent_rules.py'
```

| 任务 | 首选已有回归（按实际影响扩展） |
|---|---|
| AI 连接/凭据 | `backend/api/tests/test_ai_connections.py`、`test_ai_worker_fencing.py`、`test_byok_response_terminal.py`；前端 AI 设置/服务测试 |
| RSS | `backend/api/tests/rss/test_engine_adapter.py`、`test_subscriptions.py`、`test_operations.py`、`test_body_commit.py`、`test_access_contract.py`、`test_sync_reconciliation.py` |
| 智能频道 | `backend/api/tests/test_ag01_source_metadata.py`、`test_smart_channel_workspace.py`；`frontend/tests/pages/SmartGroupingWorkspace.flow.test.tsx` |
| 翻译/研究 | `backend/api/tests/test_shared_translations.py`、`test_translation_sse.py`、`test_research_recovery.py`、`test_research_tool_cancellation.py` |
| UI | `frontend/tests/pages/`、`frontend/tests/components/`、`frontend/tests/services/` 对应文件；发布 UI 需 build |
| CI/发布 | `ops/ci/tests/`、`scripts/deploy/tests/` 及完整适用 CI，禁止 mock 代替 G1 |

后端全量由 `ops/ci/benchmark-xdist.sh` 管理 `tests/`、`backend/api/tests/`、`scripts/deploy/tests/` 三根目录，保留串行敏感模块、两 worker 和动态收集/执行/JUnit 对账。通过数与跳过策略以当前审计代码为准，不在 Agent 中写死数字。

`README.md`、`TESTING.md`、`scripts/run_tests.sh` 的旧入口仍有范围缺口；**本次没有重构测试脚本，也没有新增 `--scope` 参数**。局部测试不是全量或发布验收。环境缺失应报告 NOT_RUN，并使用已有 CI 完成可执行的检查，不伪造结果。

## 6. 工作、复审与交付合同

按任务工作，不强制每次小改动产生长计划。最多两个独立写入目标；共享模型/路由/迁移/锁文件/夹具单写者。任务差异必须包括整个 PR、已暂存、未暂存、未跟踪、删除和重命名文件；只看 `HEAD^` 或 `origin/main...HEAD` 会漏掉本地新修改。

审查优先实际缺陷：owner/CSRF、凭据、数据版本/租约/epoch、内容授权重读、SSE 终态、SSRF/预算、迁移与回滚。沿用成熟服务；不机械禁止局部重构，也不为风格喜好扩大改动。改变测试期望须有明确的行为变更依据与回归，不能只为绿灯。

交付至少包含：原任务与范围、base/head/dirty 状态、受影响合同、实际命令与结果、CI URL/测试 SHA、遗留风险、回滚和独立验收边界。只读审查不授权 commit/push/merge；授权开发不自动授权生产或付费调用。合并必须处于当前授权并核对选中门禁与最新 base，不根据“mergeable”或旧 SHA 的成功决定。

SKIPPED、NOT_RUN、BLOCKED 与 PASS 分开。G1/受控 Proxy 是合成环境；真实厂商、多实例压力、真机/浏览器人工 UAT、生产切源与部署各自验收。代码 revert 不自动回滚数据库。

## 7. 配置验收与使用

结构检查会验证文件存在/类型/UTF-8/体积、**额外未登记规则与 Skills**、Skill 唯一字段与名称、局部链接及 Markdown 围栏、祖先链预算；测试另覆盖负例和现有 CI 路由。它**不能**证明模型服从规则、隐式正确触发、开发正确率或节省 Token。

本机更新到包含这些文件的分支后，在真实 Codex CLI 中做只读验收；保留个人模型和权限配置，不添加绕过审批参数。规则变更后开启新会话：

```bash
# 任意已有干净工作树内；确认 checkout 的是包含新规则的分支/提交
codex "只读：列出本会话生效规则来源，并说明修改 frontend/src/pages/NewsList.tsx 前还需读取哪些规则。不修改文件。"
codex --cd backend/api/rss "只读：列出根、backend、RSS 规则的来源，并说明 RSS 写入与网络事务的边界。"
```

无需模型请求可使用 `codex -C <repo-or-subdir> debug prompt-input` 比较根目录、frontend、backend/api/rss 的祖先规则及 Skill 元数据是否注入/被发现；不要把完整 prompt 输出保存到共享日志。该检查只证明提示构建，**不证明自动选择 Skill 或实际遵守**。在 Codex 内可用 `/skills` 查看，或明确输入 `$newshub-verify`、`$newshub-impact-analysis`、`$newshub-pr-handoff`。项目根与子目录应都能发现根 Skills；若缺失，检查真实 CLI 版本、目录、同名 Skill、用户配置与 override，而非覆盖用户设置。

| 只读/可回滚验收情景 | 期望 |
|---|---|
| 仅改 NewsList 样式 | 读取前端规则，选相关组件测试，不要求全部 Skills/后端本地全跑 |
| 给 BYOK 加模型绑定 | 核对 T01→T02/T03 当前合同与调用方，不隐式站点 Key 回退 |
| 改 RSS 同步或其外层测试 | 读取 backend+RSS+测试规则，检查身份/内容/权限与对账 |
| 仅修改 README/docs | 不改业务，不声称运行 CI；适当做内容/链接核对 |
| 修改前端 AGENTS | 保留原单前端 Job 分流，但快速结构检查必须执行 |
| 交接 PR | 明确 head/base、选中门禁、未运行项；不未经授权提交或部署 |
| 工作树有用户未提交改动 | 保留这些改动，隔离本任务，不 reset/clean |
| 研究 SSE 恢复 | 覆盖失效权限/版本/取消与真实终态，不能只测正常返回 |

应在实际 Git Worktree 再验证一次；无需重装模型/依赖。用户级规则可能占用上下文或与项目约定冲突，需要显示来源后人工判断；不要悄悄删除它们。

## 8. 维护与回滚

实际规则文件是操作约束的唯一正文，不将全文复制进本说明或其他 Skill。修改架构时同步相应规则与相关测试；阶段状态在当前任务合同更新。常规小改动不要求修改 AGENTS。

配置校验器会扫描项目源码中的 `AGENTS.md` / `AGENTS.override.md` 和 `.agents/skills/` 目录，并拒绝未登记的新增规则或 Skill；它排除依赖与生成目录，但不排除未知业务目录。新增合法规则/Skill 时更新 `ops/ci/agent_rules.py` 的项目允许清单与回归测试；只有确实需要时再扩展元数据格式。纯说明留在 docs，执行规则与代码不可伪装成可忽略文档。

回滚恢复/移除本 PR 的规则、Skills、检查器、测试及前端新增预检行，重新启动 Codex。不会触及用户 `~/.codex/config.toml`、认证/MCP、业务数据或生产服务。GitHub PR/CI 证据记录当前提交，文档不把待验证项提前标 PASS。

## 9. 依据

已核对当前源码/测试/CI 及原项目合同（PR #104–#107、审计基线如上）。旧规范中的模板和分批实施建议已由本次实际文件替代；不会另开重复的 Agent 平台规划。

官方加载与 Skills 说明（2026-10-18 核对；旧 developers 链接可能跳转至 ChatGPT Learn）：
- https://developers.openai.com/codex/guides/agents-md
- https://developers.openai.com/codex/skills/

这些官方规则描述产品能力，不代替本机加载测试；CI 结构检查也不等于开发效率已经提升。

## 10. 选择性吸收 pstack 的工程方法（2026-10-18）

上游参考：[pstack 镜像](https://github.com/backnotprop/pstack)（其 `MIRROR.md` 说明来源于 [Cursor pstack](https://github.com/cursor/plugins/tree/main/pstack)；本次参照镜像 `v0.15.25` 的 [Blast Radius](https://github.com/backnotprop/pstack/blob/main/skills/blast-radius/SKILL.md)、[TDD](https://github.com/backnotprop/pstack/blob/main/skills/tdd/SKILL.md) 和 [Benchmark Checklist](https://github.com/backnotprop/pstack/blob/main/skills/benchmark-checklist/SKILL.md) 思路）。

**范围：仅修改现有两份 NewsHub Skills 的工作步骤，不复制上游文件、脚本、Playbook、模型角色配置或其 Agent 框架。** 不增加新项目 Skills、依赖、Hook、MCP、CI Job 或默认模型。保留仓库自己的 Owner/CSRF、正文版本、credential_epoch、Miniflux、SQLite 事务、真实/合成验证边界；项目实际规则始终优先于外部通用建议。

| 场景 | NewsHub 内的触发规则 | 应交付的证据 | 不需要做什么 |
|---|---|---|---|
| 跨模块、权限、版本、Worker 等高风险变更 | `newshub-impact-analysis` 列出 1–2 个真正决定安全性的可证伪假设，并追踪 DTO/DB/重试/跨端消费者 | 源码路径、已有测试结果及最小可执行负例；`PROVEN` / `SOURCE_ONLY` / `UNPROVEN` / `NOT_RUN` | 只读方案阶段不为了“证明”擅自修改文件或调用生产 |
| 廉价且确定可复现的 Bug 修复 | `newshub-verify` 记录修复前失败、修复后通过；否则说明为什么没有修复前证据，采用最接近的可安全执行的回归 | 相同缺陷的 red/green、实际命令、退出码 | 不为小问题强造昂贵的全链路测试或模拟错误结论 |
| 宣称响应时间、负载或资源优化 | `newshub-verify` 先定义用户侧指标及基线，核对实际工作量、错误率、冷热缓存与真实瓶颈，用可比的多轮样本验证 | 环境/样本量、median/range、错误计数、端到端收益；无法核实则 `INCONCLUSIVE` | 不对生产做压力测试，也不把缓存偶然命中或失败快速返回记为性能提升 |

这三项均按**实际任务需要**启用。普通单组件小改动维持现有最小测试策略，GitHub Actions 调度仍由 `.github/workflows/ci.yml` 与 `ops/ci/change_scope.py` 唯一决定。结构校验器只验证 Skills 格式，不能证明模型按建议执行；后续可用对照任务核查代码差异与测试证据，不以输出篇幅或 Token 猜测效果。
