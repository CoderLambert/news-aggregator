# NewsHub Codex Agent 工程规范（设计草案 V1）

> 仓库：`CoderLambert/news-aggregator`  
> 审计代码基线：`main@40728f035eda10f3319a9d16da4803851a6503e5`（2026-10-18）  
> 状态：**PROPOSED / 仅文档，不代表已安装 Agent 规则或已完成新的测试**。  
> 本规范先指导如何配置。正式投用时应在独立 PR 添加指令文件与必要回归，不直接改业务代码、生产数据或既有 Runner。

## 1. 设计目标和不做事项

NewsHub 已具有 Django、React、RSS 适配、BYOK、研究/翻译、专项测试和自托管 CI。Agent 的主要职责是定位准确的修改边界、复用既有服务与约束、选择适当验证并提交可审查证据。

必须达成：
1. 读取**当前仓库代码和实际测试**，而不是依据旧 README、老分支或历史任务完成率猜测现状。
2. 每批默认最多**两个独立写入目标**；依赖同一模型、URL、迁移或公共测试夹具的目标不得同时写入。并行探索/只读复审可独立进行。
3. 业务实现、验证、CI 与发布验收分层，严禁把局部检查成功写成已上线、已调用真实厂商或完成全部验收。
4. 不为已有功能再做一套缓存、鉴权、网络安全、路由、文章身份或 CI。
5. Agent 规则只提供**指导**；真正强制的检查由 pytest、Vitest、GitHub Actions 和人工/生产放行完成。

不在首轮添加：Serena/grepai/MCP、另一个 Agent 编排平台、额外数据库、自动提交到生产、全局覆盖用户 `~/.codex/config.toml`、强制对每一处小改动调用多 Agent。

## 2. 当前真实模块架构

### 2.1 逻辑依赖关系

~~~text
React 19 / Vite 8 / TanStack Query / Zustand
      | 受控 API、Session/CSRF、JSON 与 SSE
      v
Django 6 / DRF 入口与 PublicPolicy/Feature Gate
      |
      +-- 新闻/频道/收藏/阅读 -> Django models / SQLite
      +-- RSS 订阅、同步和正文 -> api/rss/* -> Miniflux adapter（引擎拥有采集/提取）
      +-- AI 连接 -> UserAIConnection + AES-GCM + epoch/Worker fence
      +-- AI 调用 -> 明确模型/用途绑定完成后经受信 LiteLLM 网关
      +-- ChatGPT Subscription -> 独立 OAuth/Responses 调用链
      +-- 研究/翻译/朗读 -> owner-scoped / durable task / SSE / 内容版本
      +-- 本地搜索 -> 搜索索引作为可重建的派生状态
      +-- 管理/运维 -> 独立 worker、Compose、CI、G1 smoke
~~~

**状态限定：** 此图体现现有代码和目标职责，**不意味着** RSS 最终生产切源、旧 Scrapy 退出、T02/T03 绑定或所有模型业务 Worker 端到端上线已经完成。NewsHub 当前 Django 主数据库设置默认仍是 SQLite（WAL），Miniflux/PostgreSQL 是 RSS 引擎目标栈，不要混为一谈。

### 2.2 模块入口和职责（实际文件）

| 业务域 | 查找入口 | 写入/依赖边界 | 典型测试 |
|---|---|---|---|
| 路由/全站权限 | `backend/api/urls.py`、`backend/newsaggregator/settings.py`、`backend/api/public_policy.py` | Session/CSRF、站点 read-only、能力开关、用户权限；不得默许绕过 | `backend/api/tests/test_account_security.py`、`test_public_policy.py` |
| 新闻/文章来源 | `backend/api/models.py`、`backend/api/services/news_ingestion.py`、`article_identity.py` | 文章身份、幂等、主来源、发布时间及正文事实，不在事务里进行网络调用 | `backend/api/tests/test_news_ingestion.py`、`tests/crawler/test_ingestion_identity.py` |
| RSS、订阅与 OPML | `backend/api/rss/engine.py`、`runtime.py`、`subscriptions.py`、`operations.py`、`opml.py` | 共享物理 Feed、私有订阅、引擎身份、任务对账及失败恢复 | `backend/api/tests/rss/test_engine_adapter.py`、`test_subscriptions.py`、`test_opml_import.py` |
| RSS 文章与同步 | `backend/api/rss/sync.py`、`content_store.py`、`access.py` | 独立正文版本/写入围栏、ACL、无网络 DB 事务、同步失败幂等恢复 | `backend/api/tests/rss/test_body_commit.py`、`test_sync_reconciliation.py`、`test_access_contract.py` |
| 旧采集兼容 | `crawler/`、`backend/api/services/article_fetcher/`、`full_content_worker.py` | 正在迁移的兼容路径；不在未完成的退役门禁前删，亦不新投资旧爬虫 | `tests/crawler/`、`backend/api/tests/test_full_content_worker.py` |
| BYOK 用户 AI 连接 | `backend/api/ai_connection_models.py`、`ai_connection_views.py`、`services/ai_credentials.py` | 唯一 `UserAIConnection`，密文和 owner/epoch/version、禁用及撤销围栏 | `test_ai_connections.py`、`test_ai_worker_fencing.py` |
| BYOK 网关/执行 | `services/ai_registry.py`、`ai_gateway.py`、`ai_execution.py`、`ai_worker_fencing.py` | 使用受信 LiteLLM、明确绑定和终态；T02/T03 前保持 fail-closed | `test_byok_response_terminal.py`、`test_ai_worker_fencing.py`、`tools/byok_t00_probe/` |
| ChatGPT Subscription | `services/chatgpt_subscription.py`、`chatgpt_subscription_jobs.py`、`backend/api/subscription_views.py` | 与 BYOK 不同的授权/凭据路径；保持用户、任务和模型选择隔离 | `test_chatgpt_subscription.py`、`test_subscription_recovery.py` |
| 翻译与正文消费 | `backend/api/services/shared_translations.py`、`translation_jobs.py`、`stored_readers.py`、`backend/api/translation_sse.py` | 共享公开译文与私有译文隔离、正文版本一致、失效租约不得提交 | `test_shared_translations.py`、`test_translation_jobs.py`、`test_translation_sse.py` |
| 研究与聊天 | `services/research/agent_loop.py`、`job_manager.py`、`access.py`、`backend/api/research_views.py` | 只重放授权且当前有效的证据；持久事件、SSE 限额/取消/恢复 | `test_research_recovery.py`、`test_research_evidence.py`、`test_research_tool_cancellation.py` |
| 智能频道分类 | `services/channel_topics.py`、`channel_grouping.py`、`channel_ai.py`、`backend/api/smart_channel_views.py` | 可信来源证据版本、人工审核、私人分组、无隐性模型调用 | `test_ag01_source_metadata.py`、`test_classification_evidence.py`、`test_smart_channel_workspace.py` |
| Web 页面与状态 | `frontend/src/App.tsx`、`pages/`、`services/`、`context/`、`stores/` | URL 页面状态、TanStack Query 服务端状态、Zustand 本地偏好、认证隔离 | `frontend/tests/pages/`、`frontend/tests/services/` |
| CI 与交付 | `.github/workflows/ci.yml`、`ops/ci/change_scope.py`、`benchmark-xdist.sh`、`scripts/deploy/` | 两级路径分流、双 Runner 隔离、混合 pytest、镜像构建与 G1 | `ops/ci/tests/`、`scripts/deploy/tests/` |

表内部分测试在 `backend/api/tests/` 下，仅为简短排版省略公共前缀。正式调用必须使用实际路径；如果将来重构，应按最新文件重新定位。

### 2.3 前端状态所有权

- `App.tsx` 是页面/FeatureRoute 的入口；`CapabilitiesContext.tsx` 的无效/未知能力默认为 fail-closed。
- `services/api.ts` 管理 Axios、CSRF、SSE 等通用通信；`workspaceApi.ts` 管理频道工作区的 viewer 与受控请求。勿再创建独立不兼容的 HTTP/CSRF 客户端。
- TanStack Query（`services/*Queries.ts` / `queryClient.ts`）拥有服务端状态、失效和 viewer-scoped 查询键；`stores/preferences.ts` 的 Zustand 只承载客户端偏好；`react-router-dom` / URL 是路由与可分享筛选的依据。
- 切换登录账号、退出、Abort 或卸载时，旧的私有请求结果不得污染新 viewer；列表 DTO 与详情 DTO 不可随意合并成超大接口。
- 优先复用已有组件、hooks、路由 gate；更改跨端字段时更新 parser/类型/后端合同和前后端回归。

### 2.4 当前迁移中的高风险边界

**RSS：** 正式方案以 `docs/plans/rss-engine-migration/ARCHITECTURE.md` 为目标合同；现有 Miniflux adapter、订阅/同步/正文模块已在 main，但真实生产切源、旧栈退出有独立验收。旧 Scrapy 代码不是“应该新增功能的首选”，也不是“可以立即删除的死代码”。

**BYOK：** `UserAIConnection` 是当前唯一新连接身份。T01 有 AES-GCM、credential_epoch、Worker enqueue/claim/dispatch/commit 围栏；`ai_execution.py` 在 T02/T03 缺失时拒绝用户模型业务调用。禁止恢复旧 `UserProviderCredential` 运行路径、静默回退站点 Key、使用真实 Key 进行单测、宣称个人模型业务已端到端可用。ChatGPT Subscription 独立。

**AI 终态/SSE：** 不允许 EOF 被伪装为正常完成。保留 LiteLLM Chat Completions streaming 的 fail-closed Guard。任何取消、重试、断线恢复、最终结果提交都必须遵守 owner/lease/epoch/版本边界；不得“先给客户端成功，后台再补一致性”。

**SQLite/内容：** 主库在 SQLite WAL。网络 I/O 应在 DB 事务外完成；并发写入优先短事务、显式 CAS/版本围栏，不凭 `select_for_update()` 假设 SQLite 行锁。来源/正文变化后旧译文及旧证据不能自动视为新版本。

**智能频道：** 可信域名与来源元信息需版本化证据，人工修正优先且可审核；无权时 GET 不触发模型、抓取或意外写入。AG-01 已有回归，AG-02–AG-07 不能因为存在组件或测试就自动标完成。

## 3. 唯一事实来源及冲突处理

开发前依次核对：
1. 本轮用户明确目标和授权范围；当前 `origin/main` SHA、工作树/PR 真实基线。
2. 当前代码、迁移、测试与 CI 实际运行路径：判断“已经实现了什么”。
3. 与当前任务绑定的最新合同、Issue/PR、已合并证据：判断“应该实现什么/尚未验收什么”。
4. 历史 README、旧设计与旧分支只作背景，不能覆盖较新的合同和代码事实。

相关合同索引：
- `docs/plans/FEATURE-DEVELOPMENT-2026-10-17.md`（任务编号和后续边界；注意文件内较早的状态表为历史快照）。
- `docs/plans/rss-engine-migration/ARCHITECTURE.md` 和 `TASKS.md`（RSS 目标架构）。
- `docs/features/byok/T01-WORKER-FENCING-2026-10-18.md`（BYOK 安全合同）。
- `docs/features/smart-channels/AG-01-2026-10-18.md`、Issue #55（智能频道）。
- `docs/frontend-modernization-record.md`（状态边界）。
- `ops/ci/change-routing.md`（CI 分流）。
- `README.md`、`TESTING.md`、`scripts/run_tests.sh` 存在过期描述/不完整本地测试入口，不能当成全量测试权威。

遇到“合同设计要求”和“目前代码实际状态”不符：报告缺口，提出影响文件及兼容策略，不通过省略测试或回退旧系统掩盖。

## 4. 推荐 Codex 文件布局（分层渐进落地）

~~~text
news-aggregator/
├── AGENTS.md                         # 全仓库：高价值不变量与门禁
├── backend/
│   ├── AGENTS.md                     # Django/SQLite/API/AI 共通约束
│   └── api/
│       └── rss/
│           └── AGENTS.md                 # RSS/Miniflux/正文独有规则
├── frontend/
│   └── AGENTS.md                     # 状态/路由/API/测试约束
├── ops/ci/
│   └── AGENTS.md                     # CI/Runners/G1/变更路径
├── .agents/skills/
│   ├── newshub-impact-analysis/SKILL.md  # 影响范围分析，工作流
│   ├── newshub-verify/SKILL.md           # 选取测试及执行，工作流
│   └── newshub-pr-handoff/SKILL.md       # 交付证据/回滚，工作流
└── docs/development/
    └── CODEX-AGENT-STANDARD-2026-10-18.md # 本方案；规范全文
~~~

**只提交规则，不在首轮提交 `.codex/config.toml`。** 现有个人模型、登录方式、审批、沙盒与 MCP 留在用户配置 `~/.codex/config.toml`；不要把本机绝对路径、凭据、个人 Provider 设置写入仓库。

官方 AGENTS.md 加载规则：Codex **启动会话时**从 Git 根到**当前工作目录**依次读取，较深目录覆盖较浅约定；同目录可使用 `AGENTS.override.md`，但本项目不建议滥用。**注意：若 Codex 从仓库根目录启动，`frontend/AGENTS.md`、`backend/AGENTS.md` 等不应被假定自动加载；动手修改子模块前须明确读取适用的子目录规则，或从对应子目录启动新会话。** Skills 以 `.agents/skills/<name>/SKILL.md` 供按需发现。不要把所有模块文档粘贴进根 AGENTS，避免每次会话重复消耗上下文。

建议根 `AGENTS.md` 控制在约 100–150 行以内，四个子文件分别约 20–50 行；内容没有实际不变量或命令的，不要写入规则。建议三项 Skills 首先以**纯指令**落地，验证确有重复操作再增加脚本。

## 5. 根 AGENTS.md 的建议内容（可用于下一阶段实现）

~~~markdown
# NewsHub Agent Rules

## Source of truth
- Check git status, branch, origin/main and the affected source/tests before modifying code.
- Before editing frontend/, backend/, backend/api/rss/ or ops/ci/, explicitly read applicable nested AGENTS.md files if present; launching Codex at repo root does not automatically include deeper directory rules.
- Read docs/plans/FEATURE-DEVELOPMENT-2026-10-17.md only for task identity and current relevant decisions; earlier historical snapshots are not current implementation evidence.
- Read ops/ci/change-routing.md before changing CI. Do not use README.md or scripts/run_tests.sh alone to assert full test coverage.

## Execution boundaries
- Keep each batch to at most two independent writing goals; overlapping schema/routes/fixtures/migrations require sequential integration.
- Use existing modules/permissions/query keys/workers; don't add parallel provider, cache, HTTP client or CI implementations without identifying an actual capability gap.
- Never overwrite dirty worktrees or merge unrelated work; isolate new goals using feature branches/worktrees when appropriate.
- Changes to production, real paid providers, secrets, migrations on real data, disabling safety gates or releasing code require the authorization applicable to the task.

## Project invariants
- User-private objects, credentials, history, subscriptions and caches must remain owner-scoped and fail closed when authorization is unknown.
- Keep SQLite writes short and version-fenced. Do not perform external network/model IO inside transactions.
- RSS design targets Miniflux; don't add features to legacy Scrapy or remove legacy runtime paths before its retirement gate.
- BYOK uses UserAIConnection, credential_epoch and ai_worker_fencing. T02/T03 missing: no implicit provider/model fallback or fake business completion.
- ChatGPT Subscription is a separate authorized path. Do not merge its tokens, user selection or worker scope into BYOK.
- Never invent successful SSE terminal events, leak plaintext keys or replay stale research/translation/content after revocation.
- Preserve React URL/TanStack Query/Zustand ownership and Django Session/CSRF/feature gates.

## Verification and handoff
- Inspect code/test impact before edits, prefer the smallest actual set of tests, and expand to contract/security/integration tests when changing shared behavior.
- Canonical CI is .github/workflows/ci.yml + ops/ci/benchmark-xdist.sh; do not claim scripts/run_tests.sh alone runs all CI checks.
- GitHub CI may skip entire docs-only workflows or one product job by path: Skipped/NOT_RUN is not PASS.
- Report changed files, behavior/contracts, executed commands, PASS/FAIL/NOT_RUN, remaining risk and PR/CI commit SHA.
- Never silently disable/suppress/fix-by-skipping failing tests. Full release validation remains explicit.
~~~

不要把用户的临时任务指令（例如某次“继续所有剩余 Issue”）固化为永久规则。根规则写**架构与行为边界**，当前任务写进对应 Issue/PR 和这次 Codex 提示。

## 6. 子目录规则的分工

### backend/AGENTS.md

- Django/DRF/API 分层：view 做身份/输入/错误映射，service 实现业务与操作边界，model/DB 不得承担网络行为。
- 数据变更先审核迁移历史、所有者和回滚；不得重放旧迁移编号、删除业务记录或对真实库跑迁移试验。
- 权限：Django Session + CSRF、owner ACL、read-only/feature gate、错误响应不得回显 Key。
- 依赖 DB 并发的操作使用显式 idempotency/lease/generation/epoch/CAS；失败不得静默计为成功。
- 研究、翻译、TTS 统一读取具备版本和 ACL 的文章正文；SSE 不得伪造终态；BYOK 与 ChatGPT Subscription 隔离。
- 代码修改后按影响的 API、迁移、权限、并发、网络安全路径选择测试；真实网络/模型用明确授权的独立验收。

### backend/api/rss/AGENTS.md

- 保持 EngineAdapter/同步/操作/正文存储/私有订阅分层；NewsHub 不自建新 Feed 解析、站点提取器或绕过 Miniflux 的平行运行栈。
- FeedBinding 引擎身份不可随意重绑；Engine API 放在数据库事务外，结果不直接授予 DB 写权限。
- 检查 `content_store` 的写令牌/来源版本/来源权限及 `access` 的授权；未知结果、不完整正文、旧版本不得按成功/完整输出。
- 订阅/取消/刷新要有明确 idempotency、重试和 unknown result 恢复；严守 URL SSRF、重定向、超时、容量与凭据边界。
- 旧链路退出只按 RSS T29/T30/T31/T33 的实施/验收合同推进。

### frontend/AGENTS.md

- 页面路由在 `src/App.tsx`，功能可用性由 Capabilities/FeatureRoute 决定，不用前端隐藏代替后端授权。
- URL/Router 管理可导航状态；TanStack Query 管理服务端异步数据；Zustand 管理客户端偏好。勿新增重复全局状态管理器。
- 使用 `services/api.ts` / `workspaceApi.ts` 已有 Session/CSRF/Abort/SSE 机制；变更 API 契约同步调整 DTO 解析和测试。
- User viewer 切换要隔离缓存并阻断陈旧响应。翻译/研究流处理须兼容取消、断线和服务端真实终态。
- 优先沿用现有视觉组件和无障碍交互；变化涉及键盘/移动端时验证焦点、状态和空/错误页面。
- 验证 `npm run typecheck`、`npm run lint`、相关 `npm run test:run -- <file>`，需要时 `npm run build`。

### ops/ci/AGENTS.md

- 唯一 CI 实现为 `.github/workflows/ci.yml`、`change_scope.py`、`benchmark-xdist.sh` 和现有双 Runner；无理由不要添加第三套 CI 或 Docker daemon。
- 改路由时同步 `ops/ci/tests/test_change_scope.py`、`ops/ci/tests/test_ci_contract.py`、`scripts/deploy/tests/test_release_operations.py` 和 `change-routing.md`。
- 新路径未分类/变更检测异常时保守双跑。不得把 `Skipped` 伪装为 `PASS`；手动 `workflow_dispatch` 必须保持全量。
- 七个 state-sensitive pytest 模块保持串行，其余仍采用现有两 worker xdist，保留动态 test identity、JUnit 和 16 个当前 skip 审核门禁；不得硬编码通过总数。
- 不把 frontend Runner 暴露给 DinD，保留后端私有 socket、无生产 secrets、失败前置和镜像/G1 门禁。

## 7. 三个 Skills（建议触发和交付）

| Skill | 何时触发 | 要求输出 | 不做事项 |
|---|---|---|---|
| `newshub-impact-analysis` | 涉及多模块、API/DB 契约、迁移、RSS/BYOK/安全边界的改动前 | 修改目标、代码入口、数据流、风险、依赖和测试范围 | 不直接写业务代码，不靠旧计划猜现状 |
| `newshub-verify` | 已修改源码/测试/依赖/CI，准备汇报或 PR 时 | 精确命令、结果/证据、CI Job 预测、NOT_RUN 边界 | 不将 Skip 算 Pass，不改变真实 CI 路由 |
| `newshub-pr-handoff` | 准备提交/审查/合并 PR 时 | base/head SHA、变更表、兼容性、测试/CI URL、风险与回滚 | 不替用户或 CI 宣称生产验收成功 |

Skills 元数据中必须写明确触发场景，不能写“任何任务都必须使用本 Skill”。首版仅建立这三种真实重复流程即可。每个 `SKILL.md` 包含 YAML frontmatter（`name`、`description`），正文优先短步骤；长参考材料直接链接本规范相应章节。

参考 `newshub-verify/SKILL.md` 骨架：

~~~markdown
---
name: newshub-verify
description: Use for verification after NewsHub runtime, test, migration, workflow or dependency changes, and before reporting a PR ready. Do not invoke for read-only questions or docs-only edits.
---

1. Read the changed files using git diff against the correct PR base, not only HEAD^.
2. Open ops/ci/change-routing.md and the corresponding module AGENTS.md.
3. Identify affected contracts and the smallest real test files; if unclear, broaden.
4. Run feasible tests and keep raw exit codes; include owner/ACL, version, cancellation or replay tests for sensitive flows.
5. If release-gate paths changed, require the canonical PR CI. Do not replace G1, migrations or real-provider gates with mock success.
6. Return file paths, commands, PASS/FAIL/NOT_RUN, CI routing prediction and a concise risk summary.
~~~

## 8. 真正可执行的验证矩阵

**环境先决条件：** 使用仓库实际存在的 Python venv、Node 依赖和 Git Worktree。没有依赖时报告 `NOT_RUN`，不能偷偷连生产库、触发付费模型或假装测试通过。

| 改动场景 | 建议先运行（实际存在的路径） | 必要扩展 |
|---|---|---|
| NewsHub 普通前端 UI | `cd frontend && npm run typecheck && npm run lint`；`npm run test:run -- tests/pages/NewsList.test.jsx`（按实际组件替换） | 影响生产构建时 `npm run build`；相关集成组件测试 |
| AI 设置界面/后端连接 | `backend/api/tests/test_ai_connections.py`、`test_ai_worker_fencing.py`；`frontend/tests/pages/AIModelSettingsPage.test.tsx`、`tests/services/aiConnectionsApi.test.ts` | 更改真实消费端再覆盖终态、权限/迁移/撤销和 G1 |
| RSS/Miniflux | `backend/api/tests/rss/test_engine_adapter.py`、`test_subscriptions.py`、`test_sync_reconciliation.py`、`test_body_commit.py` | 身份变更/内容/权限时追加 `test_access_contract.py`、`test_owner_fencing.py` |
| 智能频道 | `backend/api/tests/test_ag01_source_metadata.py`、`test_smart_channel_workspace.py`、`frontend/tests/pages/SmartGroupingWorkspace.flow.test.tsx` | 元信息过期/用户隔离/审核失败、GET 零模型网络行为 |
| 全文翻译/研究 | `backend/api/tests/test_shared_translations.py`、`test_translation_sse.py`、`test_research_recovery.py` | owner 变更/断连/终态/恢复并发/正文版本回归 |
| CI 改动 | `python3 -m unittest discover -s ops/ci/tests -p 'test_*.py'` | `scripts/deploy/tests/` + 现有 GitHub 完整 PR CI |
| Docs-only 白名单文件 | 不运行产品 CI | 文档路径、链接、引用和对当前代码事实的核对；不能记为测试 PASS |

Python 局部执行格式（从仓库根目录）：

~~~bash
PYTHONPATH=backend:crawler RUN_MAIN=true \
  backend/venv/bin/python -m pytest -q \
  backend/api/tests/test_ai_connections.py \
  backend/api/tests/test_ai_worker_fencing.py
~~~

前端局部执行示例：

~~~bash
cd frontend
npm run typecheck
npm run lint
npm run test:run -- tests/pages/AIModelSettingsPage.test.tsx tests/services/aiConnectionsApi.test.ts
~~~

**完整 CI 不是 `scripts/run_tests.sh`：** 现有权威为 `.github/workflows/ci.yml`；后端 `ops/ci/benchmark-xdist.sh` 分别串行/并行覆盖 `tests/`、`backend/api/tests/`、`scripts/deploy/tests/` 并做动态身份对账；前端全量执行 typecheck、lint、Vitest、build；后端发布门禁包括 Docker 生产镜像、隔离 G1 Smoke。模块级局部命令仅是开发早反馈。

### CI 路由和新增 Agent 规则的关系

- 根 `AGENTS.md`、根 `.agents/**`、根 `.codex/**` 按现有分类作为共享变更，触发前后端 CI。
- `frontend/AGENTS.md` 属 `frontend/**`，通常走前端；`backend/AGENTS.md` 属 `backend/**`，通常走后端。
- `ops/ci/AGENTS.md` 属 CI 基础设施，触发双跑。
- 本规范位于 `docs/**`：**纯文档提交**按现有 GitHub `paths-ignore` 完全不触发自动 CI。若与可执行代码/配置混改则按实际代码路径执行。
- 未知路径分类只允许保守双跑；如果更改 CI 分类，需同时更新路径测试和文档。
- GitHub 如果把某 Check 配成 required，路径忽略可能造成 Pending；具体解决方案另行审核，不让 Agent 通过伪造 PASS 绕过。

## 9. 开发/审查/合并任务合同

一次功能改动至少记录：

~~~text
Task ID / Issue / base SHA:
Goal (<=2 independent write goals):
Owned files and shared files:
Behavior to preserve:
Risk: auth/secret/SSRF, schema, SSE, concurrency, interface, RSS retirement:
Proposed minimal implementation:
Test commands and observed results:
CI routing expectation (frontend/backend/both/none):
PR head SHA / actual GitHub check links:
NOT_RUN and user acceptance scope:
Rollback (revert code or feature flag; do not mutate production database):
~~~

阶段：
1. 读 `git status`、`origin/main`、当前 Issue/PR 和**已存在**测试，列出文件所有者；从仓库根启动时，先显式读取本任务适用的子目录 AGENTS.md。
2. 仅独立写入目标可采用不同 Worktree 并行；涉及 `models.py`、URL、迁移、共享配置、公共测试夹具时先串行整合。
3. 修改前选定跨层合同和负例，优先最小实现+必要回归；新依赖必须说明成熟替代方案和升级/回滚。
4. 先局部验证，再根据改动风险/依赖运行更大范围；绝不能通过“删除用例、更新固定数量、修改期望值”掩盖真实错误。
5. PR 记录真正执行的命令、CI URL/结果、代码 SHA，明确 `PASS` / `FAIL` / `SKIPPED` / `NOT_RUN` / `BLOCKED`；对生产/付费/人工验收独立标注。
6. 只有任务授权且必要门禁实际通过，才合并；不要对未获授权的生产做部署、迁移、付费模型调用。

审查要求优先：安全和用户隔离、API/SSE 合约、数据一致性、版本/租约/撤销、迁移和回滚、异步取消与恢复。格式化交给确定性工具；避免风格噪音。

## 10. 验收 Agent 配置本身（不是只看文件存在）

第一批建议独立 PR 落地根 `AGENTS.md`、`frontend/AGENTS.md`、`backend/AGENTS.md`；第二批补 RSS 专项、CI 约束和三种 Skills，避免一次性引入大量未验证提示词。

| 用例 | 期望 Agent 行为 |
|---|---|
| “仅修改 NewsList 的样式” | 只读相关前端文件、选择前端测试、预计前端 CI |
| “给 BYOK 新增一个模型配置” | 明确当前只有 T01，引用 T02/T03 依赖，禁止站点 Key 回退或真付费测试 |
| “重构 RSS 同步” | 找到 EngineAdapter→sync→content_store/ACL，使用相关 RSS 合同与测试，不新增 Scrapy |
| “只改中文说明文档” | 不修改源码或主动运行完整 CI，正确表述触发器路径忽略 |
| “修改 .github/workflows/ci.yml” | 复核路由、安全和覆盖对账，预测双跑并执行契约测试 |
| “补一个 Django API” | 拒绝只做前端隐藏鉴权，识别 URL/serializer/CSRF/owner 合同与后端测试 |
| “修复研究 SSE 断线恢复” | 保留真实终态、持久事件、授权重读，设计掉线/撤销/重复请求负例 |

验证手段：新 Codex 会话从根目录和子目录分别要求“总结生效规则”，只读检验；用不同风险级别的可回滚合成任务评估规则遵循、误触发 Skills、额外 Token、功能正确率和 CI 范围。不得把“Agent 读到了规则”当成“效果已验证”。

## 11. 实施顺序和回滚

- **D0（本草案）**：仅存档已核实的架构、约束与文件布局；不改任何 runtime/CI。
- **D1（首个 Agent PR）**：根 AGENTS + frontend/backend 子级规则；保持简短，通过两级加载与实际用例验证。
- **D2（第二个 Agent PR）**：RSS 和 ops/ci 局部规则；增加三项按需 Skills；运行静态校验、路径分类和真实验收。
- **D3（观测后）**：按使用记录调整冗余指令、误触发、成本；如确实需要再添加自定义只读审查 Subagent。

回滚就是删除/恢复对应规则文件与 Skill，并重新启动 Codex 会话检查生效指令。任何阶段不要求改动模型或 API Key 配置。

## 12. 核实依据

- 当前仓库源码及配置：`backend/api/`、`backend/newsaggregator/settings.py`、`frontend/src/`、`.github/workflows/ci.yml`、`ops/ci/`。
- 最新合并证据：PR #104、#105、#106、#107，`main@40728f0`。
- 项目目标与历史差额：`docs/plans/FEATURE-DEVELOPMENT-2026-10-17.md`、`docs/plans/rss-engine-migration/ARCHITECTURE.md`、`docs/features/byok/T01-WORKER-FENCING-2026-10-18.md`、`docs/features/smart-channels/AG-01-2026-10-18.md`。
- Codex 官方配置：`https://developers.openai.com/codex/guides/agents-md`、`https://developers.openai.com/codex/skills`、`https://developers.openai.com/codex/config-basic`。
