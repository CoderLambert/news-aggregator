# T02 · 录入模型并显式验证

> **PLANNED**：本文件为未执行的实施/测试契约，所有测试当前 NOT_RUN。实施时以 `origin/feat/byok-user-api-keys` 最新 HEAD 为准，勿把设计 SHA 当作当前代码。

| 属性 | 内容 |
| --- | --- |
| 前置任务 | [T01](T01-credentials.md)、[T00 本地技术门槛](T00-sdk-protocol.md) |
| 推荐规模 | M |
| 对应测试 | [Test T02](../tests/T02-models-and-tests.md) |

## 本次交付的完整功能

用户对自己的连接添加多个模型，手工输入 ID 或选官方预置，主动点击测试文本/工具能力，得到可信的能力标记。

**允许修改范围**：UserAIModelConfig、版本化目录/可信端点、手动模型 ID、可选发现、模型 CRUD/测试接口、费用提示、model revision+epoch 对测试结果做版本拦截。本地测试通过临时 LiteLLM Proxy 和受控 HTTP upstream；这里建立业务 AICallAttempt 记录，供后续业务调用复用。无可用网关时失败关闭。

**本次明确不做**：保存配置不会自动计费；测试文本成功不代表工具调用通过；不做全套使用分析页面或支持任意额外参数。

### 可直接复现的验收路径

保存两模型→测试其中文字成功而工具未知→换 Key 后旧测试状态过期→再次测试明确成功或失败。

### 对应 Test 用例

| Test ID | 可操作情境 | 必须观察到 | Test 文件 |
| --- | --- | --- | --- |
| T02-01 | 新增两模型并重新进入列表 | 按连接/用户隔离，目录失败仍允许输入模型ID | [Test 契约](../tests/T02-models-and-tests.md) |
| T02-02 | 手动触发测试，不触发保存即测试 | 每个真实上游尝试单独记账，提示可能收费 | [Test 契约](../tests/T02-models-and-tests.md) |
| T02-03 | 工具能力与文本能力分开显示 | 未验证/失败工具的模型不可标记研究可用 | [Test 契约](../tests/T02-models-and-tests.md) |
| T02-04 | 换 Key/模型参数后旧成功回执迟到 | 不能改变当前状态，未知模型保持未验证 | [Test 契约](../tests/T02-models-and-tests.md) |
| T02-05 | 任意 URL/extra_body/unsupported model 参数 | 不能进入 SDK 权限面，不自动落到管理员 Key | [Test 契约](../tests/T02-models-and-tests.md) |

### 立即停止并纠偏

旧测试回执覆盖新 credential_epoch/revision 或 API 泄漏原始错误、Key 时停止。

### Codex 一次任务交付要求

1. 查看当前工作目录 AGENTS、分支和未提交改动；读取本卡和同编号 Test、技术方案/最新相关代码。
2. 同环境记录受影响旧测试的基线；用既有 Django/React/SSE/SDK/持久任务，先验证关键假设再编码。
3. 本次只交付这一项**可以运行的完整功能**，包括权限、正常操作与最主要的失败路径；不跨到其它 Txx。
4. 跑最小定向单元/契约测试以及受影响旧功能回归，列出修改过的测试断言 diff；需求未变时禁止改断言迁就代码。
5. 更新对应 Test 文档中的真实日志、环境、SHA 和 NOT_RUN 项；单张任务 PR base 指向 `feat/byok-user-api-keys`。未授权时不合并 main、不开始下一张卡。

**任务结束**：这条用户流程能运行、失败能清楚识别，主要不变量有自动化验证；更新同名 Test 实际证据并留下单张可审核 PR。当前任何未验证的地方明确写 NOT_RUN。

