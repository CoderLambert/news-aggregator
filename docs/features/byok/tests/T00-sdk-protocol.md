# Test T00 · 共享网关端到端技术验真

> **T00 PASS / GATEWAY_ADMISSION_PROTOTYPE**：最新隔离合成运行 L（2026-10-12）为 `407 PASS / 0 FAIL / 407 checks`，CLI 标记 `PARTIAL`，因为该 CLI 不包含现有业务回归和真实 provider 兼容。T00-01 至 T00-10 的本地技术门槛和当前完整业务 CI 均通过。v1.104.2 的 unguarded Chat EOF 风险仍被原样复现：上游无协议终态而 SDK 收到 `finish_reason=stop`；受保护准入路径对此请求返回 HTTP 400 `T00_STREAMING_DISABLED`，上游计数为 0。该结果证明特定路径被关闭，不表示 LiteLLM 已修复或 Chat streaming 兼容。锁定镜像的官方 Cosign 签名和实际 digest 已验证。Responses 标准 `fc_` item / `call_` call 两轮续接严格通过；旧 `resp_item_` 仅作为独立 foreign-ID 归一化专例。SDK_LOCAL 与 native-stream Proxy 的取消传播检查在显式 2 秒本地观测窗内通过。A9 历史运行 `353 PASS / 4 FAIL` 仍以独立脱敏文件保留，不与 D/E/F/L 混合。用户已报告 DeepSeek 直连基线 PASS（1 次请求）；真实经 LiteLLM T00-11 仍为 NOT_RUN。

对应：[T00 Task](../tasks/T00-sdk-protocol.md)。

| 用例 | 场景 / 故障注入 | 正确性约束 | 状态 |
| --- | --- | --- | --- |
| T00-01 | 三协议完整文字和工具终态 | 原始上游、Proxy、SDK 终态相符；满足协议各自完整条件后才成功 | PASS（SDK/Proxy 本地合成） |
| T00-02 | partial 事件后正常 EOF、length/incomplete | 不能合成完整终态；保留原始 incomplete 原因 | PASS（Chat streaming 准入拒绝；Responses/Messages native stream 与三协议 incomplete 保留） |
| T00-03 | 截断 body、超时、SSE error、HTTP error | 安全错误可分类，Key/正文不泄露 | PASS（本地合成） |
| T00-04 | 半截工具参数、非法 JSON、非白名单工具 | 不派发工具、不成功 | PASS（本地合成） |
| T00-05 | 两轮工具续接 | 保留 Responses output items、Anthropic thinking/signature、Chat reasoning_content；公开消息不含 continuation | PASS（本地合成；foreign-ID 另列） |
| T00-06 | 不同 Key/model 并发隔离 | 不混用用户凭据、模型、Proxy 项目虚拟 Key 或部署 provider Key | PASS（不同 tenant 的 Chat A/B 与 Messages B 并发；上游共同重叠 198.372 ms） |
| T00-07 | 成功、异常、取消时关闭 stream/response/HTTP 资源 | 所有已打开资源均关闭 | PASS（SDK_LOCAL 与 native-stream Proxy 本地资源；不证明供应商端停止生成/计费） |
| T00-08 | 缺 provider Key、错误项目虚拟 Key | 缺 Key fail closed；错误项目凭据在到达 upstream 前被拒绝 | PASS（本地合成） |
| T00-09 | SDK/Proxy 重试与 fallback 计数 | max_retries=0、num_retries=0、无跨模型 fallback，实际请求数与断言一致 | PASS（本地合成） |
| T00-10 | v1.104.2 原始上游 EOF 与 Proxy 暴露终态对照 | 仅下游 stop/[DONE]不足以证明原始上游完整；受保护路径必须禁用该路由并证明上游计数为 0，负控风险单独保留 | PASS（风险复现；Chat streaming 被拒绝） |
| T00-11 | 可选、经 LiteLLM 的 DeepSeek 早期文本冒烟 | 仅在 PROXY_LOCAL 全过、用户确认确切模型/安全合成输入/请求与输出上限/最小预算后执行；不依赖 T00-G、不替代 T13 | NOT_RUN（直连基线另记） |

## 如何证明

- **SDK_LOCAL**：使用真实安装的官方客户端 SDK 直连受控合成上游，证明 SDK 请求序列化、响应解析和关闭行为；不证明 Proxy 整合或厂商兼容。
- **PROXY_LOCAL**：锁定真实 LiteLLM Proxy 镜像、真实 SDK、受控 HTTP upstream，记录上游原始请求/终态、Proxy 返回、SDK 输出和请求计数。本卡主要技术门槛。
- **DeepSeek 直连基线**：用户于 2026-10-12 报告独立 OpenAI SDK 直连诊断 PASS，1 次请求；没有执行 LiteLLM 路径。该结果只证明这一次指定模型、输入和参数的直连基线，不能证明 LiteLLM 集成、流式、工具调用或其他 provider 兼容。经 LiteLLM 的 T00-11 与其他 provider 测试仍为 NOT_RUN。
- **日志**：只保留合成凭据标识、事件名、模型别名、耗时、错误类别和请求计数；禁止打印 Key、完整 Authorization、新闻正文或私有 continuation。
- **基线与断言**：同环境记录任务前相关旧聊天/研究/翻译测试基线。若本卡只改探针/协议契约而没改旧测试，明确写“旧测试断言无 diff”；不得放宽旧断言。

## 执行证据概览

| 项目 | 结果 |
| --- | --- |
| 本卡状态 | **PASS**；T00-01 至 T00-10 本地验收、镜像签名校验与当前完整业务 CI 均通过。可选 T00-11 未运行 |
| 功能分支目标基线 HEAD | `ea2ce55ae22e19e1604e88031b824b68f2666cec`，与用户报告一致；未重置原工作树 |
| 本任务实现起点 HEAD | `69e084e39552c5650b930a067b6b79d09e95db34`；分支 `task/byok-T00-sdk-protocol`，独立工作区 |
| T00 本轮实现 SHA | `36a76c85470978bb6a2694a66e78599e648ea14c`；仅隔离探针、合成夹具、测试与文档；没有生产适配器或新闻业务改动 |
| Draft PR | #33，base `feat/byok-user-api-keys`；维持 open / Draft |
| Python / OpenAI SDK / Anthropic SDK / httpx2 / LiteLLM / Docker Compose | 3.14.8 / 3.28.0 / 1.13.0 / 2.13.1 / 1.104.2 / 5.5.1；Docker Server 29.7.2 |
| LiteLLM v1.104.2 image signature | **PASS**；Cosign v3.0.2 使用官方固定提交公钥校验，签名 digest 与锁定的 `sha256:3d88…a500` 一致；[脱敏证据](../evidence/T00-litellm-v1.104.2-cosign.json) |
| 最新 SDK_LOCAL / PROXY_LOCAL 合成运行 L | `407 PASS / 0 FAIL / 407 checks`，CLI exit 0、状态 `PARTIAL`；原始 unguarded Chat EOF 风险仍保留，受保护路径 HTTP 400 且上游 0 |
| 21 种无效/缺失 provider Key | Chat / Responses / Messages 全部 HTTP 400，错误码 `BYOK_PROVIDER_KEY_REQUIRED`，每项上游请求 0 |
| Key/model 隔离 | Chat A、Chat B、Messages B 三请求并发，各 1 次；tenant 与显式 provider Key 全匹配，两个模型别名对应的项目虚拟 Key 均受限；fixture 共同重叠 `198.372 ms`；错配模型项目 Key 返回 HTTP 403、上游 0，错误项目虚拟 Key 上游 0 |
| 错误与 incomplete | SDK_LOCAL 与 PROXY_LOCAL 三协议 HTTP 503、超时、截断 body 都各 1 次上游请求；length / incomplete / max_tokens 原因保留 |
| Native streaming | 受控本地 Responses / Messages Proxy complete、EOF、incomplete、SSE error 均通过；Chat stream 在主准入配置被拒绝且上游 0 |
| 清理与凭据扫描 | `CLEANUP_COMPOSE_DOWN` 与 `CLEANUP_NO_PROJECT_RESOURCES_LEFT` PASS；containers=0、networks=0；CLI 输出和容器日志没有合成凭据 |
| DeepSeek 直连基线 | **PASS（用户报告）**；1 次 SDK HTTP 请求尝试，prompt=57 / completion=19 tokens，`finish_reason=stop`，JSON 字段断言通过；执行时间未提供；未读取 Key |
| 经 LiteLLM 的 T00-11 / 网关真实请求 | **NOT_RUN**；目前只有本地合成 PROXY_LOCAL 证据，未发送真实 provider 网关请求 |
| 其他 provider 的 PROVIDER_REAL | **NOT_RUN** |
| 最新 T00 PR head CI | HEAD `8b02bf439ab92d8f4dcbc660468484a7625a864e` 的 frontend、backend-and-release-gates 最终均通过；runs [38172136755](https://github.com/CoderLambert/news-aggregator/actions/runs/38172136755) 与 [38172140235](https://github.com/CoderLambert/news-aggregator/actions/runs/38172140235)，backend 各 `838 passed / 2 warnings`。run `38172140235` 首次尝试出现既有 SSE disconnect 测试的 SQLite `OperationalError`，未改代码或断言后重跑该失败 job 通过 |
| T00 基线 CI 上下文（用户提供，只读） | HEAD `69e084e` 的 run `38136034042` backend-and-release-gates / frontend 均 success；较早 `38136011186` backend failure。它们不是 T00 手工网关验收结果 |
| 旧聊天/研究/翻译测试基线 | 前一 T00 PR head `29d1fd9` 的两次 backend CI 均为 `838 passed / 2 warnings`，另有两次 frontend、release gates 均通过。早先 head `2ef40cd` 的重复 CI 曾分别出现一个订阅任务 SQLite `OperationalError`，随后在无业务代码改动的 head 上全量重跑通过；功能分支基线 `69e084e` 的 CI 也为 `838 passed / 2 warnings`。隔离工作区缺 pytest 和 frontend `node_modules`，未安装全项目依赖。历史 `219 passed / 3 warnings` 没有可恢复命令/报告；缺 chromadb 的 `82 passed / 23 failed` 不作产品基线 |
| 旧测试断言 diff | `tests/` 与 `frontend/tests/` 无 diff；隔离探针、DeepSeek 直连及网关烟测自测共 56 项通过，没有放宽旧断言 |
| 完整 T00 结论 | **PASS**；T00-01 至 T00-10、镜像验签和完整业务 CI 均通过。T00-10 风险通过关闭 Chat streaming 路径隔离；可选 T00-11 与其他真实 provider 调用未运行 |

## 最新复测 L（2026-10-12）

实现 SHA：`36a76c85470978bb6a2694a66e78599e648ea14c`。运行命令：

    /tmp/byok-t00-smoke-20261012/bin/python tools/byok_t00_probe/probe.py

结果：`407 PASS / 0 FAIL / 407 checks`，退出码 0，CLI 状态 `PARTIAL`；本 CLI 未覆盖完整旧业务回归和真实 provider 兼容性。

新增 `t00-deepseek-smoke` 合成模型别名使用 LiteLLM 的 `deepseek/deepseek-flash` provider 路由及受控本地 upstream。真实 OpenAI SDK 按 DeepSeek 烟测参数发出一条请求：101 字符合成 prompt、`max_tokens=24`、JSON object、`thinking` disabled。upstream 记录恰好一条请求，tenant 与请求级合成 provider Key 匹配，SDK 收到 `finish_reason=stop` 且预期 JSON 字段断言通过。相同路由不带请求级 provider Key 时返回 HTTP 400 `BYOK_PROVIDER_KEY_REQUIRED`，上游请求为 0；配置中的固定值只是无效 sentinel。该运行全程未连接 DeepSeek 或其他真实 provider。

新建网关脚本另做了不调用模型的启动预检：临时 LiteLLM Proxy 健康就绪、loopback 端口绑定、内存生成受限项目 virtual key，`provider_request_count=0`，随后 Compose 清理通过。合并探针自测 `test_probe test_deepseek_smoke test_deepseek_gateway_smoke` 为 56 tests passed；`py_compile`、Compose config 和 `git diff --check` 均通过。本地全量运行的 `CLEANUP_COMPOSE_DOWN` 与 `CLEANUP_NO_PROJECT_RESOURCES_LEFT` 通过，containers=0、networks=0；日志和 CLI 输出无合成凭据。`provider_real` 仍为 `NOT_RUN`。

脱敏机器结果：[T00-sdk-protocol-run-l-sanitized.json](../evidence/T00-sdk-protocol-run-l-sanitized.json)，源输出 SHA-256 `8fe6fe62c1a2808e877985492df36c65bdae2909fe56005fd48b903157492166`，脱敏副本 SHA-256 `679eff4382dd94c69c7ad39a78f4a0c650232e27426c09b8655dcaaa4344a192`。副本只保留检查 ID/状态、白名单路由事实和版本；不含 prompt、Key 或响应正文。

## T00-11 已准备，等待用户确认

拟执行范围只有一条真实 DeepSeek 请求：模型 `deepseek-flash`（DeepSeek-V4.1-Flash），OpenAI Chat Completions、非流式，官方 base URL `https://api.deepseek.com`。输入固定为 101 字符安全合成文本：

```text
Return only a JSON object with exactly these fields: {"probe_id":"byok-deepseek-smoke-v1","ok":true}.
```

预期回答严格为 `{"probe_id":"byok-deepseek-smoke-v1","ok":true}`。请求上限为 `max_tokens=24`，`response_format={"type":"json_object"}`，`thinking={"type":"disabled"}`，30 秒 timeout，SDK retries=0、LiteLLM retries=0、fallbacks=0。脚本计数的是发往 loopback Proxy 的 SDK HTTP 尝试，目标为恰好 1 次；实际 provider 上游次数没有独立计数器，因而不能独立核实。响应必须有一个预期 JSON 对象且 SDK 可见 `finish_reason=stop` 才通过。Key 在 Proxy 启动后由本地终端 `getpass` 隐藏读取，仅在进程内使用，不写入配置或输出。此命令会产生一条真实 provider 请求，助手未执行；用户需先确认上述模型、输入、一次请求、24-token 输出上限与预算后，亲自在终端运行：

```sh
cd tools/byok_t00_probe
/tmp/byok-t00-smoke-20261012/bin/python deepseek_gateway_smoke.py --send-one-request
```

按 2026-10-12 DeepSeek 官方价目，Flash cache-miss 输入为 off-peak `$0.15/M`、peak `$0.30/M`，输出为 off-peak `$0.60/M`、peak `$1.20/M`；peak 适用时间为工作日 UTC 01:00–04:00 和 06:00–10:00（中国法定节假日除外）。以用户直连基线观测的 57 输入 tokens、输出上限 24 tokens、peak 价格估算，新网关请求约 `$0.0000459`，按 `$0.00005` 作为估算上限；用户已完成的直连请求按 57/19 tokens 同价估算约 `$0.0000399`，两条路径合计约 `$0.0000858`（约 `$0.00009`）。这是估值，不是账单硬上限；实际 token 数、价格更新、缓存和超时后的 provider 处理都可能改变扣费，临时 virtual key 的 `$0.01` max budget 也不等同于 provider 账单硬上限。[DeepSeek Models & Pricing](https://api-docs.deepseek.com/quick_start/pricing/)、[Chat Completions API](https://api-docs.deepseek.com/api/create-chat-completion/)、[Thinking Mode](https://api-docs.deepseek.com/guides/thinking_mode/)。

在用户运行并提供脱敏结果前，T00-11 / `PROVIDER_REAL` 保持 `NOT_RUN`，不能从本地合成上游结果推断真实 DeepSeek 兼容性。

## 历史复测 F（2026-10-12）

实现 SHA：`74d9ca29fa6b07c7b185e7b19c16ab14546992e3`。运行命令：

    /tmp/byok-t00-smoke-20261012/bin/python tools/byok_t00_probe/probe.py

结果：`396 PASS / 0 FAIL / 396 checks`，退出码 0，CLI 状态 `PARTIAL`，未覆盖项为完整旧业务回归和 `PROVIDER_REAL` 兼容性。

T00-06 新增一组真正并发的三请求验收：tenant-a 使用 `t00-chat`，tenant-b 同时使用 `t00-chat` 和 `t00-messages`，后两项通过各自模型范围受限的项目虚拟 Key 发出。上游 fixture 为每项记录单调时钟服务区间，三项均各触发一次，tenant/provider Key 均匹配，模型别名和协议路由正确，服务区间共同重叠 `198.372 ms`。这证明并发执行和凭据/模型路由隔离，不只依赖线程池提交顺序。

T00-02 的 EOF/incomplete 检查通过：SDK_LOCAL 三协议 EOF 未合成完整终态；Proxy Responses/Messages native stream EOF 未给出完成终态；Chat streaming 在受保护准入路径被 HTTP 400 `T00_STREAMING_DISABLED` 拒绝且上游计数为 0。Chat 的 unguarded 负控仍保留 v1.104.2 的 `finish_reason=stop` 风险；三协议 length/incomplete 原因均被保留。T00-07 的本地取消用例在 2,000 ms 观测窗内通过：SDK_LOCAL Chat/Responses/Messages 与 Proxy Responses/Messages 均关闭下游响应、观测到上游断开和 producer 退出，窗口末活动 producer 为 0，Proxy health 仍为 HTTP 2xx。该结果只证明本地 SDK/Proxy/fixture 资源释放，不表示供应商端停止生成或计费。

本次 Compose 清理 `CLEANUP_COMPOSE_DOWN` 与 `CLEANUP_NO_PROJECT_RESOURCES_LEFT` 均 PASS，残留 containers=0、networks=0；日志与 CLI 输出均未包含合成凭据。自测 `test_probe` 为 30 tests passed；`py_compile`、Compose 配置校验和 `git diff --check` 通过。未发送真实 provider 请求，未读取或使用 DeepSeek Key。

脱敏机器结果：[T00-sdk-protocol-run-f-sanitized.json](../evidence/T00-sdk-protocol-run-f-sanitized.json)，源输出 SHA-256 `2050f6ceb63143fb1404e9a118ff5956e9d98c1d471888a02f2d8fedcc672975`，脱敏副本 SHA-256 `6ec4bd6f4fd5455165cb3330e77812455ccf0c335f1eba2b7a96bda835e28277`。七个 SDK/Proxy `public_output.text` 字段已替换；文件保留 396 项状态、计数、终态、凭据匹配和并发区间事实。

当前 head `29d1fd958cf542cabb1d82aec5ace48e6189f2bf` 的两个全量 CI run [38164348518](https://github.com/CoderLambert/news-aggregator/actions/runs/38164348518) 与 [38164352361](https://github.com/CoderLambert/news-aggregator/actions/runs/38164352361) 均通过：frontend types/lint/tests/build 全部成功；backend 与离线部署测试各 `838 passed / 2 warnings`，后续 production settings、release shell、image build 与 G1 local-domain smoke 也通过。早先 head `2ef40cd` 的两次 backend run 曾各失败一个不同的 SQLite busy / `OperationalError` 测试，随后无业务代码改动的后续完整运行通过，按历史瞬时失败保留。T00 分支对照基线 [CI run 38136034042](https://github.com/CoderLambert/news-aggregator/actions/runs/38136034042) 同样为 `838 passed / 2 warnings`。

镜像签名通过 LiteLLM [v1.104.2 release 的 Cosign 指令](https://github.com/BerriAI/litellm/releases/tag/v1.104.2)，使用不可变提交 `0112e53046018d726492c814b3644b7d376029d0` 中的公钥；Cosign 验证 claims、签名和 transparency log inclusion 均成功。签名 payload 中的 manifest digest 与代理实际运行 pin `sha256:3d88bd757134a00e8c00237b85a021ab1f6d54abb9c1df750f411dbe7256a500` 相同。Sigstore 对 [Cosign image claim 验证](https://docs.sigstore.dev/cosign/verifying/verify/)说明其默认会检查签名 payload digest 与目标镜像相符；脱敏验证结果见 [T00-litellm-v1.104.2-cosign.json](../evidence/T00-litellm-v1.104.2-cosign.json)。

## 历史复测 E（2026-10-12）

实现 SHA：`be395ff7c42f5fbe39c74454bebe966eac56ae2a`。运行命令：

    /tmp/byok-t00-smoke-20261012/bin/python tools/byok_t00_probe/probe.py

结果：`395 PASS / 0 FAIL / 395 checks`，退出码 0，CLI 状态 `PARTIAL`。本 CLI 只报告隔离 SDK/Proxy 合成子集，不覆盖旧新闻聊天/研究/翻译回归或真实 provider 兼容。

EOF 负控仍使用无 admission callback 的锁定 v1.104.2 Proxy，原始 upstream 记录 `normal_eof_without_protocol_terminal`，SDK 收到 `finish_reason=stop` 并正常结束。该原始风险没有被弱化或隐藏。新准入条件同时检查受保护 Proxy：同一 Chat streaming 请求返回 HTTP 400、错误码 `T00_STREAMING_DISABLED`，且 upstream 请求数为 0；只有 raw 证据恰好 1 次且受保护路由确实被阻断时，该局部风险才判 PASS。若 streaming 路由开放、错误码不同或请求触达 upstream，门禁仍 FAIL。这个结果证明入口已禁用该具体路径，不声称 LiteLLM 的 EOF 行为已修复，也不支持 Chat streaming。

本次 Compose 清理 `CLEANUP_COMPOSE_DOWN` 与 `CLEANUP_NO_PROJECT_RESOURCES_LEFT` 均 PASS，残留 containers=0、networks=0。provider_real 保持 `NOT_RUN`；未发送外网请求、未读取任何 provider Key。合并自测 `test_probe test_deepseek_smoke` 为 45 tests passed；`py_compile`、Compose 配置校验和 `git diff --check` 通过。

## 历史复测 D（2026-10-11）

实现 SHA：`193d52d0b684c8c47db633a6a93ea96a6690e460`。运行命令：

    /tmp/byok-t00-sdk-venv-20261011/bin/python tools/byok_t00_probe/probe.py

该命令退出码为 1，结果 `394 PASS / 1 FAIL / 395 checks`。唯一失败是 `PROXY_UNGUARDED_CHAT_EOF_NOT_SYNTHESIZED_COMPLETE`：上游有 1 次请求且没有协议终态，Proxy SDK 正常结束并观察到 `finish_reason=stop`。此失败是保留的风险复现。

脱敏 JSON 已提交在 [T00-sdk-protocol-run-d-sanitized.json](../evidence/T00-sdk-protocol-run-d-sanitized.json)；源输出 SHA-256 为 `9d0a034e49a2a7b16746bc41947e9cb02b96f519b55f3807d1d6096961cbb66a`，副本 SHA-256 为 `0dce6b766fd26228f4ade36b92235d8cbcf91bacb132bd2ff79c58c007bda520`。副本的 7 个 SDK/Proxy `public_output.text` 已替换，未包含请求正文、Key、Authorization 值或 Prompt。更早的 A9 原始输出未覆盖（SHA-256 `ef7213c76b62b2ac263d4e934e65d779562f94347d292d0120059edb5c9c093f`）；其脱敏副本 [T00-sdk-protocol-run-a9-sanitized.json](../evidence/T00-sdk-protocol-run-a9-sanitized.json) SHA-256 为 `50326c99d0ece643bb248da2ea729729b496a6b91d786495bf524d70360943cb`，保留原来的 `353 PASS / 4 FAIL / 357 checks`，只作为修正前历史证据。

环境版本：Python 3.14.8、OpenAI SDK 3.28.0、Anthropic SDK 1.13.0、httpx2 2.13.1、LiteLLM Proxy 1.104.2、Docker Compose 5.5.1、Docker Server 29.7.2。用户另行报告 DeepSeek 直连基线 PASS；经 LiteLLM 的 T00-11 与其他 provider 的 PROVIDER_REAL 仍为 `NOT_RUN`。

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

## DeepSeek 直连诊断（用户报告已执行；与 LiteLLM 结果分开）

### 直连诊断时的准入状态与分离记录

用户运行独立 DeepSeek 直连诊断时，T00 尚处于 **BLOCKED**。当时历史运行 D 的实现 SHA 为 `193d52d0b684c8c47db633a6a93ea96a6690e460`，结果为 `394 PASS / 1 FAIL / 395 checks`。失败项 `PROXY_UNGUARDED_CHAT_EOF_NOT_SYNTHESIZED_COMPLETE` 记录了上游正常 EOF、无协议终态，而 LiteLLM v1.104.2 向 SDK 暴露 `finish_reason=stop`。随后运行 E 保留了这项 raw 风险复现，同时证明受保护路径被拒绝。当前状态已在上文更新为 **PASS**；这次直连诊断仍不改变 PROXY_LOCAL、也不代表可选 T00-11 通过。

这次 **直连诊断** 不调用 LiteLLM，也不能代表 T00-11 通过。此后也未执行经 LiteLLM 的真实 provider 请求；直连与网关请求各自独立计数，用户的直连结果单独作为 DeepSeek direct baseline 记录，不改变 T00、PROXY_LOCAL 或 T13 的真实兼容性状态。

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
| 当前真实结果 | **PASS（用户报告，2026-10-12；执行时间未提供）**；1 次请求，`answer_assertion=json_object_fields_match`，`finish_reason=stop`；prompt=57、completion=19，`reasoning_tokens=null`，thinking disabled。用户提供的完整脱敏输出见下方 |

用户提供的脱敏结果：

```json
{"answer_assertion":"json_object_fields_match","completion_tokens":19,"direct_baseline":"PASS","finish_reason":"stop","max_output_tokens":24,"model":"deepseek-flash","prompt_tokens":57,"protocol":"openai_chat_completions_non_streaming","reasoning_tokens":null,"request_count":1,"request_count_semantics":"SDK HTTP request attempts","thinking":"disabled"}
```

按上方官方价格和实际 57 input / 19 output tokens 粗估，若输入 token 全部 cache hit，非高峰约 `$0.000011571`、高峰约 `$0.000023142`；若全部 cache miss，非高峰约 `$0.00001995`、高峰约 `$0.0000399`。响应未提供 cache hit/miss 用量，且未提供执行时间，因此不能确定适用时段或精确费用；这只是估算，不是账单。实际价格、缓存和超时后的上游处理都可能影响费用。

以下命令只运行直连诊断，需由用户在本地交互终端选择执行。默认启动不发请求；脚本不会自动运行收费调用：

```sh
cd /home/lambert/Documents/Codex/2026-10-11/task-2/news-aggregator-t00/tools/byok_t00_probe
/tmp/byok-t00-smoke-20261012/bin/python deepseek_smoke.py --send-one-request
```

用户于 2026-10-12 在本地终端执行了上述命令并提供脱敏结果；执行时间未提供。Key 由用户隐藏输入，助手未读取或接收 Key。隔离合成验证环境使用 `/tmp/byok-t00-smoke-20261012`，Python 3.14.8；下面的命令运行 24 项既有探针 evaluator 自测和 17 项 DeepSeek 诊断测试，不会访问 DeepSeek：

```sh
cd /home/lambert/Documents/Codex/2026-10-11/task-2/news-aggregator-t00/tools/byok_t00_probe
/tmp/byok-t00-smoke-20261012/bin/python -m unittest -v test_probe test_deepseek_smoke
```

结果：`Ran 41 tests ... OK`。测试覆盖固定的 DeepSeek SDK 请求字段、JSON 结果断言、空/非法/错误结构、缺失或不完整终态、零/多次请求、HTTP 错误脱敏、资源关闭、无 TTY/空 Key/取消输入，以及默认不请求路径。实际 OpenAI SDK 使用本地 `httpx2.MockTransport`；没有访问 DeepSeek 或启动 LiteLLM。另有 `py_compile` 与 `git diff --check` 通过；默认 CLI 输出 `{"direct_baseline":"NOT_RUN","request_count":0,"requires":"--send-one-request"}` 并以 0 退出。

用户报告的直连命令对应 1 次 DeepSeek HTTP 请求尝试；经 LiteLLM 的请求数仍为 0。若将来单独执行网关请求，它会是另一条独立请求，不会复用本次调用结果。

本地合成自测命令：

```sh
cd /home/lambert/Documents/Codex/2026-10-11/task-2/news-aggregator-t00/tools/byok_t00_probe
/tmp/byok-t00-smoke-20261012/bin/python -m unittest -v test_probe test_deepseek_smoke
```

本次 DeepSeek 调用由用户本人执行，输出已单独记录；助手没有读取或接收任何 Key。

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

上述历史 A9 运行的 SDK/Proxy 子集使用本任务自己的唯一 Compose 项目且 cleanup PASS。Key 只使用本次合成值。SDK trust_env=false；没有读取 .env、进程环境或旧配置中的 provider Key。该历史运行的 proxy/upstream 容器日志及 CLI JSON synthetic credential scan 均为 false，未打印 Key、Authorization、正文或 continuation；当时的官方 Cosign 签名校验还未执行，当前验签结果见上文复测 F。

## 旧测试对照与未验证项

既有 tests/ 无 diff，未更改任何旧断言。本次没有重跑新闻项目旧聊天/研究/翻译测试，因此不能声称旧回归通过。先前历史记录只留下 219 passed / 3 warnings 摘要；命令、依赖及机器报告未恢复。另一次因隔离环境缺 chromadb 得到 82 passed / 23 failed，也不能替代功能基线；本次不安装旧项目的无关依赖。

历史 A9 的 Responses `resp_item_` 与 Messages cancel 失败已在上方 A9 文件中保留。最新运行 L 中，标准 Responses `fc_`/`call_` 与 foreign-ID 归一化专例均通过，T00-01 至 T00-10 本地验收通过；原始 Chat EOF 缺终态风险继续在 unguarded 负控中复现，准入配置已证明在上游前拒绝该 streaming 路由。完整业务 CI 与镜像签名也已通过。DeepSeek 直连基线为用户报告 PASS；真实的经 LiteLLM T00-11 和其他 provider 测试仍未运行。本地合成结果不表示真实 provider 兼容，也未改生产调用。
