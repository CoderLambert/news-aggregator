# T13 · 六家厂商真实兼容性关卡

> **PLANNED**：本文件为未执行的实施/测试契约，所有测试当前 NOT_RUN。实施时以 `origin/feat/byok-user-api-keys` 最新 HEAD 为准，勿把设计 SHA 当作当前代码。

| 属性 | 内容 |
| --- | --- |
| 前置任务 | [T00](T00-sdk-protocol.md)、[T02](T02-models-and-tests.md)、[T04](T04-article-chat.md)、[T09](T09-research-first-run.md) |
| 推荐规模 | 六个独立小验证 |
| 对应测试 | [Test T13](../tests/T13-providers.md) |

## 本次交付的完整功能

按 OpenAI、Claude、DeepSeek、GLM、Qwen、Kimi 六个官方通用 API Key，逐厂商证明一个指定模型的真实文本/流/工具功能。

**允许修改范围**：本卡只作组合门槛，实际 Codex 一次只能执行 T13-A 至 T13-F 其中一张厂商子卡。每次记录真实模型 ID、region、协议、Date、SDK 和测试证据；模拟测试不算厂商通过。

**本次明确不做**：无 Key 不绕过，禁止把 Coding Plan/订阅 Token 当作后端通用 Key；不以“兼容 OpenAI SDK”推导所有厂商能力。

### 可直接复现的验收路径

六份独立的提供商验证记录；没有合法凭据的厂家逐项 BLOCKED/NOT_RUN。

### 对应 Test 用例

| Test ID | 可操作情境 | 必须观察到 | Test 文件 |
| --- | --- | --- | --- |
| T13-01 | 六张子卡分别有真实通用 Key +指定模型的文本结果 | 只有实测成功标文本已验证 | [Test 契约](../tests/T13-providers.md) |
| T13-02 | 原生真实终态与断流/输出限制 | SDK 会识别失败与不完整 | [Test 契约](../tests/T13-providers.md) |
| T13-03 | 工具能力/特殊 reasoning 续接 | 仅对实际通过的模型启用研究工具 | [Test 契约](../tests/T13-providers.md) |
| T13-04 | 同一环境双用户/不同 Key | 不串路由或 Key，也不 fallback | [Test 契约](../tests/T13-providers.md) |
| T13-05 | 某厂商无 Key 或额度不足 | 独立 BLOCKED/NOT_RUN，不伪造成功 | [Test 契约](../tests/T13-providers.md) |

### 立即停止并纠偏

缺任一厂商真实验收，T13 合计不能写全部 PASS；可以先完成其他不依赖的工作。

### Codex 一次任务交付要求

1. 查看当前工作目录 AGENTS、分支和未提交改动；读取本卡和同编号 Test、技术方案/最新相关代码。
2. 同环境记录受影响旧测试的基线；用既有 Django/React/SSE/SDK/持久任务，先验证关键假设再编码。
3. 本次只交付这一项**可以运行的完整功能**，包括权限、正常操作与最主要的失败路径；不跨到其它 Txx。
4. 跑最小定向单元/契约测试以及受影响旧功能回归，列出修改过的测试断言 diff；需求未变时禁止改断言迁就代码。
5. 更新对应 Test 文档中的真实日志、环境、SHA 和 NOT_RUN 项；单张任务 PR base 指向 `feat/byok-user-api-keys`。未授权时不合并 main、不开始下一张卡。

**任务结束**：这条用户流程能运行、失败能清楚识别，主要不变量有自动化验证；更新同名 Test 实际证据并留下单张可审核 PR。当前任何未验证的地方明确写 NOT_RUN。

