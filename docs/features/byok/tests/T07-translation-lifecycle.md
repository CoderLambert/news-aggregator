# Test T07 · 翻译取消与显式重新生成

> **EXECUTED · DRAFT PR #41**。测试代码提交 `7479a9ef4e0addd3a859cadcd487b5bfc0dd0c96`，堆叠在 T06 PR #40 的 head `f1b1ebe0549b961cc434c7bdcf84181b230d5a52`。T07 定向与旧回归均通过；GitHub CI、真实 provider、浏览器 UAT 状态分别记录，不互相代替。

对应：[T07 Task](../tasks/T07-translation-lifecycle.md)。

| 用例 | 场景 / 失败注入 | 正确性约束 | 状态 |
| --- | --- | --- | --- |
| T07-01 | 关闭 SSE 后 GET 恢复；卸载后重新挂载前端 hook | 无假取消；复用同一 job ID；不发起第二次 stream；合成执行只计一次 | PASS · Django + Vitest |
| T07-02 | worker 正在运行时显式 POST cancel，随后旧 worker 返回 | 仅 owner/当前 generation 可取消；取消状态不被旧执行结果覆盖 | PASS · threaded Django test + Vitest |
| T07-03 | 首次成功、显式新任务失败、再次显式新任务成功 | 每次创建不同 task ID/idempotency key；失败不覆盖旧成功；旧 task 结果可查 | PASS · Django + Vitest |
| T07-04 | started lease 过期后 GET 与相同幂等键 POST | 状态 interrupted；无 dispatch、无 provider 重试 | PASS · Django test |
| T07-05 | 现有订阅任务取消/版本语义 | 既有订阅恢复测试无回归 | PASS · Django regression |

## 如何证明

- **基线**：先用该卡涉及的旧测试在同一环境记录原始结果，再引入代码修改；不要凭“测试数量全绿”掩盖不相关回归。
- **实际测试**：新 Django unit/DB/HTTP/worker 或 Vitest/浏览器测试按必要范围补齐；没有业务路径运行的模拟测试不能算功能完整。
- **SDK/Proxy 真实程度**：真实官方 SDK + 受控 upstream 为 SDK_LOCAL；锁定 LiteLLM Proxy + 真实 SDK + 受控 upstream 为 PROXY_LOCAL；只有指定真实 provider/model/region 请求为 PROVIDER_REAL。三者分开记录，缺少对应真实执行证据时标 NOT_RUN。
- **回归**：每个改动了旧测试的文件列出 diff，说明产品语义的变更依据；不准无依据放宽断言。
- **用户验收**：翻译运行→关闭面板再连仍为同任务→明确取消后状态可查→重试新 task_id→旧译文仍可看。

## 执行证据（后续任务填写）

| 项目 | 结果 |
| --- | --- |
| 本卡状态 | **EXECUTED · DRAFT PR #41**；PR checks 以最新 GitHub 状态为准，暂不合并 |
| 精确基线 HEAD / 测试代码 HEAD | `f1b1ebe0549b961cc434c7bdcf84181b230d5a52` / `7479a9ef4e0addd3a859cadcd487b5bfc0dd0c96` |
| 环境 | Linux x86_64，Python 3.14.8、Django 6.1.2、pytest 9.1.1、SQLite；Node 24.21.0、npm 11.19.0、Vitest 4.1.7、React 19.2.6 |
| 修改前基线 | 同一隔离 Python/SQLite 环境：`46 passed in 11.55s`（`test_ai_translation_jobs.py` + `test_subscription_recovery.py`）；同一前端依赖：`25 passed`（`useTranslation.test.jsx` + `news-detail.test.jsx`） |
| T07 后端定向 + 订阅回归 | `50 passed in 12.01s`；同两 Django 测试文件，含新增 4 项 T07 测试 |
| T07 前端 hook + 订阅/页面相关回归 | `3 files, 28 tests passed`；含新增 3 项 hook 测试、`useTranslation` 和 news detail 测试 |
| Django system/migration checks | `manage.py check` 无错误，1 条 `staticfiles.W004`（worktree 未构建 `frontend/dist/assets`）；`makemigrations --check --dry-run`: `No changes detected` |
| 前端 lint / diff | 新增测试文件 ESLint 通过；`git diff --check` 通过。仅追加测试，没有修改或放宽既有断言 |
| 可复现后端命令 | `env -i PATH=/tmp/byok-t01-verify-20261012/bin:/usr/bin:/bin HOME=/tmp/byok-t01-empty-home PYTHONPATH="/tmp/byok-t02-test-stubs:$PWD/backend" DJANGO_ENV=development DJANGO_SECRET_KEY=t07-synthetic-only-not-a-secret DJANGO_DB_PATH=/tmp/byok-t07-after-20261012a.sqlite3 /tmp/byok-t01-verify-20261012/bin/python -m pytest backend/api/tests/test_ai_translation_jobs.py backend/api/tests/test_subscription_recovery.py -q` |
| 可复现前端命令 | `cd frontend && npm test -- --run tests/hooks/usePrivateTranslation.test.jsx tests/hooks/useTranslation.test.jsx tests/components/news-detail/news-detail.test.jsx`；`./node_modules/.bin/eslint tests/hooks/usePrivateTranslation.test.jsx` |
| SDK_LOCAL / PROXY_LOCAL / PROVIDER_REAL / UAT | 本卡没有发起 SDK 或 Proxy 请求：SDK_LOCAL **NOT_RUN**，PROXY_LOCAL **NOT_RUN**，PROVIDER_REAL **NOT_RUN**；手动浏览器 UAT **NOT_RUN**。Django worker/React hook 使用合成数据，不会访问 provider |
| 测试代码 diff | 新增 4 个 Django 生命周期测试和 3 个 React hook 测试；既有测试无改动。取消 owner/generation、迟到 worker fence、显式重试的幂等键、旧结果保留和过期任务禁止 dispatch 均有断言 |
| GitHub CI | 推送后待核对 PR #41 的当前 head 检查；未将本地通过写作 CI 通过 |
| 未验证、失败原因、修复 PR | 真实 provider 账单/行为和最终浏览器操作链未执行；不在 T07 本地自动化范围内，保留 NOT_RUN |

任何来源缺失，保留 NOT_RUN，不能伪造 PASS。

