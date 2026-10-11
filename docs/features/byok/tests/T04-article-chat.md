# Test T04 · 新闻问答 BYOK 闭环

对应：[T04 Task](../tasks/T04-article-chat.md)。

> **READY FOR REVIEW（2026-10-12）**。业务端到端本地闭环、固定路由、双用户模型所有权、完整终态保存和清空竞态已有自动化证据。PROVIDER_REAL、用户浏览器 UAT、双用户并发流与失效 Key 的真实 Proxy 故障注入仍为 NOT_RUN；T04-02、T04-03、T04-05 标为 PARTIAL，不代表完整验收。

## 提交与执行环境

| 项目 | 结果 |
| --- | --- |
| 精确基线 HEAD / 分支 | `68895c1e26660564ddc01d474caaef510770a22b` / `task/byok-T03-preferences` |
| 基线 PR | [#37 Draft](https://github.com/CoderLambert/news-aggregator/pull/37)，尚未合并；本卡分支依赖该提交 |
| T04 分支 | `task/byok-T04-article-chat` |
| T04 实现提交 | `4f47aacbb959ffdc79acf73c7d66795572799a39` |
| OS / 架构 | Linux 7.2.5-3-omarchy x86_64 |
| Python / Django / DRF / pytest / OpenAI SDK | 3.14.8 / 6.1.2 / 3.18.3 / 9.1.1 / 3.28.0 |
| Node / npm / Vitest | 24.21.0 / 11.19.0 / 4.1.7 |
| Docker / LiteLLM Proxy | Docker 29.7.2；`ghcr.io/berriai/litellm@sha256:3d88bd757134a00e8c00237b85a021ab1f6d54abb9c1df750f411dbe7256a500` |
| 数据库与隔离 | pytest 临时 SQLite；Proxy 使用本地独立 Compose 项目；Python venv `/tmp/byok-t01-verify-20261012` 和测试 stub `/tmp/byok-t02-test-stubs`；未读取仓库 `.env`、用户数据库或真实 Key |

## 变更前基线

基线代码为上述 T03 HEAD，使用与本次相同的 Python/Node 环境。

```sh
PYTHONPATH="/tmp/byok-t02-test-stubs:$PWD/backend" \
  /tmp/byok-t01-verify-20261012/bin/python -m pytest \
  backend/api/tests/test_chat_context.py \
  backend/api/tests/test_chat_ownership.py \
  backend/api/tests/test_subscription_modes.py -q
```

结果：`68 passed in 11.45s`。

```sh
cd frontend
npm test -- --run \
  tests/hooks/useChat.test.js \
  tests/hooks/useChat.phase.test.js \
  tests/components/NewsChatAssistant.test.jsx
```

结果：`3 files, 29 passed`。

## 实际验证

T04 后端定向和旧聊天/偏好回归：

```sh
PYTHONPATH="/tmp/byok-t02-test-stubs:$PWD/backend" \
  /tmp/byok-t01-verify-20261012/bin/python -m pytest \
  backend/api/tests/test_ai_chat.py \
  backend/api/tests/test_ai_chat_sdk_local.py \
  backend/api/tests/test_chat_ownership.py \
  backend/api/tests/test_chat_context.py \
  backend/api/tests/test_ai_preferences.py -q
```

结果：`46 passed in 7.61s`。SDK_LOCAL 使用真实 OpenAI Python SDK 和本地受控 Responses SSE upstream；覆盖单次请求、固定模型别名、分离的项目/Provider Key、`store=false`、完整终态和无 `response.completed` 的 EOF 失败。

PROXY_LOCAL 使用 T00 的本地受控 upstream 夹具和固定 LiteLLM 镜像；runner 复制夹具到临时目录，只启动自身 Compose 项目，退出时删除容器与卷：

```sh
/tmp/byok-t01-verify-20261012/bin/python scripts/byok/run_t04_proxy_local.py \
  --t00-worktree /home/lambert/Documents/Codex/2026-10-11/task-2/news-aggregator-t00
```

脱敏结果：`{"cleanup":"PASS","model_alias":"news.deepseek-flash","no_retry_or_fallback":true,"provider_key_only_at_upstream":true,"provider_real":"NOT_RUN","proxy_local":"PASS","scope":"T04_PROXY_LOCAL_SYNTHETIC_ONLY","sdk_local":"PASS","secret_leak_check":"PASS","status":"PASS","upstream_request_count":2}`。一条完整流成功提交问答对和模型来源；一条 incomplete 流在输出部分文字后给出安全错误，未写入问题或回答。上游只观测到对应两次调用，均为 tenant-a 用户 Key；项目虚拟 Key、master/default/admin Key 均未作为 Provider 凭据，重试/回退数为零，容器日志未发现合成凭据。

前端：`npm test -- --run` 结果为 `70 files, 492 passed`；`npm run lint` 和 `npm run typecheck` 均通过。新增问答模型选择、模型来源渲染、来源历史解析和 incomplete 错误 UI 断言。

后端完整套件两次均为 `542 passed, 2 skipped, 1 failed, 2 warnings`（55.73s、59.73s）。唯一失败是未改动的既有订阅任务用例 `test_subscription_recovery.py::test_simultaneous_database_connections_share_one_unique_task` 的并发 SQLite 锁超时；单独重跑同一用例结果 `1 passed in 1.21s`。T04 定向用例全绿；不把这个不相关的全量套件限制记成 T04 回归。

隔离 `manage.py check` 报现有 embedding 模型未预装和 `frontend/dist/assets` 不存在两条环境 warning；`makemigrations --check --dry-run` 输出 `No changes detected`。未生成或应用迁移，也未触碰共享/生产数据库。

## 用例结果

| 用例 | 场景 / 正确性约束 | 状态 |
| --- | --- | --- |
| T04-01 | 后端经官方 SDK 和锁定 Proxy 流式问答；显示来源并读取已保存问答 | PASS；SDK_LOCAL、PROXY_LOCAL 与历史数据断言 |
| T04-02 | incomplete / EOF 不冒充成功、不保存、不重试或回退 | PARTIAL；Proxy incomplete、SDK EOF 和单元流失败已通过；真实失效 Provider Key/HTTP 故障注入 NOT_RUN |
| T04-03 | 用户模型所有权、清空后迟到流丢弃、不同用户会话隔离 | PARTIAL；跨用户模型拒绝、清空竞态和既有 owner 查询测试通过；双用户并发 BYOK 流及真实浏览器 logout/cache 竞态 NOT_RUN |
| T04-04 | 单次选择不改变长期用途偏好或既有任务 | PASS；当前用户显式模型走固定 alias，偏好记录仍为空；前端发送每轮 `model_config_id` |
| T04-05 | 既有订阅聊天和键盘操作 | PARTIAL；变更前 68 个后端旧用例与 29 个前端旧用例通过，最终前端全量通过；没有单独浏览器键盘/焦点 UAT |

## 测试改动与断言范围

- `NewsChatAssistant.test.jsx`：现有开关测试改用 `QueryClient` 和认证上下文以支撑新增私有模型目录查询；旧行为断言未放宽，并增加仅本轮选择模型的断言。
- `useChat.test.js`：仅增加选定模型随流发送/来源保存与 incomplete 错误不写 Query 缓存的断言；既有断言未放宽。
- `chatHistoryReconciliation.test.js`：仅增加持久模型来源字段白名单解析用例；既有断言未放宽。

## 未运行项与边界

| 级别 | 状态 | 说明 |
| --- | --- | --- |
| UNIT / INTEGRATION | PASS | 用户所有权、固定目录路由、会话代次、成功终态写入、错误流和旧聊天兼容已覆盖 |
| SDK_LOCAL | PASS | 官方 OpenAI SDK → 本地合成 Responses upstream；不代表真实厂商兼容 |
| PROXY_LOCAL | PASS | 固定 LiteLLM Proxy + 官方 SDK + 受控 upstream；不代表共享生产网关或真实 Provider |
| PROVIDER_REAL | NOT_RUN | 没有由本任务调用 DeepSeek 或其他 Provider；没有读取/保存真实 API Key |
| UAT / 浏览器 | NOT_RUN | 未执行真实用户操作或键盘/焦点浏览器验收 |
| 并发与 Key 故障注入 | NOT_RUN | 两名用户同时流式问答、连接在途轮换 Key、真实 Proxy HTTP 401/429 未单独注入 |
| 生产数据库迁移 | NOT_RUN | 没有迁移，无共享或生产数据库操作 |
