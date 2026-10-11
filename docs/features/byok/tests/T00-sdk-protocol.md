# Test T00 · 共享网关端到端技术验真

> **T00 BLOCKED / PROBE_SUBSET_ONLY**：下列 11 条原始验收约束完整保留。2026-10-11 的局部探针证明若干 SDK/Proxy 路径，但发现 EOF 被合成正常 stop，且缺个人 Key 时路由到部署默认 Key；PROVIDER_REAL 仍为 NOT_RUN。

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
| T00-08 | 缺 provider Key、错误项目虚拟 Key | 缺 Key fail closed；错误项目凭据在到达 upstream 前被拒绝 | BLOCKED |
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
| 精确功能分支基线 HEAD | 3cd584c95acd52bc533bba0b55eab75b35c41ad5；PR #32 base 为 feat/byok-user-api-keys。工作树未 reset 到基线 |
| T00 探针实现 SHA | 7978a2894dac6b8c0ebdb64614ce877e34c18c4f；仅探针、夹具、自测和 README，无生产适配器或新闻业务调用 |
| Python / OpenAI SDK / Anthropic SDK / httpx2 / LiteLLM / Docker Compose | 3.14.8 / 3.28.0 / 1.13.0 / 2.13.1 / 1.104.2 / 5.5.1；Docker Server 29.7.2 |
| SDK_LOCAL | 三协议真实 SDK complete 与 EOF 直连受控上游路径的协议终态、凭据头和请求计数检查通过 |
| PROXY_LOCAL | OpenAI Chat A/B 同模型并发与 Anthropic Messages 凭据路径通过；错误项目 Key 在上游前拒绝。EOF 完整性及缺 provider Key 两项失败 |
| CLI 整体结果 | 91 项 PASS、3 项 FAIL，退出码 1。三个失败项见下文；CLI 不用固定状态码掩盖结果 |
| PROVIDER_REAL | **NOT_RUN**；未读现有 Key、未发送任何 DeepSeek 请求 |
| 旧聊天/研究/翻译测试 | 历史摘要 219 passed / 3 warnings 的命令、依赖和报告未恢复，本次仍 NOT_RUN；此前缺 chromadb 的 82 passed / 23 failed 不作为产品基线 |
| 旧测试断言 diff | 现有 tests/ 下断言无变化；只新增 tools/byok_t00_probe/test_probe.py 自测，无旧断言放宽 |
| 完整 T00 结论 | **BLOCKED**；工具往返、显式 length/incomplete、截断/超时/SSE/HTTP 错误、取消资源关闭等仍 NOT_RUN |

完整逐项执行输出由 CLI 生成 JSON；其中每项均为 PASS 或 FAIL，含请求计数、终态、认证类别、实际镜像 ID 与清理结果。以下只摘录脱敏汇总和必要事实，不保留任何 Key 或正文。

## SDK_LOCAL 证据

执行命令：

    cd tools/byok_t00_probe
    /tmp/byok-t00-sdk-venv-20261011/bin/python -m unittest -v test_probe

    cd ../..
    /tmp/byok-t00-sdk-venv-20261011/bin/python tools/byok_t00_probe/probe.py

自测输出：12 tests passed。包含错误租户、错误认证 scheme、项目 Key 转发、部署默认 Key fallback、EOF 后合成 stop 等“错误结果必须判 FAIL”的测试。

三协议 SDK_LOCAL 都用已安装的 OpenAI / Anthropic 官方 SDK 直接连接受控 HTTP upstream：

- OpenAI Chat Completions 与 Responses 使用 SDK api_key；上游仅接受 Authorization Bearer，assert x-api-key 不存在。合成 A 凭据匹配，master/project/admin/deployment default 均 false。
- Anthropic Messages 使用 SDK api_key；上游仅接受 x-api-key，Authorization 不作 provider 凭据。合成 A 凭据匹配，其他凭据匹配均 false。
- 三协议完整流均观察到对应终态：Chat finish_reason=stop；Responses response.completed；Messages message_stop 与 end_turn。每条上游请求数为 1。
- 三协议正常 EOF 路径各只有 1 次上游请求。Chat 没有 finish_reason，Responses 没有 response.completed，Messages 没有 message_stop 且没有 stop_reason。此处只证明 SDK_LOCAL 直连路径。

## PROXY_LOCAL 证据

同一个 t00-chat alias 下，两个不同 Proxy project virtual key 与不同 provider key 的并发 Chat 请求均成功：tenant-a / tenant-b 各 1 次上游调用，均匹配其显式请求 provider key。OpenAI 上游观察到 Bearer，x-api-key 不存在；project/master/admin/deployment key 匹配均为 false。两个 SDK 调用在同一线程池中并发执行，模型 alias 相同。

Anthropic Messages Proxy 请求使用 Anthropic SDK auth_token 将 Proxy project virtual key 放在 Authorization，并用 official extra_body 的 api_key 字段提交 provider key。上游观察到 tenant-a、x-api-key 和 message_stop；没有 project/master/admin/default key 转发。

两项拒绝及其上游计数：

| 检查 | SDK 结果 | 上游计数/标签 | 判定 |
| --- | --- | --- | --- |
| 错误 Proxy project virtual key | HTTP 401 | 0 | PASS |
| 缺失用户 provider key，模型部署配置含 synthetic default key | HTTP 401 | 1，tenant=deployment-default，deployment_default_match=true | FAIL；按任一请求触达部署默认 Key 即失败，不以 HTTP 状态作为通过条件 |

EOF 复现路径原始上游只有 1 次请求，终止事实为 normal_eof_without_protocol_terminal；Proxy SDK 正常结束并收到 3 个事件，其中 finish_reason=stop。检查项 PROXY_CHAT_EOF_NOT_SYNTHESIZED_COMPLETE 判 FAIL。该结果只针对 LiteLLM 1.104.2 的此 Chat streaming 路由。

版本决策沿用当前任务固定的 v1.104.2。根据根任务提供的官方源码调研记录，截至 2026-10-11，官方 stable 仍为 v1.104.2，main 相同路径仍在 EOF 缺终态时补 stop，尚无确认的配置修复。本次没有盲目升级，也没有声称其他或未来版本已修复；探针证据只覆盖下面记录的 v1.104.2 容器。

CLI 脱敏摘要：

    {"status":"FAIL","scope":"PROBE_SUBSET_ONLY","passed_check_count":91,"failed_check_count":3,"failed_check_ids":["PROXY_CHAT_EOF_NOT_SYNTHESIZED_COMPLETE","PROXY_MISSING_PROVIDER_FAILS_CLOSED","PROXY_MISSING_PROVIDER_DID_NOT_USE_DEPLOYMENT_DEFAULT"],"provider_real":"NOT_RUN"}

退出码为 1。容器日志与最终 CLI JSON 的 synthetic credential scan 均为 false。成功完整终态、每条上游计数、错误项目 Key 拒绝、缺 Key 默认 fallback、EOF、请求重试配置均由独立检查项判断。

## 镜像、清理与隐私证据

探针使用 Docker context default、内部 Compose 网络及唯一项目名。结束后的 cleanup 检查为 PASS：Compose down 成功，残留 containers=0、networks=0。

运行容器的实际 Image IDs 与固定配置如下。Docker 本次返回的 RepoDigests 数组为空；探针同时记录运行时 Image ID，并验证它与固定 digest 字符串一致以及 Config.Image 仍指向该固定引用：

| 服务 | 固定 Config.Image | 实际运行 Image ID | RepoDigests |
| --- | --- | --- | --- |
| db | postgres@sha256:721873c34ceb9f8d8fc265984940dc982404c105f19ad51be9fdc5970a6080ea | sha256:721873c34ceb9f8d8fc265984940dc982404c105f19ad51be9fdc5970a6080ea | [] |
| proxy | ghcr.io/berriai/litellm@sha256:3d88bd757134a00e8c00237b85a021ab1f6d54abb9c1df750f411dbe7256a500 | sha256:3d88bd757134a00e8c00237b85a021ab1f6d54abb9c1df750f411dbe7256a500 | [] |
| upstream | ghcr.io/berriai/litellm@sha256:3d88bd757134a00e8c00237b85a021ab1f6d54abb9c1df750f411dbe7256a500 | sha256:3d88bd757134a00e8c00237b85a021ab1f6d54abb9c1df750f411dbe7256a500 | [] |

Key 只使用本次合成值。SDK trust_env=false；没有读取 .env、进程环境或旧配置中的 provider Key。CLI 在 stdout 与 proxy/upstream 容器日志内存中检查所有合成项目/provider/master/admin/default Key；两项检查均 PASS，未打印 Key、Authorization、正文或 continuation。官方 cosign 签名验证仍为 NOT_RUN。

## 旧测试对照与未验证项

既有 tests/ 无 diff，未更改任何旧断言。本次没有重跑新闻项目旧聊天/研究/翻译测试，因此不能声称旧回归通过。先前历史记录只留下 219 passed / 3 warnings 摘要；命令、依赖及机器报告未恢复。另一次因隔离环境缺 chromadb 得到 82 passed / 23 failed，也不能替代功能基线；本次不安装旧项目的无关依赖。

显式 length/incomplete、截断 body、超时、SSE 内 error、HTTP 错误注入、半截/非法工具参数、白名单拒绝、Responses 原始 output items continuation、Anthropic thinking/signature、Chat reasoning_content、两轮工具往返、取消后的资源关闭，以及完整旧业务回归均未运行。SDK_LOCAL 与 PROXY_LOCAL 证据彼此分开；本地证据不表示任何真实 provider 兼容。不得进入 T01 或据此扩大成生产变更。

## 后续可选 DeepSeek 有界冒烟（尚未执行）

按当前官方文档，可提议 model=deepseek-flash、官方 OpenAI-compatible base URL https://api.deepseek.com、一次非流式短文本请求、输入上限 128 tokens、max_tokens=32、max_retries=0、请求数 1。DeepSeek 官方定价页当前列出的 peak cache-miss 输入费为 USD 0.30 / 1M tokens，输出费为 USD 1.20 / 1M tokens，因此该上限的估算最多约 USD 0.0000768；建议以 USD 0.01 作为用户确认的单次总预算上限，并在真正执行前再次复核官方价格。来源：[DeepSeek Models & Pricing](https://api-docs.deepseek.com/quick_start/pricing/)。

这只是供确认的测试边界，不是授权或已执行结果。运行前仍需你确认具体模型、合成输入、token/请求上限和预算；Key 只由你在终端隐藏输入，不持久化、不打印。其他厂商仍为 NOT_RUN。
