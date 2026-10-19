# DeepSeek 有界真实验收记录

结论：**PARTIAL，不能把 T13-C 或产品整体标为验收通过。** 本轮已实际执行 DeepSeek 短文本、完整流、Token 截断、工具首轮和单轮思考输出。完整工具往返、思考多轮回传、双用户不同厂商 Key 尚未验证。

## 执行范围与身份

- 用户在本会话选择并提供临时 API Key，授权隔离环境、合成提示、最多 6 次请求、每次最多 256 输出 Token；未操作生产。
- 代码树：`origin/main@976fe662c5a952086a04c9edcab0432fa3bd4fcc`；本地 HEAD `e8c34541a6752ed697db9fba3931aa8f2dd7efb6` 的已跟踪代码与该 main 一致，原 `backend/db.sqlite3` 改动例外并保留。
- 日期：2026-10-20，Asia/Shanghai；精确时间和请求计数见 [脱敏机器证据](byok-deepseek-real-2026-10-20.json)。
- 官方端点：`https://api.deepseek.com/chat/completions`；请求及原始响应模型均为 `deepseek-flash`。服务端地域、底层发布版本未在响应中披露，未从别名推断。
- SDK：Python 3.12.14、OpenAI 3.28.0、httpx2 2.13.1；`max_retries=0`、`trust_env=False`、禁止重定向。
- Proxy：LiteLLM 1.105.0，镜像 `ghcr.io/berriai/litellm:v1.105.0@sha256:60947db020b57e204823d3fbc8bb295c85be890d7c9adcc77fb4f5fc2fe410b2`，沿用当前 `provider_key_guard.py`。
- 使用用户提供的临时凭据；未读取 Coding/Token Plan、ChatGPT 订阅或其他厂商凭据。Key 字符格式本身不能证明账户计费类别。未查询账户账单，失败请求费用未知。

## 实际上游请求

| 次序 | 场景 | 上限 | 原始上游结果 | 判定 |
|---|---|---:|---|---|
| 1 | 非思考短文本 | 256 | HTTP 200，`stop`，预期合成文本一致 | PASS |
| 2 | 非思考完整流 | 256 | HTTP 200，原始 `stop` + `[DONE]`，SDK 收到 `stop` 和预期文本 | PASS |
| 3 | 刻意耗尽输出额度 | 1 | HTTP 200，原始 `length` + `[DONE]`；Proxy 记录 `502 T00_STREAM_TERMINAL_UNVERIFIED`，SDK 未收到成功终态 | 截断拒绝证据成立；详见下文 |
| 4 | 思考模式强制指定工具 | 256 | HTTP 400，`Thinking mode does not support this tool_choice` | 参数兼容性 FAIL；未作自动重试或回退 |
| 5 | 思考模式自动选择工具 | 256 | HTTP 200，原生 `tool_calls`，恰好一个白名单工具、合法空对象参数；无 `reasoning_content` | 首轮工具调用成立；完整往返 NOT_RUN |
| 6 | 单轮思考与最终回答 | 256 | HTTP 200，`stop`，非空 `reasoning_content`，结果正确；80 reasoning tokens | 单轮 PASS；多轮回传 NOT_RUN |

出口账本精确闭合为 **6 次派发、6 次响应**。已返回 usage 的 5 次共 394 输入 Token、152 输出 Token，其中包含思考 Token；HTTP 400 的 usage 未提供，不能按 0 补录。每次 `max_tokens` 均不超过 256。

第 4 与第 5 次是参数不同的兼容性用例；没有 SDK/Proxy 自动重试和模型回退。开始前还出现一次观察器本地目录权限错误，修复并核实出口账本为 0 后才发送第 1 次真实请求。该本地失败保留在机器证据中，不计为上游调用或隐藏为 PASS。

## 截断与工具验收限制

SDK 对第 3 次不完整流没有抛出异常，而是输出部分内容后正常结束迭代；因此“SDK 迭代结束”仍然不能代表成功。原始探针最初因要求 SDK 抛异常而将这一项记为 FAIL，该原始结果保留。随后核实 Proxy 明确记录终态拒绝且 SDK 没有收到 `stop`。

另独立执行当前实际业务函数 `ai_verified_stream.verified_text_deltas` 的四个合成检查：无 `stop` 的 EOF、`length` 终态、空结果均抛 `IncompleteStream`，正常文字加 `stop` 通过。**这些是合成函数检查，不是本次真实 SSE 帧重放，也不是 Django/数据库端到端验收。** 真实网络断流场景本轮未运行。

第 5 次工具响应是有效首轮，但验收脚本额外要求非空思考内容并提前返回，没有发送工具结果。本轮未完成 `tool_call → result → final`，也未完成带原生思考字段的多轮续接。第 6 次只补充单轮思考内容的真实证据，未以第 7 次调用突破授权上限。不能因此宣称研究功能已经真实验收通过。

## 隔离与清理

本次创建独立 Compose 项目、临时 PostgreSQL 卷、随机项目 Key 和数据库/Proxy 凭据。项目 Key 只允许 Flash 路由。未复制真实 `.env` 或业务数据库。

Proxy 仅连接内部网络；单独的出口观察器只转发到 DeepSeek 官方 HTTPS 端点，验证 TLS，不跟随重定向、不重试。观察器在发送前将计数落盘，强制总数不超过 6、模型固定、输出上限 1–256。SDK 入口也通过该临时观察器转发。这些隔离覆盖与 `api_base` 改写均在临时配置中，未修改仓库运行时代码；故不等同未经改写的生产拓扑验收。

缺少 provider Key 的请求返回 400，项目无权访问模型返回 403；两者均在真实上游前拒绝，发送计数为 0。

Key 仅暂存在权限受限的内存文件系统，未写入仓库或本报告。报告生成前扫描临时 JSON/JSONL/Python/YAML 未发现本次凭据。完成后删除 provider Key 文件及其余临时凭据，移除本次容器、网络和数据库卷；按项目标签复查均为 0。临时脚本和脱敏账本位于 `/tmp/newshub-deepseek-20261020/`，哈希见机器证据。**本地清理不代表厂商端撤销，用户仍需撤销已提供的临时 Key。**

## 剩余门禁

- T13-C-01：本次 Flash 文本通过。
- T13-C-02：正常流和 `length` 拒绝有真实证据；真实网络 EOF、完整应用持久化链未运行。
- T13-C-03：只有工具首轮；工具结果及最终回答 NOT_RUN。
- T13-C-04：单轮思考通过；`reasoning_content` 多轮回传 NOT_RUN。
- T13-C-05：只有一个厂商 Key，双用户不同 Key 并发隔离 NOT_RUN。
- 原 T00 历史镜像验签、完整 T00-G 运维门禁、其他厂商、全量 CI、浏览器产品验收和生产发布均不由本次证据覆盖。

官网核对：[模型与端点](https://api-docs.deepseek.com/quick_start/pricing/)、[工具调用](https://api-docs.deepseek.com/guides/tool_calls/)、[思考模式及回传约束](https://api-docs.deepseek.com/guides/thinking_mode/)。官网说明用于确定参数与预期，不能替代实际运行结果。
