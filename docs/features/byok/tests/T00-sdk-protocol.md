# Test T00 · 共享网关端到端技术验真

> **BLOCKED**：SDK_LOCAL 已对三协议执行正常完整流与正常 EOF 对照。PROXY_LOCAL 已运行固定 LiteLLM Proxy、官方 SDK、受控 HTTP upstream 和合成凭据隔离探针。LiteLLM v1.104.2 的 OpenAI Chat Completions streaming 路径把上游无终态 EOF 暴露为正常 `stop`，违反完整性契约。不得将本卡标为通过；PROVIDER_REAL 保持 NOT_RUN。

对应：[T00 Task](../tasks/T00-sdk-protocol.md)。可复现探针位于 [`tools/byok_t00_probe/`](../../../../tools/byok_t00_probe/README.md)。

| 用例 | 场景 / 故障注入 | 结果 |
| --- | --- | --- |
| T00-01 | 三协议完整文字和工具终态 | SDK_LOCAL 三协议正常流有对应终态；PROXY_LOCAL 只测 Chat 正常文本回合，工具及另外两路未验，PARTIAL |
| T00-02 | partial 事件后正常 EOF、length/incomplete | SDK_LOCAL EOF 均无终态；PROXY_LOCAL Chat 合成 `stop`，BLOCKED |
| T00-03 | 截断 body、超时、SSE error、HTTP error | NOT_RUN |
| T00-04 | 半截工具参数、非法 JSON、非白名单工具 | NOT_RUN |
| T00-05 | 两轮工具续接 | Responses items、Anthropic thinking/signature、Chat reasoning_content continuation 未验，NOT_RUN |
| T00-06 | 不同 Key/model 并发隔离 | 合成 A/B 的不同 virtual key、provider key、model allowlist 各成功一次；跨模型 403 且无上游请求。未并发执行，PARTIAL |
| T00-07 | 成功、异常、取消时关闭 stream/response/HTTP 资源 | SDK 流使用上下文管理器、Compose 清理成功；异常/取消后的 FD 关闭未独立断言，PARTIAL |
| T00-08 | 缺 provider Key、错误项目虚拟 Key | 错误项目 Key 401/无上游请求；缺 provider Key 500/无上游请求（本地 Proxy 未配置 provider fallback），PARTIAL |
| T00-09 | SDK/Proxy 重试与 fallback 计数 | SDK `max_retries=0`、Proxy `num_retries=0`、无 fallback；本探针内请求计数为单次，PARTIAL |
| T00-10 | v1.104.2 上游 EOF 与 Proxy 终态对照 | 上游无终态 EOF、Proxy SDK 收到 3 chunks 与 `finish_reason=stop`、上游请求 1 次，BLOCKED |
| T00-11 | 可选 DeepSeek 早期文本冒烟 | PROXY_LOCAL 未通过；PROVIDER_REAL=NOT_RUN，未读入任何真实 Key |

## 证明范围

- **SDK_LOCAL**：OpenAI `3.28.0` 与 Anthropic `1.13.0` 真实 SDK 直接访问受控合成 HTTP upstream，不经过 Proxy，不代表厂商兼容。
- **PROXY_LOCAL**：固定 LiteLLM Proxy `1.104.2` + 真实 OpenAI SDK + 同一受控 upstream。仅本 Test 标明的 Chat 路由和凭据/模型拒绝路径有证据。
- **PROVIDER_REAL**：NOT_RUN。DeepSeek 只会在本地门槛完整通过、另行提供模型/预算并获用户确认后测试；其它厂商不据此声明兼容。
- 日志只记录协议、场景、模型、合成租户标签、计数和头存在布尔值；不记录 Key、Authorization 值、提示正文或 continuation。

## 执行环境与基线

| 项目 | 结果 |
| --- | --- |
| 远端目标 `feat/byok-user-api-keys` | `3cd584c95acd52bc533bba0b55eab75b35c41ad5`（PR 31 merge HEAD；本地 `origin/feat` 跟踪引用仍为旧 `ea2ce55ae22e19e1604e88031b824b68f2666cec`，未重置） |
| 本次探针检出 HEAD | `c22b5903b2c03582fb3b45d870fd50fb9857f071`，分支 `task/byok-T00-proxy-probe` |
| T00 业务实现 SHA | 无。没有提交业务 SDK、provider 适配器或新闻调用实现；本次只增加独立探针和证据文档。 |
| 运行时 | Python `3.14.8`; OpenAI `3.28.0`; Anthropic `1.13.0`; httpx2 `2.13.1`; LiteLLM `1.104.2`; Docker Server `29.7.2`; Compose `5.5.1` |
| 镜像 | LiteLLM GHCR pull 成功，实际 `RepoDigest=sha256:3d88bd757134a00e8c00237b85a021ab1f6d54abb9c1df750f411dbe7256a500`；Postgres 实际 `RepoDigest=sha256:721873c34ceb9f8d8fc265984940dc982404c105f19ad51be9fdc5970a6080ea`。官方 cosign 签名验证 NOT_RUN（环境无 cosign，未安装系统工具）。 |
| Docker 授权/网络 | 正式提权的只读 `docker version` 成功，客户端/服务端 `29.7.2`；普通沙箱的 socket `EACCES` 是沙箱边界。GHCR 镜像 HTTPS 拉取成功。Compose 使用 `internal: true`，没有 host port、用户 home、Docker socket 或 provider Key 挂载。 |
| 旧聊天/研究/翻译测试基线 | 计划文档仅有历史摘要 `219 passed, 3 warnings`，精确命令/报告未恢复。此前隔离环境重跑准备因缺 `chromadb` 得到 `82 passed, 23 failed`，失败均指向该缺失依赖；未把它当产品回归。本次没有以同环境有效命令重建 219 基线，也未在探针文档改动后重跑，故旧基线对照仍未完成。 |
| 旧测试断言 diff | `tests/` 下旧测试和断言无修改；没有放宽断言。 |

## 可复现命令

在隔离 venv 安装锁定依赖并运行整合 CLI：

```bash
python3 -m venv /tmp/byok-t00-sdk-venv-20261011
/tmp/byok-t00-sdk-venv-20261011/bin/python -m pip install -r tools/byok_t00_probe/requirements.lock
/tmp/byok-t00-sdk-venv-20261011/bin/python tools/byok_t00_probe/probe.py
```

探针明确固定 Docker context `default`，自动启动并清理单次 Compose project/卷。provider key、master key、Proxy virtual key 都是本次探针合成值；SDK `trust_env=False`，不读取 `.env`、用户目录或进程里的 provider Key。非零返回码 `2` 是预期 BLOCKED 状态，表示检测到代理合成终态的完整性问题，不是脚本崩溃。

## 实际脱敏输出

最终 CLI 输出（key 值不会进入 stdout）：

```json
{"images":{"litellm":"ghcr.io/berriai/litellm@sha256:3d88bd757134a00e8c00237b85a021ab1f6d54abb9c1df750f411dbe7256a500","postgres":"postgres@sha256:721873c34ceb9f8d8fc265984940dc982404c105f19ad51be9fdc5970a6080ea"},"provider_real":"NOT_RUN","proxy_local":{"allowed_model_upstream_counts":{"tenant-a":1,"tenant-b":1},"chat_eof_integrity":"BLOCKED","cross_model_status":403,"cross_model_upstream_delta":0,"missing_provider_header_present":null,"missing_provider_status":500,"missing_provider_upstream_delta":0,"missing_provider_upstream_tenant":null,"proxy_eof_sdk_event_count":3,"proxy_eof_sdk_finish_reasons":["stop"],"proxy_eof_upstream_attempts":1,"proxy_eof_upstream_tenant":"tenant-a","proxy_eof_upstream_terminal":"normal_eof_without_protocol_terminal","tenant_a_finish":"stop","tenant_b_finish":"stop","wrong_project_key_status":401,"wrong_project_upstream_delta":0},"runtime_versions":{"docker_compose":"5.5.1","docker_server":"29.7.2","litellm":"1.104.2"},"sdk_local":{"chat":{"complete_events":3,"complete_finish_reasons":["stop"],"eof_events":2,"eof_finish_reasons":[]},"messages":{"complete_events":["message_start","content_block_start","content_block_delta","text","content_block_stop","message_delta","message_stop"],"complete_stop_reason":"end_turn","eof_events":["message_start","content_block_start","content_block_delta","text"],"eof_stop_reason":null},"responses":{"complete_events":["response.created","response.output_text.delta","response.completed"],"complete_has_terminal":true,"eof_events":["response.created","response.output_text.delta"],"eof_has_terminal":false}},"sdk_versions":{"anthropic":"1.13.0","httpx2":"2.13.1","openai":"3.28.0","python":"3.14.8"},"status":"BLOCKED","temporary_containers_cleaned":true}
```

Chat EOF 原始上游记录为 `scenario=eof-no-terminal`, `upstream_terminal=normal_eof_without_protocol_terminal`, `tenant=tenant-a`, `count=1`；同一请求的客户端却正常结束并观察到 `finish_reason=stop`。SDK_LOCAL 的直接对照在 Chat EOF 时只有 2 个 chunk、无 finish reason；Responses EOF 缺 `response.completed`；Messages EOF 缺 `message_stop` 和 stop reason。此证据仅说明此 v1.104.2 Chat 路径，不能泛化为其它协议或错误类型。

## 尚未验证/阻塞

截断 body、超时、SSE 内错误、HTTP 错误、显式 length/incomplete、工具参数校验、两轮工具往返、三协议通过 Proxy、continuation 原样往返、思考签名/推理字段保留、异常/取消资源关闭及并发调度均未验收。尤其 Proxy Chat EOF 路径在 T00 阻塞规则下不能通过；需由根任务决定该具体路径的局部修复、等待上游修复或禁用该路由 streaming。不得把 SDK_LOCAL 或凭据隔离子测标成整体 T00 PASS。
