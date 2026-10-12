# Test T05 · 个人全文翻译最小闭环

对应：[T05 Task](../tasks/T05-private-translation.md)。

> **READY FOR REVIEW（2026-10-12）**。[Draft PR #39](https://github.com/CoderLambert/news-aggregator/pull/39) 以 T04 分支为 base。T05 本地自动化和前端验证已完成；一项旧订阅 SQLite 并发回归在整组运行时失败、隔离重跑通过。SDK_LOCAL、PROXY_LOCAL、PROVIDER_REAL、人工浏览器 UAT 和生产迁移均为 NOT_RUN。

## 提交与执行环境

| 项目 | 结果 |
| --- | --- |
| 精确基线 HEAD / 分支 | `2bc9490be92a2dcd27de4969996d7060f90f6ca6` / `task/byok-T04-article-chat` |
| T04 父 PR | [#38 Draft](https://github.com/CoderLambert/news-aggregator/pull/38)，OPEN、未合并；T05 依赖该分支 |
| T05 分支 / PR | `task/byok-T05-private-translation` / [#39 Draft](https://github.com/CoderLambert/news-aggregator/pull/39)，base 为 T04 分支 |
| T05 实现提交 | `b9c3275` (`feat: add private BYOK article translation`) |
| OS / 架构 | Linux 7.2.5-3-omarchy x86_64 |
| Python / Django / DRF / pytest / OpenAI SDK | 3.14.8 / 6.1.2 / 3.18.3 / 9.1.1 / 3.28.0 |
| Node / npm / Vitest | 24.21.0 / 11.19.0 / 4.1.7 |
| 数据库与隔离 | pytest 临时 SQLite，`DJANGO_DB_PATH` 位于 `/tmp`；Python venv `/tmp/byok-t01-verify-20261012`；仅测试导入 stub `/tmp/byok-t02-test-stubs`；未访问仓库数据库或读取 `.env` |
| Key / 网络 | 仅使用测试内合成 Key 和 mock SDK 流；T05 测试没有调用本地 Proxy 或真实 Provider |

## 变更前基线

在 T04 基线提交上，使用同一后端测试环境和三组旧订阅翻译测试：

```sh
PYTHONPATH=/tmp/byok-t02-test-stubs \
DJANGO_DB_PATH=/tmp/byok-t05-baseline-20261012.sqlite3 \
/tmp/byok-t01-verify-20261012/bin/python -m pytest \
  backend/api/tests/test_chatgpt_subscription.py \
  backend/api/tests/test_subscription_recovery.py \
  backend/api/tests/test_translation_jobs.py -q
```

结果：`80 passed`。

## 实际验证

T05 新增后端用例：

```sh
PYTHONPATH=/tmp/byok-t02-test-stubs \
DJANGO_DB_PATH=/tmp/byok-t05-final-new-20261012.sqlite3 \
/tmp/byok-t01-verify-20261012/bin/python -m pytest \
  backend/api/tests/test_ai_translation_jobs.py -q
```

结果：`10 passed in 4.89s`。覆盖完整终态保存与 GET 恢复、幂等重复/冲突/并发、A/B 私有隔离、长度和幂等头拒绝、凭证代次变更丢弃部分输出、写入回滚、关闭 SSE 后 worker 独立完成、显式上游 completed 终态以及 `0037` 迁移保留旧 subscription 行。Provider 流用 mock SDK 事件，不构成 SDK_LOCAL 或真实 Proxy 验证。

受影响的旧订阅回归：

```sh
PYTHONPATH=/tmp/byok-t02-test-stubs \
DJANGO_DB_PATH=/tmp/byok-t05-final-regression-20261012.sqlite3 \
/tmp/byok-t01-verify-20261012/bin/python -m pytest \
  backend/api/tests/test_chatgpt_subscription.py \
  backend/api/tests/test_subscription_recovery.py \
  backend/api/tests/test_translation_jobs.py -q
```

结果：`79 passed, 1 failed in 16.81s`。失败为既有 `test_sse_disconnect_does_not_cancel_background_worker`，SQLite `OperationalError` 使后台任务在终态更新时失败。隔离重跑同一用例为 `1 passed in 1.82s`。因此完整回归记录为 PARTIAL，不能记为全绿；未修改旧测试断言。

其他检查：`manage.py check` 输出 `System check identified no issues (0 silenced)`；`makemigrations --check --dry-run` 输出 `No changes detected`。两项均只连接 `/tmp` 测试 DB；embedding 模型预加载缺失产生一条环境 warning。

前端在 `frontend/` 下验证：`npm run typecheck` 通过；对变更 TS/TSX 文件运行定向 ESLint 通过；`npm run test:run` 为 `70 files, 492 passed`；`npm run build` 通过。`npm ci` 成功，安装输出报告 19 个依赖 advisory；本任务未运行 audit fix，也未修改 lockfile。

## 用例结果

| 用例 | 场景 / 正确性约束 | 状态 |
| --- | --- | --- |
| T05-01 | 完整上游终态、事务写入、稳定 task/result ID、GET 恢复 | PASS（mock SDK + Django DB/API） |
| T05-02 | 重复 Idempotency-Key、冲突请求和并发 attach | PASS |
| T05-03 | 不完整上游流与 DB 写入失败不能提交为成功 | PASS（mock SDK 终态与事务故障注入） |
| T05-04 | A/B 各用自己的 Key 翻译同篇文章，结果保持私有 | PASS |
| T05-05 | 旧 subscription 数据迁移及旧功能回归 | PARTIAL：迁移保真通过；旧回归 79/80，单例重跑通过 |

## 测试改动与未运行项

本卡只新增 `backend/api/tests/test_ai_translation_jobs.py`；没有修改任何既有测试断言。所有测试 Key 均为合成值。T05 没有读取、保存或发送用户真实 API Key，没有调用 DeepSeek 或其他真实 Provider，也没有启动 T00/T01 Proxy。

| 验证级别 | 状态 | 说明 |
| --- | --- | --- |
| UNIT / INTEGRATION | PASS | 新增 10 项后端用例通过，涵盖 owner、任务、迁移与失败路径 |
| SDK_LOCAL | NOT_RUN | 流式终态由 mock SDK 对象验证；未对本地受控 HTTP upstream 发 SDK 请求 |
| PROXY_LOCAL | NOT_RUN | 本卡没有启动 LiteLLM Proxy |
| PROVIDER_REAL | NOT_RUN | 本卡未发起真实 Provider 请求 |
| UAT / 浏览器 | NOT_RUN | 未执行手工浏览器验收 |
| 旧订阅整组回归 | PARTIAL | 79/80；SQLite 并发失败的单例重跑通过，见上文 |
| 生产数据库迁移 | NOT_RUN | 仅 MigrationExecutor 临时测试数据库验证旧行保真；未操作共享或生产数据库 |
