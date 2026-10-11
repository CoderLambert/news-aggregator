# T13-E · Qwen / 百炼 官方模型联调

> **PLANNED**：本文件为未执行的实施/测试契约，所有测试当前 NOT_RUN。实施时以 `origin/feat/byok-user-api-keys` 最新 HEAD 为准，勿把设计 SHA 当作当前代码。

这是 [T13 真实厂商验收](T13-providers.md) 的**一张独立子任务卡**，只能完成一个厂商。依赖 T00/T02/T04/T09，按本卡实际 Key/模型独立提交。

本次只用 **Qwen / 百炼** 的合法通用计费 API Key、后端可信地域端点、一个明确模型 ID。协议：**Chat Completions**。关键验证：通用按量 API Key、北京/新加坡及受限 workspace 模板，不接 Coding/Token Plan。

## 只完成一个厂商的完整验收

- 明确具体模型/地域/日期/SDK 版本，读取该厂商官网关于模型/套餐的限制；不能用 Coding/Token Plan 或 ChatGPT 订阅代替。
- 实际 SDK 发起短文本和流式输出；确定原始成功/失败终态，记录费用可能性但绝不泄漏密钥。
- 在工具支持的模型上完成 tool_call→工具结果→最终回答；模型不支持则注明原因，不能标“研究能力已验证”。
- 双用户不同 Key 同时调用不串凭据；不要顺手调整其他厂商适配器。
- 缺合法真实 Key：只准备 SDK_LOCAL，**PROVIDER_REAL=NOT_RUN，子卡 BLOCKED**；不能补录假的 PASS。

测试用例：[Test T13-E](../tests/T13-e-provider.md)。必要的最小修复可提交单厂商 PR，base 指向功能分支。不要同时执行其它 T13 子卡。

