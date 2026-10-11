# Test T00 · 共享网关端到端技术验真

> **T00 BLOCKED / GATEWAY_ADMISSION_PROTOTYPE**：最新隔离合成运行 D（2026-10-11）为 `394 PASS / 1 FAIL / 395 checks`。唯一失败仍是无回调 Chat EOF 被 LiteLLM v1.104.2 暴露成 `finish_reason=stop`。Responses 标准 `fc_` item / `call_` call 两轮续接严格通过；旧 `resp_item_` 仅作为独立 foreign-ID 归一化专例。SDK_LOCAL 与 native-stream Proxy 的取消传播检查在显式 2 秒本地观测窗内通过。A9 历史运行 `353 PASS / 4 FAIL` 仍以独立脱敏文件保留，不与 D 混合。仅测试夹具在独立 profile 开放 Responses/Messages native stream；主准入配置仍拒绝 Chat stream。不是产品接入；PROVIDER_REAL 仍为 NOT_RUN。

对应：[T00 Task](../tasks/T00-sdk-protocol.md)。

| 用例 | 场景 / 故障注入 | 正确性约束 | 状态 |
| --- | --- | --- | --- |
| T00-01 | 三协议完整文字和工具终态 | 原始上游、Proxy、SDK 终态相符；满足协议各自完整条件后才成功 | PASS（SDK/Proxy 本地合成） |
| T00-02 | partial 事件后正常 EOF、length/incomplete | 不能合成完整终态；保留原始 incomplete 原因 | PARTIAL |
| T00-03 | 截断 body、超时、SSE error、HTTP error | 安全错误可分类，Key/正文不泄露 | PASS（本地合成） |
| T00-04 | 半截工具参数、非法 JSON、非白名单工具 | 不派发工具、不成功 | PASS（本地合成） |
| T00-05 | 两轮工具续接 | 保留 Responses output items、Anthropic thinking/signature、Chat reasoning_content；公开消息不含 continuation | PASS（本地合成；foreign-ID 另列） |
| T00-06 | 不同 Key/model 并发隔离 | 不混用用户凭据、模型、Proxy 项目虚拟 Key 或部署 provider Key | PARTIAL |
| T00-07 | 成功、异常、取消时关闭 stream/response/HTTP 资源 | 所有已打开资源均关闭 | PARTIAL（本地受控流通过；不证明供应商停止生成/计费） |
| T00-08 | 缺 provider Key、错误项目虚拟 Key | 缺 Key fail closed；错误项目凭据在到达 upstream 前被拒绝 | PASS（本地合成） |
| T00-09 | SDK/Proxy 重试与 fallback 计数 | max_retries=0、num_retries=0、无跨模型 fallback，实际请求数与断言一致 | PASS（本地合成） |
| T00-10 | v1.104.2 原始上游 EOF 与 Proxy 暴露终态对照 | 仅下游 stop/[DONE] 不足以证明原始上游完整；失败按局部风险记录 | BLOCKED |
| T00-11 | 可选 DeepSeek 早期文本冒烟 | 仅在 PROXY_LOCAL 全过、用户确认确切模型/安全合成输入/请求与输出上限/最小预算后执行；不依赖 T00-G、不替代 T13 | NOT_RUN |

## 如何证明

- **SDK_LOCAL**：使用真实安装的官方客户端 SDK 直连受控合成上游，证明 SDK 请求序列化、响应解析和关闭行为；不证明 Proxy 整合或厂商兼容。
- **PROXY_LOCAL**：锁定真实 LiteLLM Proxy 镜像、真实 SDK、受控 HTTP upstream，记录上游原始请求/终态、Proxy 返回、SDK 输出和请求计数。本卡主要技术门槛。
- **PROVIDER_REAL**：默认 NOT_RUN。本轮未执行或申请执行 DeepSeek 冒烟；已有独立入口仍是实验准备，不表示真实兼容。真实测试只在用户明确指示后由用户终端隐藏提供 Key；其他 provider 仍 NOT_RUN。
- **日志**：只保留合成凭据标识、事件名、模型别名、耗时、错误类别和请求计数；禁止打印 Key、完整 Authorization、新闻正文或私有 continuation。
- **基线与断言**：同环境记录任务前相关旧聊天/研究/翻译测试基线。若本卡只改探针/协议契约而没改旧测试，明确写“旧测试断言无 diff”；不得放宽旧断言。

## 执行证据概览

| 项目 | 结果 |
| --- | --- |
| 本卡状态 | **BLOCKED**；本次 CLI 只报告已覆盖子集，T00 完整验收未通过 |
| 功能分支目标基线 HEAD | `ea2ce55ae22e19e1604e88031b824b68f2666cec`，与用户报告一致；未重置原工作树 |
| 本任务实现起点 HEAD | `69e084e39552c5650b930a067b6b79d09e95db34`；分支 `task/byok-T00-sdk-protocol`，独立工作区 |
| T00 本轮实现 SHA | `193d52d0b684c8c47db633a6a93ea96a6690e460`；仅工具、合成夹具、测试与 README；没有生产适配器或新闻业务改动 |
| Draft PR | #33，base `feat/byok-user-api-keys`；维持 open / Draft |
| Python / OpenAI SDK / Anthropic SDK / httpx2 / LiteLLM / Docker Compose | 3.14.8 / 3.28.0 / 1.13.0 / 2.13.1 / 1.104.2 / 5.5.1；Docker Server 29.7.2 |
| 最新 SDK_LOCAL / PROXY_LOCAL 合成运行 D | `394 PASS / 1 FAIL / 395 checks`，CLI exit 1；唯一失败为无回调 Chat EOF 合成 `stop`，没有弱化该断言 |
| 21 种无效/缺失 provider Key | Chat / Responses / Messages 全部 HTTP 400，错误码 `BYOK_PROVIDER_KEY_REQUIRED`，每项上游请求 0 |
| Key/model 隔离 | 同 alias 的 Chat A/B 使用不同显式 provider Key 各 1 次；错配模型的项目 Key 返回 HTTP 403、上游 0；错误项目虚拟 Key 上游 0 |
| 错误与 incomplete | SDK_LOCAL 与 PROXY_LOCAL 三协议 HTTP 503、超时、截断 body 都各 1 次上游请求；length / incomplete / max_tokens 原因保留 |
| Native streaming | 受控本地 Responses / Messages Proxy complete、EOF、incomplete、SSE error 均通过；Chat stream 在主准入配置被拒绝且上游 0 |
| 清理与凭据扫描 | `CLEANUP_COMPOSE_DOWN` 与 `CLEANUP_NO_PROJECT_RESOURCES_LEFT` PASS；containers=0、networks=0；CLI 输出和容器日志没有合成凭据 |
| PROVIDER_REAL | **NOT_RUN**；未读现有 Key、未发送任何 DeepSeek 请求 |
| CI 上下文（用户提供，只读） | HEAD `69e084e` 的 run `38136034042` backend-and-release-gates / frontend 均 success；较早 `38136011186` backend failure。它们不是 T00 手工网关验收结果 |
| 旧聊天/研究/翻译测试基线 | **NOT_RUN**：当前 Python 缺 pytest，frontend 未安装 node_modules；按约束没有安装全项目依赖。历史 `219 passed / 3 warnings` 没有可恢复的命令/报告；缺 chromadb 的 `82 passed / 23 failed` 不作产品基线 |
| 旧测试断言 diff | `tests/` 与 `frontend/tests/` 无 diff；隔离探针自测 24 项通过，没有放宽旧断言 |
| 完整 T00 结论 | **BLOCKED**；Chat EOF 原始终态仍失败，PROVIDER_REAL 和旧新闻回归仍未执行 |

## 最新复测 D（2026-10-11）

实现 SHA：`193d52d0b684c8c47db633a6a93ea96a6690e460`。运行命令：

    /tmp/byok-t00-sdk-venv-20261011/bin/python tools/byok_t00_probe/probe.py

该命令退出码为 1，结果 `394 PASS / 1 FAIL / 395 checks`。唯一失败是 `PROXY_UNGUARDED_CHAT_EOF_NOT_SYNTHESIZED_COMPLETE`：上游有 1 次请求且没有协议终态，Proxy SDK 正常结束并观察到 `finish_reason=stop`。此失败是保留的风险复现。

脱敏 JSON 已提交在 [T00-sdk-protocol-run-d-sanitized.json](../evidence/T00-sdk-protocol-run-d-sanitized.json)；源输出 SHA-256 为 `9d0a034e49a2a7b16746bc41947e9cb02b96f519b55f3807d1d6096961cbb66a`，副本 SHA-256 为 `0dce6b766fd26228f4ade36b92235d8cbcf91bacb132bd2ff79c58c007bda520`。副本的 7 个 SDK/Proxy `public_output.text` 已替换，未包含请求正文、Key、Authorization 值或 Prompt。更早的 A9 原始输出未覆盖（SHA-256 `ef7213c76b62b2ac263d4e934e65d779562f94347d292d0120059edb5c9c093f`）；其脱敏副本 [T00-sdk-protocol-run-a9-sanitized.json](../evidence/T00-sdk-protocol-run-a9-sanitized.json) SHA-256 为 `50326c99d0ece643bb248da2ea729729b496a6b91d786495bf524d70360943cb`，保留原来的 `353 PASS / 4 FAIL / 357 checks`，只作为修正前历史证据。

环境版本：Python 3.14.8、OpenAI SDK 3.28.0、Anthropic SDK 1.13.0、httpx2 2.13.1、LiteLLM Proxy 1.104.2、Docker Compose 5.5.1、Docker Server 29.7.2。PROVIDER_REAL 仍为 `NOT_RUN`。

- Responses 的正常两轮输出使用 `fc_t00_r1/r2` item ID 与 `call_t00_r1/r2` call ID。SDK_LOCAL 和 PROXY_LOCAL 均严格保留 reasoning raw item、encrypted continuation、function-call 全字段及 tool result 对应关系；公开结果只含 `text`。
- 旧 `resp_item_call_r1/r2` 输入单独走 foreign-ID 归一化专例。LiteLLM v1.104.2 移除非 `fc_` item ID；两轮中 `call_id`、名称、参数、状态、reasoning、续接 opaque state 及 tool result 对应关系均保留。该专例不会被报告成标准 Responses tool association 失败。LiteLLM 的 [v1.104.2 transformation 实现](https://github.com/BerriAI/litellm/blob/v1.104.2/litellm/llms/openai/responses/transformation.py#L358-L372)记录了这项 foreign ID 处理。
- Chat 保留 `[DONE]`；Responses 和 Messages 不附加该 sentinel，分别以 `response.completed` 与 `message_stop` 作为协议终态。对应 framing 检查通过。

取消测试使用合成长流、fixture 最长生成 8 秒，并以 **2,000 ms 本地观测窗**判定传播。时间戳由客户端与本机容器写入单调时钟。关闭 SDK 响应后，所有测试都只消费 1 个初始事件，随后 fixture 观测到上游 socket 断开、producer 退出，活动 fixture producer 为 0；native-stream Proxy health endpoint 为 2xx：

| 路径 | 下游关闭至上游断开 | producer 退出延迟 | 断开前成功写入 frame / 关闭后写入 | 窗口末活动 producer | Proxy health |
| --- | ---: | ---: | ---: | ---: | --- |
| SDK Chat | 9.888 ms | 9.919 ms | 3 / 1 | 0 | N/A |
| SDK Responses | 9.983 ms | 10.004 ms | 3 / 1 | 0 | N/A |
| SDK Messages | 9.887 ms | 9.901 ms | 3 / 1 | 0 | N/A |
| Proxy Responses | 8.963 ms | 8.967 ms | 4 / 1 | 0 | HTTP 2xx |
| Proxy Messages | 7.855 ms | 7.860 ms | 3 / 1 | 0 | HTTP 2xx |

frame 数是 fixture 的 socket 写入计数，不能当作 Proxy 内部缓冲帧数，也不证明供应商即时停止生成或计费。这次 Messages cancel 原来附加 `[DONE]` 且用 1 MiB 单帧观察；现改为真实 Messages `message_stop` 语义、重复 32 KiB synthetic delta、socket 断连与 producer 资源观测。

本轮检查：24 项标准库 `unittest` 自测通过；`py_compile`、`docker compose -f tools/byok_t00_probe/compose.yaml config --quiet`、`git diff --check` 通过。Compose `down` 与项目资源核对通过，containers=0、networks=0。

旧新闻聊天/研究/翻译回归仍为 `NOT_RUN`，其原因与历史基线相同：隔离环境没有 pytest 和 frontend `node_modules`，没有为此安装全项目依赖。`tests/` 与 `frontend/tests/` 没有改动；没有放宽旧断言。用户提供的 CI 运行仍只作为独立上下文，不算 T00 手工验收。

## 历史 A9 本地证据（2026-10-11，fixture 修正前）

最终运行命令：

    /tmp/byok-t00-sdk-venv-20261011/bin/python tools/byok_t00_probe/probe.py

本节以下内容完整记录 fixture 修正前的 A9 历史状态。A9 原始 CLI 输出仍位于 `/tmp/byok-t00-run-a9.json`；提交版本为 `../evidence/T00-sdk-protocol-run-a9-sanitized.json`，公开输出文本已脱敏。

以下 `SDK_LOCAL`、`PROXY_LOCAL`、准入与镜像细节均属于 A9 历史快照；最新状态以本页前面的复测 D 与其脱敏 JSON 为准。

本地自测与静态检查：`python3 -m py_compile tools/byok_t00_probe/{probe,upstream,proxy_callback,test_probe}.py`、`cd tools/byok_t00_probe && /tmp/byok-t00-sdk-venv-20261011/bin/python -m unittest -v test_probe`（22 tests passed）、`docker compose -f tools/byok_t00_probe/compose.yaml config --quiet`、`git diff --check` 均通过。全程真实厂商入口未调用，仅使用本地 HTTP fixture 与合成 Key。

- SDK_LOCAL 与 PROXY_LOCAL 中，Chat / Responses / Messages 的 HTTP 503、超时、截断 body 各类错误均显式失败，且每个 marker 只触发 1 个上游请求；SDK `max_retries=0`，Proxy `num_retries=0`、fallbacks 为空。
- 三协议 length / incomplete 均保留：Chat `length`、Responses `incomplete / max_output_tokens`、Messages `max_tokens`。SDK_LOCAL 三协议和独立 native-stream Proxy 的 Responses / Messages 都通过 complete、正常 EOF、incomplete、SSE-error 事件终态检查。
- Chat、Responses、Messages 的两轮合成工具往返在 SDK_LOCAL 均保留 continuation 与结果；Proxy Chat / Messages 也通过，且公开结果只有 text、无 Key/continuation。Proxy Responses 保留 reasoning item 全字段、function-call 的 type/call_id/name/arguments/status 及 tool result，但每轮 function-call item 均缺 `id`（缺字段数=1、额外字段数=0）；同一官方 SDK 直连受控 upstream 时两轮字段全部保留，因而这是 LiteLLM Proxy 路径差异。
- SDK_LOCAL 与 native-stream Proxy 的下游 SDK response 在取消后均关闭。Proxy Responses 上游可观察到取消；Proxy Messages 取消后上游仍成功写完 7 个 SSE frame（含 `[DONE]`），`client_disconnected=false`，未中止上游流，该项保持 FAIL。
- 无回调 `unguarded_proxy` 原始 Chat EOF：上游 1 次请求且无协议终态；Proxy SDK 正常结束并给出 `finish_reason=stop`，保持 FAIL。没有以 downstream stop 作为上游完成证据。
- Native-stream Proxy 使用独立 Compose service/profile；主准入配置仅拒绝 Chat `stream=true`。缺失/无效 Key 的 21 个组合仍在路由前拒绝；项目 Key 请求未授权模型时 HTTP 403、上游计数 0。

全部旧测试状态与本地验收分开记录。用户提供的 CI 运行只说明该 HEAD 的 CI job 状态，不作为上述 T00 手工结论。

完整逐项执行输出由 CLI 生成 JSON；其中每项均为 PASS 或 FAIL，含请求计数、终态、认证类别、实际镜像 ID 与清理结果。以下只摘录脱敏汇总和必要事实，不保留任何 Key 或正文。

## SDK_LOCAL 证据

执行命令：

    cd tools/byok_t00_probe
    /tmp/byok-t00-sdk-venv-20261011/bin/python -m unittest -v test_probe

    cd ../..
    /tmp/byok-t00-sdk-venv-20261011/bin/python tools/byok_t00_probe/probe.py

自测输出：22 tests passed。包含错误租户、错误认证 scheme、项目 Key 转发、部署默认 Key fallback、EOF 后合成 stop、Responses failed SSE event 和 cancel close 等“错误结果必须判 FAIL”的测试。

镜像证据复测命令：

    /tmp/byok-t00-sdk-venv-20261011/bin/python tools/byok_t00_probe/probe.py --images-only

脱敏摘要：`IMAGE_EVIDENCE_ONLY` 总结果 PASS；`IMAGE_FIXED_REFERENCES_RESOLVE_TO_RUNNING_IDS`、`CLEANUP_COMPOSE_DOWN`、`CLEANUP_NO_PROJECT_RESOURCES_LEFT` 均 PASS，残留 containers=0、networks=0。此模式没有发起模型请求。`docker inspect` 只输出容器 ID、`.Image`、`.Config.Image` 和 service label；image ID 与 RepoDigests 来自 `docker image inspect` 并分列记录，未输出 Env。

三协议 SDK_LOCAL 都用已安装的 OpenAI / Anthropic 官方 SDK 直接连接受控 HTTP upstream：

- OpenAI Chat Completions 与 Responses 使用 SDK api_key；上游仅接受 Authorization Bearer，assert x-api-key 不存在。合成 A 凭据匹配，master/project/admin/deployment default 均 false。
- Anthropic Messages 使用 SDK api_key；上游仅接受 x-api-key，Authorization 不作 provider 凭据。合成 A 凭据匹配，其他凭据匹配均 false。
- 三协议完整流均观察到对应终态：Chat finish_reason=stop；Responses response.completed；Messages message_stop 与 end_turn。每条上游请求数为 1。
- 三协议正常 EOF 路径各只有 1 次上游请求。Chat 没有 finish_reason，Responses 没有 response.completed，Messages 没有 message_stop 且没有 stop_reason。此处只证明 SDK_LOCAL 直连路径。

## PROXY_LOCAL 证据

同一个 t00-chat alias 下，两个不同 Proxy project virtual key 与不同 provider key 的并发 Chat 请求均成功：tenant-a / tenant-b 各 1 次上游调用，均匹配其显式请求 provider key。OpenAI 上游观察到 Bearer，x-api-key 不存在；project/master/admin/deployment key 匹配均为 false。两个 SDK 调用在同一线程池中并发执行，模型 alias 相同。

Anthropic Messages Proxy 请求使用 Anthropic SDK auth_token 将 Proxy project virtual key 放在 Authorization，并用 official extra_body 的 api_key 字段提交 provider key。上游观察到 tenant-a、x-api-key 和 message_stop；没有 project/master/admin/default key 转发。

以下两项是前一轮尚未启用准入回调时的历史结果；不要与本轮 GATEWAY_ADMISSION_PROTOTYPE 的拒绝结果混为一谈：

| 检查 | SDK 结果 | 上游计数/标签 | 判定 |
| --- | --- | --- | --- |
| 错误 Proxy project virtual key | HTTP 401 | 0 | PASS |
| 缺失用户 provider key，模型部署配置含 synthetic default key | HTTP 401 | 1，tenant=deployment-default，deployment_default_match=true | FAIL；按任一请求触达部署默认 Key 即失败，不以 HTTP 状态作为通过条件 |

EOF 复现路径原始上游只有 1 次请求，终止事实为 normal_eof_without_protocol_terminal；Proxy SDK 正常结束并收到 3 个事件，其中 finish_reason=stop。检查项 PROXY_CHAT_EOF_NOT_SYNTHESIZED_COMPLETE 判 FAIL。该结果只针对 LiteLLM 1.104.2 的此 Chat streaming 路由。

版本决策沿用当前任务固定的 v1.104.2。根据根任务提供的官方源码调研记录，截至 2026-10-11，官方 stable 仍为 v1.104.2，main 相同路径仍在 EOF 缺终态时补 stop，尚无确认的配置修复。本次没有盲目升级，也没有声称其他或未来版本已修复；探针证据只覆盖下面记录的 v1.104.2 容器。

SDK/Proxy 功能路径的上次脱敏摘要（镜像核验项已撤销，需与下方 IMAGE_EVIDENCE_ONLY 证据分开）：三个失败检查仍为 PROXY_CHAT_EOF_NOT_SYNTHESIZED_COMPLETE、PROXY_MISSING_PROVIDER_FAILS_CLOSED、PROXY_MISSING_PROVIDER_DID_NOT_USE_DEPLOYMENT_DEFAULT。该 SDK/Proxy 全量子集未因镜像证据修订而重跑。容器日志与输出的 synthetic credential scan 均为 false。

## 准入回调原型（GATEWAY_ADMISSION_PROTOTYPE）

固定 LiteLLM v1.104.2 的官方源码核对：共同请求处理器先把 `self.data` 交给 `proxy_logging_obj.pre_call_hook`，之后才调用 `route_request`。本次三路 call type 经源码确认分别为 Chat `acompletion`、Responses `aresponses`、Messages `anthropic_messages`；Messages 与 Responses endpoint 都把请求 body 交给共同处理器。来源：[官方 call-hook 文档](https://docs.litellm.ai/docs/proxy/call_hooks)、[v1.104.2 共同处理器 hook 调用](https://github.com/BerriAI/litellm/blob/v1.104.2/litellm/proxy/common_request_processing.py#L2189-L2194)、[后续 route_request 调用](https://github.com/BerriAI/litellm/blob/v1.104.2/litellm/proxy/common_request_processing.py#L2595-L2603)、[route type 映射](https://github.com/BerriAI/litellm/blob/v1.104.2/litellm/proxy/route_llm_request.py#L76-L86)、[Messages endpoint](https://github.com/BerriAI/litellm/blob/v1.104.2/litellm/proxy/anthropic_endpoints/endpoints.py#L148-L156)、[Responses endpoint](https://github.com/BerriAI/litellm/blob/v1.104.2/litellm/proxy/response_api_endpoints/endpoints.py#L265-L311)。

实现只放在隔离 fixture 的只读挂载 `tools/byok_t00_probe/proxy_callback.py`：`CustomLogger.async_pre_call_hook` 检查 LiteLLM 传入的 pre-call `data` mapping 顶层 `api_key` 是否为非空且非全空白字符串；不接受 metadata 或 HTTP header 替代。该 mapping 不保证是原始、未变更的 HTTP body。拒绝时抛出 `fastapi.HTTPException(400)` 和静态错误码。不使用返回拒绝字符串、moderation hook 或并行拦截。配置中保留合成 deployment default key 作为负控；当前动态验证证明 callback 在该 default key 路由前拒绝。模型 Key 仅通过虚拟 Key 的模型允许列表与非敏感 alias metadata 建立，没有 team/project provider credential override；两个 Proxy 配置都关闭 `forward_client_headers_to_llm_api` 与 `forward_llm_provider_auth_headers`。

本轮本地完整子集命令：

    /tmp/byok-t00-sdk-venv-20261011/bin/python tools/byok_t00_probe/probe.py

| 路由 | 拒绝场景 | 每项结果 | 对应上游调用 |
| --- | --- | --- | --- |
| Chat / Responses / Messages | 缺字段、null、空字符串、全空白、非字符串、仅 metadata 有值、仅 `x-api-key` header 有值（21 个组合） | 全部 HTTP 400，错误码 `BYOK_PROVIDER_KEY_REQUIRED` | 每项 0 |
| 主准入 Proxy Chat | `stream=true` 且顶层显式合成 Key | HTTP 400，错误码 `T00_STREAMING_DISABLED` | 0 |
| 独立 `native-stream` Proxy Responses / Messages | complete、EOF、incomplete、SSE error、取消 | 原生终态/错误事件均有断言；Messages 取消后上游仍完成响应，FAIL | 每项 1 |
| Chat / Responses / Messages | 正常非流请求 | 完整终态通过；Chat A/B 同 alias 并发使用各自 Key | 每项 1 |

为了保留原始风险复现，独立 `unguarded_proxy` profile 不加载回调：缺 provider Key 时返回 HTTP 401，但上游仍被调用 1 次并观察到 deployment-default；Chat 原始上游无协议终态，而 Proxy SDK 仍观察到 3 个事件和 `finish_reason=stop`。对应 EOF 完整性检查仍为 FAIL，不能将流拒绝描述为修复了 SDK/Proxy EOF 行为。最终运行 353 项 PASS / 4 项 FAIL；日志与最终 JSON 中的合成凭据扫描均为 false，Compose down PASS，残留 containers=0、networks=0。

## DeepSeek 直连诊断（代码已准备，真实调用未执行）

### 当前准入与分离记录

T00 当前仍为 **BLOCKED**。任务卡要求核心 PROXY_LOCAL 全部通过后，才可申请经 LiteLLM 的 DeepSeek 早期真实调用；最新运行 D 在实现 SHA `25ca792008676889de64cc069ef36c6452983883` 为 `394 PASS / 1 FAIL / 395 checks`。失败项 `PROXY_UNGUARDED_CHAT_EOF_NOT_SYNTHESIZED_COMPLETE` 记录了上游正常 EOF、无协议终态，而 LiteLLM v1.104.2 向 SDK 暴露 `finish_reason=stop`。该失败未改写或屏蔽。

因此目前只准备了可选的 **直连诊断**，不调用 LiteLLM，也不能代表 T00-11 通过。真实 LiteLLM 路径仍是 `BLOCKED / NOT_RUN`；没有提供或执行它的收费命令。若用户选择直连诊断，其结果单独记为 DeepSeek direct baseline，不改变 T00、PROXY_LOCAL 或 T13 状态。未来网关路径必须另有记录；直连与网关请求各自独立计数。

### 官方资料核验（2026-10-12）

- 官方 [Models & Pricing](https://api-docs.deepseek.com/quick_start/pricing/) 与 [model list](https://api-docs.deepseek.com/api/list-models/) 当前列出模型 ID `deepseek-flash`，版本名 DeepSeek-V4.1-Flash；OpenAI 格式 base URL 为 `https://api.deepseek.com`，最大输出为 384K tokens。这个上限不是探针上限。
- 官方 [Chat Completions API](https://api-docs.deepseek.com/api/create-chat-completion/) 定义 `max_tokens`、JSON response format 和 Chat Completions 响应终态；[Thinking Mode](https://api-docs.deepseek.com/guides/thinking_mode/) 说明 thinking 默认启用，且 OpenAI SDK 通过 `extra_body={"thinking":{"type":"disabled"}}` 关闭。thinking 模式下 `temperature` 不生效，因此探针不发送 `temperature`。
- Flash 当前每百万输入 tokens（cache miss）为非高峰 `$0.15`、高峰 `$0.30`；每百万输出 tokens 为非高峰 `$0.60`、高峰 `$1.20`。高峰为周一至周五 01:00–04:00、06:00–10:00 UTC，排除中国法定节假日；其余时段按非高峰价。官方注明价格可能调整，费用按真实 usage 计。

### 直连代码与用户执行参数

| 项目 | 记录 |
| --- | --- |
| 探针代码提交 | `02a693db37e6aed07ad3a7d46304a220a2f5a5f6`（当前 Draft PR #33 的代码提交；执行前仍核对最终 HEAD） |
| 环境 | Linux 7.2.5-3-omarchy x86_64；Python 3.14.8；OpenAI SDK 3.28.0；httpx2 2.13.1；依赖按 `tools/byok_t00_probe/requirements.lock` 安装于隔离 venv |
| 调用路径 | OpenAI Chat Completions SDK → `https://api.deepseek.com`；非流式；只测 DeepSeek `deepseek-flash` |
| 输入 | 固定、无新闻或隐私内容的 101 字符 ASCII 指令：`Return only a JSON object with exactly these fields: {"probe_id":"byok-deepseek-smoke-v1","ok":true}.`；实际 token 数由响应 usage 记录，未在本机 tokenizer 上核验 |
| 输出/推理限制 | `max_tokens=24`；thinking 显式 disabled；不请求推理；若 usage 返回 reasoning tokens 则记录；SDK `max_retries=0`，HTTP redirect 关闭，30 秒 timeout |
| 请求数 | 该命令最多发起 1 次直连 HTTP 请求；LiteLLM 路径为 0。`request_count` 是 SDK HTTP request hook 观察到的发送尝试数，不声称上游一定已处理或计费 |
| 回答断言 | 非空 JSON object，且恰好包含 `probe_id="byok-deepseek-smoke-v1"`、`ok=true`；还要求唯一 choice 的 `finish_reason=stop`。自由文本、空响应、非法 JSON、额外/缺失字段、`length`、缺少终态、请求数不是 1 均失败 |
| 安全输出 | 只输出状态、固定模型/协议、终态、断言类别、请求数与 usage；不输出 Key、回答正文、请求头、异常文本；Key 只由 `getpass` 隐藏输入并留在进程内，不放进命令参数、环境变量或文件 |
| 当前真实结果 | `NOT_RUN`；本次只用合成 SDK transport 测试，未访问 `api.deepseek.com` |

按高峰未缓存价格，暂以短提示词不超过约 50 input tokens、最多 24 output tokens 估算，单次直连约 `$0.000044`；非高峰约 `$0.000022`。这是预算估算，不是保证上限：实际 tokenizer/JSON 模式计费、价格变化，以及请求超时后上游仍处理等情况都可能改变账单。thinking 已关闭，预期 reasoning tokens 为 0；最终以厂商 usage 为准。

以下命令只运行直连诊断，需由用户在本地交互终端选择执行。默认启动不发请求；脚本不会自动运行收费调用：

```sh
cd /home/lambert/Documents/Codex/2026-10-11/task-2/news-aggregator-t00/tools/byok_t00_probe
/tmp/byok-t00-smoke-20261012/bin/python deepseek_smoke.py --send-one-request
```

本次未运行上述收费命令。隔离合成验证环境使用 `/tmp/byok-t00-smoke-20261012`，Python 3.14.8；通过下面的命令运行 24 项既有探针 evaluator 自测和 17 项 DeepSeek 诊断测试：

```sh
cd /home/lambert/Documents/Codex/2026-10-11/task-2/news-aggregator-t00/tools/byok_t00_probe
/tmp/byok-t00-smoke-20261012/bin/python -m unittest -v test_probe test_deepseek_smoke
```

结果：`Ran 41 tests ... OK`。测试覆盖固定的 DeepSeek SDK 请求字段、JSON 结果断言、空/非法/错误结构、缺失或不完整终态、零/多次请求、HTTP 错误脱敏、资源关闭、无 TTY/空 Key/取消输入，以及默认不请求路径。实际 OpenAI SDK 使用本地 `httpx2.MockTransport`；没有访问 DeepSeek 或启动 LiteLLM。另有 `py_compile` 与 `git diff --check` 通过；默认 CLI 输出 `{"direct_baseline":"NOT_RUN","request_count":0,"requires":"--send-one-request"}` 并以 0 退出。

这条命令对应 1 次 DeepSeek 直连请求。若以后另行准入 LiteLLM 路径，它将是另一条独立请求，双路径总数为 2；当前 PROXY_LOCAL 失败，所以现在没有第二条用户执行命令，也没有把直连诊断包装为网关验收。

本地合成自测命令：

```sh
cd /home/lambert/Documents/Codex/2026-10-11/task-2/news-aggregator-t00/tools/byok_t00_probe
/tmp/byok-t00-smoke-20261012/bin/python -m unittest -v test_probe test_deepseek_smoke
```

真实 DeepSeek 调用仍须由用户本人执行，且输出需单独记录；本次不读取或请求任何 Key。

## 镜像、清理与隐私证据

镜像证据由单独 IMAGE_EVIDENCE_ONLY 模式复测；未发起 SDK inference。探针只用 Docker format 输出 container ID、.Image、.Config.Image 和 service label，不读取或输出 Env。然后对每个运行容器的 .Image ID 及其固定 Config.Image 分别执行 docker image inspect，只取 .Id 与 .RepoDigests。

通过条件为：运行时 image inspect .Id 等于容器 .Image；固定引用解析出的 image inspect .Id 也等于容器 .Image；.Config.Image 等于该服务的固定引用。RepoDigests 被单独记录，不与 config/image ID 直接比较。

| 服务 | Container ID | 容器 .Image | 容器 .Config.Image | 运行时 image inspect .Id | 运行时 RepoDigests | 固定引用解析 .Id | 固定引用 RepoDigests |
| --- | --- | --- | --- | --- | --- | --- | --- |
| db | 564049b447d01ad8868a993e16b96bfe80e32a4a2fcf30dddc34e3bd4a56d313 | sha256:721873c34ceb9f8d8fc265984940dc982404c105f19ad51be9fdc5970a6080ea | postgres@sha256:721873c34ceb9f8d8fc265984940dc982404c105f19ad51be9fdc5970a6080ea | sha256:721873c34ceb9f8d8fc265984940dc982404c105f19ad51be9fdc5970a6080ea | [postgres@sha256:721873c34ceb9f8d8fc265984940dc982404c105f19ad51be9fdc5970a6080ea] | sha256:721873c34ceb9f8d8fc265984940dc982404c105f19ad51be9fdc5970a6080ea | [postgres@sha256:721873c34ceb9f8d8fc265984940dc982404c105f19ad51be9fdc5970a6080ea] |
| proxy | d70fed2df3f0974804e89de448a26c6c4ce9cc6b1c226d26e271781a3ee4c5e1 | sha256:3d88bd757134a00e8c00237b85a021ab1f6d54abb9c1df750f411dbe7256a500 | ghcr.io/berriai/litellm@sha256:3d88bd757134a00e8c00237b85a021ab1f6d54abb9c1df750f411dbe7256a500 | sha256:3d88bd757134a00e8c00237b85a021ab1f6d54abb9c1df750f411dbe7256a500 | [ghcr.io/berriai/litellm@sha256:3d88bd757134a00e8c00237b85a021ab1f6d54abb9c1df750f411dbe7256a500] | sha256:3d88bd757134a00e8c00237b85a021ab1f6d54abb9c1df750f411dbe7256a500 | [ghcr.io/berriai/litellm@sha256:3d88bd757134a00e8c00237b85a021ab1f6d54abb9c1df750f411dbe7256a500] |
| unguarded_proxy | b4aea003749c35a1298507e29e75bc0fea8d73d17cdb59a9d412ed79fad6efca | sha256:3d88bd757134a00e8c00237b85a021ab1f6d54abb9c1df750f411dbe7256a500 | ghcr.io/berriai/litellm@sha256:3d88bd757134a00e8c00237b85a021ab1f6d54abb9c1df750f411dbe7256a500 | sha256:3d88bd757134a00e8c00237b85a021ab1f6d54abb9c1df750f411dbe7256a500 | [ghcr.io/berriai/litellm@sha256:3d88bd757134a00e8c00237b85a021ab1f6d54abb9c1df750f411dbe7256a500] | sha256:3d88bd757134a00e8c00237b85a021ab1f6d54abb9c1df750f411dbe7256a500 | [ghcr.io/berriai/litellm@sha256:3d88bd757134a00e8c00237b85a021ab1f6d54abb9c1df750f411dbe7256a500] |
| upstream | 449dcf1d1a0a81445a40bf99f594674f611428a9cff4725a7892012d9612daf5 | sha256:3d88bd757134a00e8c00237b85a021ab1f6d54abb9c1df750f411dbe7256a500 | ghcr.io/berriai/litellm@sha256:3d88bd757134a00e8c00237b85a021ab1f6d54abb9c1df750f411dbe7256a500 | sha256:3d88bd757134a00e8c00237b85a021ab1f6d54abb9c1df750f411dbe7256a500 | [ghcr.io/berriai/litellm@sha256:3d88bd757134a00e8c00237b85a021ab1f6d54abb9c1df750f411dbe7256a500] | sha256:3d88bd757134a00e8c00237b85a021ab1f6d54abb9c1df750f411dbe7256a500 | [ghcr.io/berriai/litellm@sha256:3d88bd757134a00e8c00237b85a021ab1f6d54abb9c1df750f411dbe7256a500] |

本次四服务 IMAGE_EVIDENCE_ONLY 的 IMAGE_FIXED_REFERENCES_RESOLVE_TO_RUNNING_IDS、CLEANUP_COMPOSE_DOWN、CLEANUP_NO_PROJECT_RESOURCES_LEFT 均 PASS；四服务镜像 ID 与固定引用解析匹配，残留 containers=0、networks=0。RepoDigests 来自 image inspect 输出，不再使用 container inspect 上的 RepoDigests 字段。前一版把容器 .Image ID 字符串与固定 digest 字符串直接相等作为证据，该判断已撤销。

此前 SDK/Proxy 完整子集运行在本任务自己的唯一 Compose 项目下 cleanup PASS。Key 只使用本次合成值。SDK trust_env=false；没有读取 .env、进程环境或旧配置中的 provider Key。前次该运行的 proxy/upstream 容器日志及 CLI JSON synthetic credential scan 均为 false，未打印 Key、Authorization、正文或 continuation。官方 cosign 签名验证仍为 NOT_RUN。

## 旧测试对照与未验证项

既有 tests/ 无 diff，未更改任何旧断言。本次没有重跑新闻项目旧聊天/研究/翻译测试，因此不能声称旧回归通过。先前历史记录只留下 219 passed / 3 warnings 摘要；命令、依赖及机器报告未恢复。另一次因隔离环境缺 chromadb 得到 82 passed / 23 failed，也不能替代功能基线；本次不安装旧项目的无关依赖。

历史 A9 的 Responses `resp_item_` 与 Messages cancel 失败已在上方 A9 文件中保留。最新 D 中，标准 Responses `fc_`/`call_` 与 foreign-ID 归一化专例均通过，受控本地取消传播通过；无回调 Chat EOF 的失败继续保留。PROVIDER_REAL 与旧新闻聊天/研究/翻译回归仍未运行。本地合成结果不表示任何真实 provider 兼容，也未改生产调用。
