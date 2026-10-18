# NewsHub CI 按修改范围分流

基线：PR #106（`main@eb9931d`）已引入文件路径路由；本次补充**纯文档/非运行时元信息直接不触发自动 CI**。
核心目标是将**开发阶段的提交快检**与**合并阶段的完整验收**分离，而不降低正式合并及主线的安全门槛。

## 开发阶段与合并阶段（当前合同）

| 入口 | Stage | 执行和结果 |
|---|---|---|
| **Draft PR** 的 opened/synchronize/reopened/converted_to_draft | **开发阶段** | 同仓库可信 PR；`changes` 根据增量文件确定 `dev-frontend` / `dev-backend`。前端类型检查 + Lint，后端语法 + 快速安全回归 + CI 契约；**不运行全量 Vitest/pytest、受控 SDK/Proxy、生产镜像构建、G1 Smoke** |
| **Ready for review** PR（包括转换事件，以及后续 synchronize） | **合并阶段** | `changes` 分析**整个 PR**，运行受影响的原 `frontend` 和 `backend-and-release-gates` 全套检查；`merge-gate` 核实被选中的完整 Job 都成功 |
| **main push** | **主线合并后校验** | 继续原有按路径选取的完整 Job、`merge-gate`；正式发布前仍应运行明确的全量 `workflow_dispatch` |
| **workflow_dispatch** | **手动完整检查** | 不受路径忽略控制，强制前后端完整 CI；不使用真实生产数据或收费供应商 |
| **仅 docs/** 及已批准的非运行时白名单 | **跳过** | 触发器不启动 Workflow；`NOT_RUN` 不代表通过 |

**Codex / 人工操作**：新功能 PR 默认 `Draft`，频繁提交只产生快检；完成实现、专项测试、代码审核和合并准备后执行 `gh pr ready <PR编号> --repo CoderLambert/news-aggregator`，由 `ready_for_review` 触发完整验收。若全量 CI 发现问题需继续修改，先执行 `gh pr ready <PR编号> --undo --repo CoderLambert/news-aggregator` 回 Draft，再提交修复；重新 Ready 后对最新 SHA 做完整 CI。Ready 状态下的新提交会重新全检，这是刻意保留的安全机制。

**重要限制**：开发阶段快检只是早期反馈，不能单独支撑合并。合并必须核验 `merge-gate`、本次最新 PR head SHA、最新 main/base、真实 review 意见与适用全量 Job 结果。现有仓库如果没有启用必要检查的分支保护，GitHub UI 仍可能允许手动绕过；不能把工作流成功等同于分支保护已经生效。

## 两级分流：触发器过滤 + 按阶段的 Job 路由

1. **GitHub 触发器（零 Runner）**：`.github/workflows/ci.yml` 的 `push` 与 `pull_request` 事件设置相同的 `paths-ignore` 白名单。只有本次变化的**全部文件**都匹配白名单时，GitHub 不启动该 CI Workflow。
2. **`changes` Job**：在同仓库 Draft PR 的 `synchronize` 事件中，仅当 GitHub `before` SHA 确认为新 head 的祖先时使用 `before..head` 增量；缺失 `before`、force push、重写历史则回退整个 PR 的 `merge-base..head`。Ready 阶段始终分析整个 PR。
3. **业务 Job**：Draft 只运行 `dev-frontend` / `dev-backend` 快检。Ready、main push 或手动运行时调用原 `frontend`（TypeScript/Lint/Vitest/build）和 `backend-and-release-gates`（pytest 全三根、生产镜像、隔离 G1），不得省略选中 Job 的原有测试。
4. **合并总门禁**：`merge-gate` 只有在非 Draft 的完整阶段启动；`changes` 成功且每个路由选中的完整 Job SUCCESS 才算 PASS，未选中的 Job 必须确认为 SKIPPED。Draft 下的 Skipped 不等于验收完成。
5. **手动全量**：`workflow_dispatch` 不经过路径过滤，强制运行前后端完整门禁。发布前或修改跨端行为时使用。

## 路由矩阵

下表中“前端/后端运行”代表文件影响范围；具体是 Draft 快检还是 Ready 全检由上面的阶段决定。


| 本次提交/PR 的变更 | 是否启动 Workflow | 前端 | 后端 + Docker/G1 |
|---|---|---|---|
| 仅 `docs/**`、`README.md` 等已批准说明文件 | **否** | 不运行 | 不运行 |
| 仅 `LICENSE`、`CONTRIBUTING.md`、GitHub Issue/PR 模板或 `FUNDING.yml` | **否** | 不运行 | 不运行 |
| `frontend/**` 的源码、测试、包依赖 | 是 | 运行 | 跳过 |
| `backend/**`、`crawler/**`、后端/发布测试、BYOK/RSS 后端模块 | 是 | 跳过 | 运行 |
| 前后端混合改动 | 是 | 运行 | 运行 |
| 接口路径、序列化契约、`.github/workflows/**`、`ops/ci/**`、Compose、Dockerfile | 是 | 运行 | 运行 |
| 文档 + 业务代码同时改动 | 是 | 仅按业务路径决定 | 仅按业务路径决定 |
| 未知路径、异常路径、无法计算 Git Diff | 是 | 运行 | 运行 |
| 手动 `workflow_dispatch` | 是 | 运行 | 运行 |

### 自动 Workflow 完全忽略的路径

以 `.github/workflows/ci.yml` 的 `push.paths-ignore` / `pull_request.paths-ignore` 为唯一最终配置：

```yaml
paths-ignore:
  - 'docs/**'
  - 'README.md'
  - 'TESTING.md'
  - 'DEVLOG.md'
  - 'CHANGELOG.md'
  - 'frontend/README.md'
  - 'CONTRIBUTING.md'
  - 'CODE_OF_CONDUCT.md'
  - 'SECURITY.md'
  - 'LICENSE'
  - 'LICENSE.md'
  - 'NOTICE'
  - 'NOTICE.md'
  - '.github/ISSUE_TEMPLATE/**'
  - '.github/PULL_REQUEST_TEMPLATE.md'
  - '.github/PULL_REQUEST_TEMPLATE/**'
  - '.github/FUNDING.yml'
```

使用的是**明确路径白名单**，**不是** `**/*.md`、`.github/**`、`scripts/**` 等全局忽略规则。特别注意：`.github/CODEOWNERS`、`.github/workflows/**`、`ops/ci/**`、项目 `AGENTS.md` / `.agents/**` 都不能因此跳过 CI。

`docs/**` 的目录语义是仅放置说明、报告与非可执行附件；如果未来将正式运行配置、契约文件或测试 fixture 放进 `docs/`，必须在同一次改动中先调整此白名单并补充契约测试。

## Git Diff 与失败保护

- Ready PR：使用 PR base 和 head 的 `merge-base` 作为整个 PR 差异起点；Draft PR synchronize：**验证 `before` 确为当前 head 祖先后**使用增量 `before..head`。缺失/重写历史会安全回退整个 PR 范围。main Push：使用 GitHub 的完整 `before..head`，不只检查 `HEAD^`。
- 使用 `git diff --name-only -z --no-renames`：重命名同时按旧路径和新路径分类，避免跨目录迁移漏检。
- 本次只改文档，GitHub 在**触发器层**跳过整个 Workflow（不会启动 `changes`）。
- 如果路径不在白名单内，触发器必须启动 Workflow；若 `changes` Job 计算不确定，则**在当前阶段**对前后端全部选中。Draft 不会因此偷偷运行生产镜像/G1 的完整阶段。
- `changes` 运行在无 Docker 权限的前端 Runner 上，使用 Python 标准库和 Git；不引入第三方路径过滤 Action。

## 安全边界

- **跳过不等于测试通过**。GitHub 的路径过滤可能导致检查处于 Pending。若以后启用了「要求 CI 必须通过」的分支保护，文档 PR 可能无法合并；此时应保留一个始终运行且轻量的必需检查，或重构工作流为始终完成的汇总检查，不能把 Skipped 伪装为 PASS。
- GitHub 文件筛选有自身差异比较与文件数限制；大量修改或特殊 Push 事件应按官方文档审查，发布前始终支持手动全量复核。
- `main` 上纯文档 Push 也不触发本 Workflow；部署或发布验收一律不能以文档提交代替代码提交的 CI 结果。
- 即使 API 接口文件未变化，后端响应的语义也可能改变。当前是**路径级粗粒度分流**，不是完整依赖图或跨端契约验证。
- 仍禁止对外部 fork PR 执行自托管 Runner。Draft 与 Ready **均必须属于同一可信仓库**；仅 Ready 执行完整合并检查。手动运行仍需可信来源。
- `merge-gate` 是合并证据，不会替用户启用 GitHub Branch Protection；所有自动/人工合并必须核对最新 PR head、完整门禁和代码审核，且不得将开发阶段快检当作最终状态。

参考：[GitHub Actions 官方 paths-ignore 说明](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#onpushpull_requestpull_request_targetpathspaths-ignore)。

## 验证与日常操作

```bash
# 校验路径分类、混合改动、重命名、多提交 Push 与回退安全性
python3 -m unittest discover -s ops/ci/tests -p 'test_change_scope.py'

# 校验 CI Trigger/Job 契约及 Runner 安全边界
python3 -m unittest discover -s ops/ci/tests -p 'test_ci_contract.py'

# 新 PR 从 Draft 开始。提交/同步时仅运行快检
gh pr create --draft --base main --title '...' --body '...'

# 准备合并（针对整个 PR 运行完整检查）
gh pr ready <PR号> --repo CoderLambert/news-aggregator

# 如果审核要继续开发，先回 Draft；新提交不会重复全量 CI
gh pr ready <PR号> --undo --repo CoderLambert/news-aggregator

# 发布前或需要完整验证时，手动触发所有门禁
gh workflow run ci.yml --repo CoderLambert/news-aggregator --ref main
```

修改阶段或忽略名单时必须同步检查 `ops/ci/change_scope.py` 的分类，以及 `ops/ci/tests/test_change_scope.py`、`ops/ci/tests/test_ci_contract.py` 和 `scripts/deploy/tests/test_release_operations.py` 的契约。修改任一 CI 配置/测试文件本身会触发**前后端完整 PR CI**。
