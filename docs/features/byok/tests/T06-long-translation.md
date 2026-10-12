# Test T06 · 长文分块完整翻译

> **IMPLEMENTED · DRAFT PR**。实现提交 `1f719e666edc5554c16ffc1aa0b227909118a60f` 位于 `task/byok-T06-long-translation`，堆叠于 T05 PR #39 / 基线 `54df6abd70a979fee11a2c610c4fde0c35f00a15`；PR #39 尚未合并。PR #40 head `324e194a460374cc0cc148c095debd07f8b2d9cd` 的两组前端均通过，一组后端完整门禁通过，另一组因既有 SQLite 并发测试失败。T06 自身定向测试通过；因重复后端门禁结果不一致，PR 保持 Draft。真实供应商调用和浏览器 UAT 未运行，保留为 NOT_RUN。

对应：[T06 Task](../tasks/T06-long-translation.md)。

| 用例 | 场景 / 失败注入 | 正确性约束 | 状态 |
| --- | --- | --- | --- |
| T06-01 | 跨多 chunk 的 Markdown 翻译和合并 | 顺序与进度一致；代码围栏原样通过；标题、行标、行内代码、链接目标、引用定义和表格形状在最终结果中保留，否则不保存 | PASS · pytest + PROXY_LOCAL |
| T06-02 | 中间 chunk EOF/限长/空输出 | failed、保留 partial progress、无完整结果或缓存；SDK/Proxy 不重试 | PASS · pytest + PROXY_LOCAL incomplete 负控 |
| T06-03 | 排队后文章正文变更 | 使用已冻结源文；源文变化后 provider 未启动，旧输入不冒充新正文 | PASS · Django worker test |
| T06-04 | 上下文/输出预算未知或 Markdown 结构超限 | 明确拒绝，不静默截断，不创建任务或发送 provider 请求 | PASS · pytest |
| T06-05 | T05 短文本路径和旧订阅回归 | 短文本单次完整调用；旧订阅行为不变 | PASS · T06 pytest + 80 项回归 |

## 实现边界

- 原文上限为 64 KiB UTF-8；单个模型输入最多 4 KiB UTF-8、最多 32 个翻译 chunk。预算从模型目录读取：输出限制为 `min(4096, model max output)`，输入字节上限为 `min(4096, context window - output limit - 512-token prompt reserve)`。缺失或无效元数据、过大的不可拆 Markdown 原子块都会在任务创建/provider dispatch 前明确失败。
- 字节预算是请求尺寸的保守护栏，不是 tokenizer 精确计数、模型成本上限或账单限额。最终输出使用模型目录给出的输出 token 限额；任何非 completed、空或结构破坏的输出都不会成为完整私有结果。
- fenced code 原文不发送给模型并按原样回传。其余 Markdown 按安全边界切块；合并后再校验代码围栏、标题级别、列表行标记、行内代码、链接数量与目标、引用定义和表格行/列形状。校验失败时任务失败，不保存完整译文。
- 沿用 T05 的 owner/session 权限、冻结输入、任务 lease、凭据 epoch fence、私有结果事务与 SSE；不改前端，也不增加队列或模型 fallback。

## 如何复现

以下代理检查使用 T00 PR #33 head `ad0f14eb599ddbf8a691dc535227d7ef18298cb6` 提供的锁定 LiteLLM Proxy 和内部合成 upstream。只生成临时虚拟 key，并使用 `sk-t00-provider-a-synthetic`；upstream 没有真实供应商路由。T06 探针只输出计数和布尔证据，不输出 prompt、凭据或译文。

```sh
cd /home/lambert/Documents/Codex/2026-10-11/task-2/news-aggregator-t00
docker compose --project-name byok-t06-proxy-20261012 -f tools/byok_t00_probe/compose.yaml up -d --wait proxy

cd /home/lambert/Documents/Codex/2026-10-11/task-2/news-aggregator-t06
PYTHONPATH=backend DJANGO_SETTINGS_MODULE=newsaggregator.settings \
DJANGO_DB_PATH=/tmp/byok-t06-proxy-integration.sqlite3 \
/tmp/byok-t01-verify-20261012/bin/python tools/byok_t06_probe/proxy_local.py \
  --compose-project byok-t06-proxy-20261012 \
  --compose-file /home/lambert/Documents/Codex/2026-10-11/task-2/news-aggregator-t00/tools/byok_t00_probe/compose.yaml

cd /home/lambert/Documents/Codex/2026-10-11/task-2/news-aggregator-t00
docker compose --project-name byok-t06-proxy-20261012 -f tools/byok_t00_probe/compose.yaml down --volumes --remove-orphans
```

再现本卡定向用例与旧回归：

```sh
cd /home/lambert/Documents/Codex/2026-10-11/task-2/news-aggregator-t06
PYTHONPATH=/tmp/byok-t02-test-stubs DJANGO_DB_PATH=/tmp/byok-t06-tests.sqlite3 \
  /tmp/byok-t01-verify-20261012/bin/python -m pytest backend/api/tests/test_ai_translation_jobs.py -q
PYTHONPATH=/tmp/byok-t02-test-stubs DJANGO_DB_PATH=/tmp/byok-t06-regression.sqlite3 \
  /tmp/byok-t01-verify-20261012/bin/python -m pytest \
  backend/api/tests/test_chatgpt_subscription.py \
  backend/api/tests/test_subscription_recovery.py \
  backend/api/tests/test_translation_jobs.py -q
```

## 执行证据

| 项目 | 结果 |
| --- | --- |
| T06 分支父提交 | `54df6abd70a979fee11a2c610c4fde0c35f00a15`（T05 PR #39 head；PR 未合并） |
| 运行环境 | Python 3.14.8、Django 6.1.2、pytest 9.1.1、SQLite；OpenAI SDK 3.28.0、httpx2 2.13.1；Docker Engine 29.7.2、Compose 5.5.1 |
| Proxy/upstream | LiteLLM 1.104.2，镜像 digest `sha256:3d88bd757134a00e8c00237b85a021ab1f6d54abb9c1df750f411dbe7256a500`；T00 isolated internal Compose network |
| 修改前旧回归基线 | 在上述父提交：`80 passed in 16.94s`，命令同“旧回归”一行 |
| T06 定向 pytest | `19 passed in 6.10s`，`test_ai_translation_jobs.py` |
| T06 后旧回归 | `80 passed in 16.89s`，`test_chatgpt_subscription.py`、`test_subscription_recovery.py`、`test_translation_jobs.py` |
| 瞬时 SQLite 并发波动 | 一次并行全测中 80 项有 1 项 `test_simultaneous_database_connections_share_one_unique_task` 失败；单测隔离重跑 `1 passed in 1.67s`，随后顺序全回归 `80 passed`。GitHub 上更早的 PR #33/#34 两次失败也分别落在既有 SQLite 并发/worker 恢复用例；T05 PR #39 的当前检查全通过。T06 顺序复跑通过；不改旧断言。 |
| `manage.py check` | 无错误；1 条 `staticfiles.W004`（T06 worktree 无 `frontend/dist/assets` 构建产物），启动时另有可选 embedding preload `ModuleNotFoundError` 警告 |
| `makemigrations --check --dry-run` | `No changes detected` |
| PROXY_LOCAL | PASS：T06 SDK 实际发出 15 个 Responses streaming chunk，均观察到 `response_completed`；upstream 确认 provider tenant 为 `tenant-a`、项目虚拟 key 未泄漏；围栏代码精确保留、SSE progress 与合并内容一致。incomplete 负控观察到 1 次请求、`response_incomplete`，业务返回 `incomplete_response`、0 retry。真实 provider 请求数 0。 |
| GitHub CI（head `7200211b382cdbee5086ee721eec64ad5d075ee0`） | 两组 frontend 均 PASS；两组 `backend-and-release-gates` 均 FAIL。run `38190345273`：895 passed、2 skipped，失败 `test_sse_disconnect_does_not_cancel_background_worker`（worker 持久化遇 `OperationalError`）；run `38190373196`：894 passed、2 skipped，失败该用例和 `test_simultaneous_database_connections_share_one_unique_task`（SQLite `OperationalError`）。两组均运行到 T06 测试且通过。完整检查尚未绿，不据本地回归覆盖。 |
| GitHub CI（最新完成的 head `324e194a460374cc0cc148c095debd07f8b2d9cd`） | 两组 frontend 均 PASS。backend run `38190688778` 全部通过（含 895 项测试、2 skipped、生产镜像构建及隔离 G1 smoke）；run `38190685979` 有 895 passed、2 skipped，唯一失败为既有 `test_simultaneous_database_connections_share_one_unique_task`（SQLite `OperationalError`）。该组也运行并通过 T06 测试。重复门禁结果不一致，所以 CI 仍记为未全绿、PR 保持 Draft。 |
| SDK_LOCAL / PROVIDER_REAL / 浏览器 UAT | SDK_LOCAL 未单独分类（SDK 已在 PROXY_LOCAL 中运行）；PROVIDER_REAL **NOT_RUN**；用户浏览器长文刷新验收 **NOT_RUN** |
| 测试断言 diff | 旧长度护栏从字符数改为 UTF-8 字节上限；扩展 fake SDK 以记录顺序/请求数/重试参数；新增完整结构、超预算无 dispatch、中间 chunk incomplete、空输出、结构变化不保存、排队后源文变化和私有多 chunk 结果测试。未放宽既有产品断言。 |
| 用户端操作链 | API/DB/worker/SSE 自动化覆盖通过；手动浏览器步骤保留 NOT_RUN |

这张卡的代码和工具验证已经完成，PR 会堆叠在 T05 #39；PROVIDER_REAL 与浏览器 UAT 没有被以上本地证据替代。
