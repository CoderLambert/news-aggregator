# Test T00 · 共享网关端到端技术验真

> **T00 BLOCKED / GATEWAY_ADMISSION_PROTOTYPE**：下列 11 条原始验收约束完整保留。2026-10-11 的隔离探针增加了仅供验真的准入回调：三类请求的缺失/无效 Key 在部署默认 Key 路由前被拒绝，流式请求也被显式拒绝。独立无回调配置仍复现默认 Key 回落与 Chat EOF 被合成正常 stop。此原型不是产品接入；PROVIDER_REAL 仍为 NOT_RUN。

对应：[T00 Task](../tasks/T00-sdk-protocol.md)。

| 用例 | 场景 / 故障注入 | 正确性约束 | 状态 |
| --- | --- | --- | --- |
| T00-01 | 三协议完整文字和工具终态 | 原始上游、Proxy、SDK 终态相符；满足协议各自完整条件后才成功 | PARTIAL |
| T00-02 | partial 事件后正常 EOF、length/incomplete | 不能合成完整终态；保留原始 incomplete 原因 | BLOCKED |
| T00-03 | 截断 body、超时、SSE error、HTTP error | 安全错误可分类，Key/正文不泄露 | NOT_RUN |
| T00-04 | 半截工具参数、非法 JSON、非白名单工具 | 不派发工具、不成功 | NOT_RUN |
| T00-05 | 两轮工具续接 | 保留 Responses output items、Anthropic thinking/signature、Chat reasoning_content；公开消息不含 continuation | NOT_RUN |
| T00-06 | 不同 Key/model 并发隔离 | 不混用用户凭据、模型、Proxy 项目虚拟 Key 或部署 provider Key | PARTIAL |
| T00-07 | 成功、异常、取消时关闭 stream/response/HTTP 资源 | 所有已打开资源均关闭 | PARTIAL |
| T00-08 | 缺 provider Key、错误项目虚拟 Key | 缺 Key fail closed；错误项目凭据在到达 upstream 前被拒绝 | PARTIAL |
| T00-09 | SDK/Proxy 重试与 fallback 计数 | max_retries=0、num_retries=0、无跨模型 fallback，实际请求数与断言一致 | PARTIAL |
| T00-10 | v1.104.2 原始上游 EOF 与 Proxy 暴露终态对照 | 仅下游 stop/[DONE] 不足以证明原始上游完整；失败按局部风险记录 | BLOCKED |
| T00-11 | 可选 DeepSeek 早期文本冒烟 | 仅在 PROXY_LOCAL 全过、用户确认确切模型/安全合成输入/请求与输出上限/最小预算后执行；不依赖 T00-G、不替代 T13 | NOT_RUN |

## 如何证明

- **SDK_LOCAL**：使用真实安装的官方客户端 SDK 直连受控合成上游，证明 SDK 请求序列化、响应解析和关闭行为；不证明 Proxy 整合或厂商兼容。
- **PROXY_LOCAL**：锁定真实 LiteLLM Proxy 镜像、真实 SDK、受控 HTTP upstream，记录上游原始请求/终态、Proxy 返回、SDK 输出和请求计数。本卡主要技术门槛。
- **PROVIDER_REAL**：默认 NOT_RUN。PROXY_LOCAL 全过后可单独提出一次早期 DeepSeek 文本冒烟，不等待 T00-G；执行前用户必须确认确切模型、安全合成输入、请求数、输出 token 上限和最小费用预算，Key 仅由用户在终端隐藏输入且不持久化/打印。此冒烟只证明所列日期/模型的单次真实路由，不代替 T13 产品矩阵；未获确认不得运行。其他 provider 仍 NOT_RUN。
- **日志**：只保留合成凭据标识、事件名、模型别名、耗时、错误类别和请求计数；禁止打印 Key、完整 Authorization、新闻正文或私有 continuation。
- **基线与断言**：同环境记录任务前相关旧聊天/研究/翻译测试基线。若本卡只改探针/协议契约而没改旧测试，明确写“旧测试断言无 diff”；不得放宽旧断言。

## 执行证据概览

| 项目 | 结果 |
| --- | --- |
| 本卡状态 | **BLOCKED**；本次 CLI 只报告已覆盖子集，T00 完整验收未通过 |
| 精确功能分支基线 HEAD | 3cd584c95acd52bc533bba0b55eab75b35c41ad5；高于用户报告的 ea2ce55（合并 PR #31，父提交 ea2ce55 与 c22b590）；本分支基于 c22b590 的相同树，未 reset 原工作树 |
| 本任务分支 | `task/byok-T00-sdk-protocol`；独立工作区；Draft PR base 为 `feat/byok-user-api-keys` |
| T00 探针实现 SHA（准入原型） | 060445e8d201172fd37724715e4c2587c47fe0b7；仅探针、夹具、自测和 README，无生产适配器或新闻业务调用 |
| DeepSeek 有界入口实现 SHA | eb3c2e30271ec153f7d44fd181d292e202a71d05；仅提供显式 opt-in 的官方 API 单次请求脚本；本次未执行 |
| Python / OpenAI SDK / Anthropic SDK / httpx2 / LiteLLM / Docker Compose | 3.14.8 / 3.28.0 / 1.13.0 / 2.13.1 / 1.104.2 / 5.5.1；Docker Server 29.7.2 |
| SDK_LOCAL | 三协议真实 SDK complete 与 EOF 直连受控上游路径的协议终态、凭据头和请求计数检查通过 |
| PROXY_LOCAL | Chat、Responses、Messages 正常完整请求成功；Chat A/B 同模型并发隔离通过。21 种无效/缺失 Key 组合均为 400 且上游计数 0；三路 `stream=true` 均为 400 且上游计数 0。错误项目 Key 在上游前拒绝。无回调 Chat EOF 风险仍复现 |
| SDK/Proxy 完整子集运行 | 修正前探针 SHA 7978a2894dac6b8c0ebdb64614ce877e34c18c4f 的运行记录为 91 PASS / 3 FAIL；其中镜像证据检查来源错误，已撤销该项 PASS。90 项非镜像 PASS、3 项 FAIL 保留为该版本的路线证据；修正版镜像单项另行实测，未重跑 SDK/Proxy 路径 |
| 镜像证据修订 | IMAGE_EVIDENCE_ONLY：固定引用解析 ID、运行容器 .Image、image inspect IDs、RepoDigests、Config.Image 均已独立记录，检查 PASS；cleanup PASS，残留 0 |
| 准入探针完整子集运行 | 当前工作树代码运行 152 PASS / 1 FAIL，退出码 1。唯一 FAIL 为无回调 Chat EOF 仍在下游显示 `finish_reason=stop`；本次回调拒绝与资源清理检查通过 |
| PROVIDER_REAL | **NOT_RUN**；未读现有 Key、未发送任何 DeepSeek 请求 |
| 旧聊天/研究/翻译测试 | 历史摘要 219 passed / 3 warnings 的命令、依赖和报告未恢复；当前 Python 3.14.8 缺 pytest（`python3 -m pytest --version` 返回 `No module named pytest`），按约束未安装全项目依赖，旧基线仍 NOT_RUN；此前缺 chromadb 的 82 passed / 23 failed 不作为产品基线 |
| 旧测试断言 diff | `tests/` 下没有变化；只新增 tools/byok_t00_probe/test_probe.py 自测，无旧断言放宽 |
| 完整 T00 结论 | **BLOCKED**；本原型只证明限定路由下回调拒绝路径。工具往返、显式 length/incomplete、截断/超时/SSE/HTTP 错误、取消资源关闭及产品接入仍 NOT_RUN |

完整逐项执行输出由 CLI 生成 JSON；其中每项均为 PASS 或 FAIL，含请求计数、终态、认证类别、实际镜像 ID 与清理结果。以下只摘录脱敏汇总和必要事实，不保留任何 Key 或正文。

## SDK_LOCAL 证据

执行命令：

    cd tools/byok_t00_probe
    /tmp/byok-t00-sdk-venv-20261011/bin/python -m unittest -v test_probe

    cd ../..
    /tmp/byok-t00-sdk-venv-20261011/bin/python tools/byok_t00_probe/probe.py

自测输出：14 tests passed。包含错误租户、错误认证 scheme、项目 Key 转发、部署默认 Key fallback、EOF 后合成 stop 等“错误结果必须判 FAIL”的测试。

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

实现只放在隔离 fixture 的只读挂载 `tools/byok_t00_probe/proxy_callback.py`：`CustomLogger.async_pre_call_hook` 只检查请求顶层 `api_key` 是否为非空且非全空白字符串，不接受 metadata 或 HTTP header 替代；拒绝时抛出 `fastapi.HTTPException(400)` 和静态错误码。不使用返回拒绝字符串、moderation hook 或并行拦截。配置中保留合成 deployment default key 作为负控；当前动态验证证明 callback 在该 default key 路由前拒绝。模型 Key 仅通过虚拟 Key 的模型允许列表与非敏感 alias metadata 建立，没有 team/project provider credential override；两个 Proxy 配置都关闭 `forward_client_headers_to_llm_api` 与 `forward_llm_provider_auth_headers`。

本轮本地完整子集命令：

    /tmp/byok-t00-sdk-venv-20261011/bin/python tools/byok_t00_probe/probe.py

| 路由 | 拒绝场景 | 每项结果 | 对应上游调用 |
| --- | --- | --- | --- |
| Chat / Responses / Messages | 缺字段、null、空字符串、全空白、非字符串、仅 metadata 有值、仅 `x-api-key` header 有值（21 个组合） | 全部 HTTP 400，错误码 `BYOK_PROVIDER_KEY_REQUIRED` | 每项 0 |
| Chat / Responses / Messages | `stream=true` 且顶层显式合成 Key（3 项） | 全部 HTTP 400，错误码 `T00_STREAMING_DISABLED` | 每项 0 |
| Chat / Responses / Messages | 正常非流请求 | 完整终态通过；Chat A/B 同 alias 并发使用各自 Key | 每项 1 |

为了保留原始风险复现，独立 `unguarded_proxy` profile 不加载回调：缺 provider Key 时返回 HTTP 401，但上游仍被调用 1 次并观察到 deployment-default；Chat 原始上游无协议终态，而 Proxy SDK 仍观察到 3 个事件和 `finish_reason=stop`。对应 EOF 完整性检查是本轮唯一 FAIL，不能将流拒绝描述为修复了 SDK/Proxy EOF 行为。全运行 152 项 PASS / 1 项 FAIL；日志与最终 JSON 中的合成凭据扫描均为 false，Compose down PASS，残留 containers=0、networks=0。

## DeepSeek 有界入口（已准备，未执行）

入口：`/tmp/byok-t00-sdk-venv-20261011/bin/python tools/byok_t00_probe/deepseek_smoke.py --send-one-request`。未传 `--send-one-request` 时只输出 `NOT_RUN`，不提示或读取 Key。显式启动后只允许一条官方 OpenAI-compatible Chat Completions 请求，固定模型 `deepseek-flash`、固定合成文本 `Reply with exactly the word OK.`、`max_tokens=16`、`reasoning_effort=none`、`max_retries=0`；SDK 传输层计数必须等于 1。Key 由 `getpass` 在 TTY 中隐藏读取，只在进程内存使用，输出仅含脱敏状态、HTTP 类别及计数，不输出响应正文、Key 或原始异常文本。此入口直连 DeepSeek 官方通用 API，尚未执行，也不能替代 T13。官方文档列出 OpenAI 格式 base URL `https://api.deepseek.com`、当前模型 ID `deepseek-flash` 和最高模型输出限制；定价页列出 deepseek-flash 高峰输入 $0.30/M、输出 $1.20/M token，并声明价格可调整。按保守的 16 输入 + 16 输出 token 估算，本次 token 费上界约 **$0.000024**；建议审批预算上限 **$0.01**，以运行时官方价和账户计费为准。参考：[DeepSeek Models & Pricing](https://api-docs.deepseek.com/quick_start/pricing)、[Chat Completions API](https://api-docs.deepseek.com/api/create-chat-completion)。执行前仍须由用户在本对话确认模型、单次请求、16 输出 token 上限和 $0.01 预算；当前 `PROVIDER_REAL=NOT_RUN`。

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

显式 length/incomplete、截断 body、超时、SSE 内 error、HTTP 错误注入、半截/非法工具参数、白名单拒绝、Responses 原始 output items continuation、Anthropic thinking/signature、Chat reasoning_content、两轮工具往返、取消后的资源关闭，以及完整旧业务回归均未运行。SDK_LOCAL 与 PROXY_LOCAL 证据彼此分开；本地证据不表示任何真实 provider 兼容。不得进入 T01 或据此扩大成生产变更。
