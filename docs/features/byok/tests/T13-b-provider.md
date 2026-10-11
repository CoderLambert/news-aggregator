# Test T13-B · Claude / Anthropic 官方真实兼容性

> **PLANNED**：本文件为未执行的实施/测试契约，所有测试当前 NOT_RUN。实施时以 `origin/feat/byok-user-api-keys` 最新 HEAD 为准，勿把设计 SHA 当作当前代码。

| Test ID | 真实行为 | 验收约束 | 当前 |
| --- | --- | --- | --- |
| T13-B-01 | 厂商特定通用 Key 真实生成短文本 | 文本、实际 model/region/日期可记录，密钥不能泄露 | NOT_RUN |
| T13-B-02 | 上游流式完整输出和刻意失败 | 原始终态可信，EOF/length 不当完成 | NOT_RUN |
| T13-B-03 | tool_call→result→final | 工具能力确实支持，完整续接 | NOT_RUN |
| T13-B-04 | 厂商特别行为 | message_stop、end_turn/tool_use、thinking block 与签名 | NOT_RUN |
| T13-B-05 | 并发双用户/多 Key | 不串凭据且无隐式重试/回退 | NOT_RUN |

## 证据区（待执行）

- 模型 ID、地域、SDK 版本、时间：NOT_RUN
- SDK_LOCAL 请求/响应日志：NOT_RUN
- PROXY_LOCAL 请求/响应与请求计数：NOT_RUN
- PROVIDER_REAL 正常文本/流式/工具：NOT_RUN（首轮仅 DeepSeek 获准）
- 真实凭据类别（不包含 Key 字符）：NOT_RUN
- 脱敏失败记录/参数兼容性：NOT_RUN
- 精确任务 SHA、变更/测试 diff、PR：NOT_RUN

缺合法通用 Key 只能标 BLOCKED/NOT_RUN；实际调用可能计费。

