# NewsHub CI 按修改范围分流

基线：PR #106（`main@eb9931d`）已引入文件路径路由；本次补充**纯文档/非运行时元信息直接不触发自动 CI**。
核心目标是在不降低被选中 Job 的测试覆盖率的前提下，减少无关 Runner 工作、依赖准备和镜像构建。

## 两级分流：触发器过滤 + Job 路由

1. **GitHub 触发器（零 Runner）**：`.github/workflows/ci.yml` 的 `push` 与 `pull_request` 事件设置相同的 `paths-ignore` 白名单。只有本次变化的**全部文件**都匹配白名单时，GitHub 不启动该 CI Workflow。
2. **`changes` Job（轻量）**：当触发器决定运行 CI 后，由前端 Runner 检出完整 Git 历史，执行 `ops/ci/change_scope.py`，计算 `frontend=true/false` 和 `backend=true/false`。
3. **业务 Job**：`frontend` 继续负责 TypeScript/Lint/Vitest/build；`backend-and-release-gates` 继续负责 Django/pytest、生产镜像、隔离 G1 Smoke。单个 Job 被选择时**不缩减它原有的测试范围**。
4. **手动全量**：`workflow_dispatch` 不经过路径过滤，强制运行前后端完整门禁。发布前或修改跨端行为时使用。

## 路由矩阵

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

- PR：使用 PR base 和 head 的 `merge-base` 作为差异起点；Push：使用 GitHub 提供的完整 `before..head` 范围，不只检查 `HEAD^`。
- 使用 `git diff --name-only -z --no-renames`：重命名同时按旧路径和新路径分类，避免跨目录迁移漏检。
- 本次只改文档，GitHub 在**触发器层**跳过整个 Workflow（不会启动 `changes`）。
- 如果路径不在白名单内，触发器必须启动 Workflow；若 `changes` Job 计算不确定，则保守地**双跑**。
- `changes` 运行在无 Docker 权限的前端 Runner 上，使用 Python 标准库和 Git；不引入第三方路径过滤 Action。

## 安全边界

- **跳过不等于测试通过**。GitHub 的路径过滤可能导致检查处于 Pending。若以后启用了「要求 CI 必须通过」的分支保护，文档 PR 可能无法合并；此时应保留一个始终运行且轻量的必需检查，或重构工作流为始终完成的汇总检查，不能把 Skipped 伪装为 PASS。
- GitHub 文件筛选有自身差异比较与文件数限制；大量修改或特殊 Push 事件应按官方文档审查，发布前始终支持手动全量复核。
- `main` 上纯文档 Push 也不触发本 Workflow；部署或发布验收一律不能以文档提交代替代码提交的 CI 结果。
- 即使 API 接口文件未变化，后端响应的语义也可能改变。当前是**路径级粗粒度分流**，不是完整依赖图或跨端契约验证。
- Draft/Fork PR 的原有自托管 Runner 安全门禁继续保留。手动运行仍需可信来源。

参考：[GitHub Actions 官方 paths-ignore 说明](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#onpushpull_requestpull_request_targetpathspaths-ignore)。

## 验证与日常操作

```bash
# 校验路径分类、混合改动、重命名、多提交 Push 与回退安全性
python3 -m unittest discover -s ops/ci/tests -p 'test_change_scope.py'

# 校验 CI Trigger/Job 契约及 Runner 安全边界
python3 -m unittest discover -s ops/ci/tests -p 'test_ci_contract.py'

# 发布前或需要完整验证时，明确手动触发所有门禁
gh workflow run ci.yml --repo CoderLambert/news-aggregator --ref main
```

修改忽略名单时必须同步检查 `ops/ci/change_scope.py` 的分类，以及 `ops/ci/tests/test_change_scope.py`、`ops/ci/tests/test_ci_contract.py` 和 `scripts/deploy/tests/test_release_operations.py` 的契约。修改任一 CI 配置/测试文件本身会触发**前后端完整 PR CI**。
