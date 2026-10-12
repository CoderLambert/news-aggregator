# Test T00 · 官方 SDK 本地协议验真

> **SDK_LOCAL PASS · PROVIDER_REAL NOT_RUN**。本次执行遵循 2026-10-12 的用户指定范围：官方 OpenAI/Anthropic SDK 直连受控 loopback HTTP upstream，使用三个薄协议适配器。旧版本本文与 Task 中的 LiteLLM Proxy 路径不适用于本次验收；没有启动 LiteLLM、调用厂商或新闻业务。

对应：[T00 Task](../tasks/T00-sdk-protocol.md)。

## 范围与判定

| 阶段 | 状态 | 说明 |
| --- | --- | --- |
| SDK_LOCAL | **PASS** | 真实安装的官方 SDK 对本机 `127.0.0.1` 受控 HTTP/SSE upstream 发请求；8 个集成用例通过。仅证明这些 SDK/协议路径与本地夹具的交互。 |
| PROXY_LOCAL | **N/A** | 本次已确认的 T00 设计不采用 LiteLLM Proxy，也未启动 Proxy。 |
| PROVIDER_REAL | **NOT_RUN** | 没有调用 DeepSeek 或其他厂商。DeepSeek 脚本仅准备，不应在用户确认前运行。 |

SDK_LOCAL 覆盖：Chat Completions、Responses、Messages 完整终态；partial EOF 与各协议 length/incomplete；HTTP 503 和 SSE 错误；截断/非法与非白名单工具参数；每种协议两轮工具往返；Responses 原始 output items、Anthropic thinking/signature 与 Chat `reasoning_content` 的私有续接；公开消息/事件的私密状态隔离；显式 API Key/model 并发隔离；SDK `max_retries=0` 与每场景一次上游请求；取消时服务端观察到客户端关闭，并关闭 SDK 客户端/流资源。

所有凭据都是固定合成值，仅本地服务记录 `tenant-a` / `tenant-b` 标签，不记录 Key 或 Authorization。SDK client 显式传入 Key、base URL 与 `trust_env=False` 的 HTTP transport；不读取环境中的 provider Key、dotenv 或全局配置。

## 实现与环境

| 项目 | 记录 |
| --- | --- |
| 用户报告的基线 HEAD | `ea2ce55ae22e19e1604e88031b824b68f2666cec` |
| 本地 `origin/feat/byok-user-api-keys` 跟踪 HEAD / 本任务分支基点 | `3cd584c95acd52bc533bba0b55eab75b35c41ad5` |
| 差异 | GitHub API 于 2026-10-12 实时确认分支 HEAD 为 `3cd584c95acd52bc533bba0b55eab75b35c41ad5`，与本地跟踪 ref 相同；它比用户报告值多 4 个提交：`6440a07197dae4b43b032c782638ad97e9defb59`、`77ddc2759a17b586928c76b3fc55b6573a53319a`、`c22b5903b2c03582fb3b45d870fd50fb9857f071`、`3cd584c95acd52bc533bba0b55eab75b35c41ad5`。未重置。 |
| T00 SDK 实现 commit | `f69aeb68234fa46bd07a405f658fa36c3a9fa9e2` |
| Draft PR | [#45](https://github.com/CoderLambert/news-aggregator/pull/45)，base `feat/byok-user-api-keys`；创建时 head `1bfd72be1dee811f95faa1d8a8f4bb8813d264af`。Open、Draft、未合并。 |
| Python / OpenAI / Anthropic / HTTP transport | Python `3.14.8` / `openai==3.28.0` / `anthropic==1.13.0` / `httpx2==2.13.1` |
| 后端旧测试环境 | Python `3.14.8`、Django `6.1.2`、pytest `9.1.1` |
| 前端旧测试环境 | Node `26.8.1`、Vitest `4.1.7` |
| 安装范围 | 复用了已存在的隔离 venv `/tmp/byok-t00-smoke-20261012`；本次没有下载/升级任何包，没有升级全项目或系统软件。`tools/byok_t00_probe/requirements.lock` 固定三个直接依赖版本。 |

## SDK_LOCAL 命令与结果

工作目录：仓库根目录。执行环境使用 `env -i`，只设置 PATH、临时 HOME 和空 `PYTHONPATH`。SDK 测试请求全部发往本机临时端口。

```sh
env -i PATH=/tmp/byok-t00-smoke-20261012/bin:/usr/bin:/bin HOME=/tmp/byok-t00-sdk-home PYTHONPATH= timeout 90s /tmp/byok-t00-smoke-20261012/bin/python -m tools.byok_t00_probe.probe --mode sdk-local
```

脱敏输出：

```text
test_cancellation_closes_sdk_and_stream_resources ... ok
test_complete_terminal_states_and_public_continuation_boundary ... ok
test_eof_and_native_incomplete_reasons_fail_closed ... ok
test_explicit_key_and_model_are_isolated_between_clients ... ok
test_http_and_in_stream_errors_are_sanitized_and_not_retried ... ok
test_incomplete_and_non_allowlisted_tools_never_return_a_dispatchable_turn ... ok
test_sdk_retry_policy_is_zero_and_event_projection_hides_raw_data ... ok
test_two_tool_roundtrips_preserve_native_private_state ... ok

Ran 8 tests
OK
SDK_LOCAL=PASS providers_called=0 upstream=loopback
```

`PROVIDER_REAL` 未运行；没有产生外部 API 请求或费用。测试仅保留本地合成请求计数、协议、模型名和凭据标签，不输出请求正文或凭据。

## 既有聊天/研究/翻译测试对照

以下后端命令在实现前与实现后使用相同的隔离环境、临时数据库和 11 个测试文件。

```sh
env -i PATH=/tmp/byok-t01-verify-20261012/bin:/usr/bin:/bin HOME=/tmp/byok-t00-baseline-home PYTHONPATH=backend DJANGO_ENV=development DJANGO_SECRET_KEY='T00-baseline-synthetic-Django-key-20261012-6A4f9D!' DJANGO_DB_PATH=/tmp/byok-t00-baseline-dev.sqlite3 CHROMA_DATA_DIR=/tmp/byok-t00-baseline-dev-chroma TTS_CACHE_DIR=/tmp/byok-t00-baseline-dev-tts PUBLIC_SITE_MODE=full PUBLIC_SIGNUP_ENABLED=1 PUBLIC_AI_ENABLED=1 CHATGPT_PLAN_USAGE_ENABLED=0 CHATGPT_AUTH_MODE=local_oss timeout 180s /tmp/byok-t01-verify-20261012/bin/pytest -q --create-db backend/api/tests/test_chat_context.py backend/api/tests/test_chat_migration.py backend/api/tests/test_chat_ownership.py backend/api/tests/test_chatgpt_subscription.py backend/api/tests/test_research_csrf.py backend/api/tests/test_research_recovery.py backend/api/tests/test_research_tool_cancellation.py backend/api/tests/test_llm_translation_prompt.py backend/api/tests/test_shared_translations.py backend/api/tests/test_translation_jobs.py backend/api/tests/test_translation_sse.py
```

| 时点 | 后端结果 | 前端结果 |
| --- | --- | --- |
| 实现前基线 | `129 passed, 1 failed`；唯一失败是既存 `test_subscription_views_are_scoped_and_never_return_credentials` 期望跨用户 models 请求为 400，实际 403。 | Vitest 全套 `65 files / 466 passed`，62.58s。 |
| 实现后 | `129 passed, 1 failed`；同一测试、同一断言、同一 400 对 403 失败。未修改该断言。 | Vitest 全套 `65 files / 466 passed`，64.38s。 |

实现后前端命令（工作目录 `frontend/`）：

```sh
env -i PATH=/usr/bin:/bin HOME=/tmp/byok-t00-baseline-home timeout 120s /usr/bin/node node_modules/vitest/vitest.mjs run --maxWorkers=1 --reporter=dot
```

前端仍输出现有 React `act(...)` 和 Node `module.register()` 弃用警告；测试均通过。对照基线，旧后端/前端测试文件没有 diff；T00 没有更改旧断言、业务实现或测试配置。基线失败未被弱化或修正。

## 预备的 DeepSeek PROVIDER_REAL 路径

`tools/byok_t00_probe/provider_real.py` 是独立可选入口，不会被 SDK_LOCAL 调用。它固定官方通用 OpenAI-compatible 地址 `https://api.deepseek.com`，要求 `--model` 显式传值，通过终端隐藏输入 Key，拒绝非交互 stdin，SDK `max_retries=0`，固定一条合成文本请求和 `max_tokens=16`，关闭环境代理继承；输出只包含状态、模型名、请求数、token 计数或异常类/HTTP 状态，不打印 Key、正文或异常消息。没有运行此入口。

当前建议模型为官方文档列出的 `deepseek-flash`。以固定提示不超过 32 个输入 token、16 个最大输出 token 估算，按目前官方 peak cache-miss 输入价 `$0.30/1M` 和输出价 `$1.20/1M`，单次成功请求的 token 费用约不超过 **US$0.00003**；这不是平台充值门槛或最低扣款保证，价格可能变化。参考 DeepSeek [Models & Pricing](https://api-docs.deepseek.com/quick_start/pricing/) 与 [Thinking Mode](https://api-docs.deepseek.com/guides/thinking_mode/) 文档。待用户确认模型与预算后再运行。除 DeepSeek 外不据此声明任何厂商兼容。

## 限制

- 本地测试通过只证明固定 SDK 版本处理受控的 HTTP/SSE fixtures，不证明任何真实厂商兼容、线上代理行为或生产配置。
- 真实 DeepSeek 路由证据仍为 **PROVIDER_REAL=NOT_RUN**。其他厂商未调用、未验证。
- 独立分支已推送，Draft PR #45 已创建；没有合并。本任务未进入 T01。
