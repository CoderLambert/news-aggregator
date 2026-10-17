# BYOK 终态校验修复（2026-10-17）

## 所属批次

基线 `main@66a09aef0b6291c0beddd559ffd9e2874e0643b1`。本任务只修当前个人 API Key 接入 LiteLLM Proxy 的 Chat Completions 文本流兼容边界。生产部署、真实模型调用、用户手工产品验收均延后至统一验收。

## 已确认问题与处理

`backend/api/services/provider_credentials.py` 将 `stream=True` 请求降级成 LiteLLM 非流式请求，再包装为一个 SSE-compatible chunk。此前即使供应商返回 `finish_reason=length`、`content_filter`、`tool_calls`、缺失 terminal、多个候选或非文本内容，兼容层仍可能向消费者暴露部分正文。某些消费者不强制终态；这可能导致不完整的聊天回答被误用。

本变更在任何文字进入消费者**之前**检查：必须恰好 1 个 choice、`finish_reason=stop`、且 `message.content` 为非空字符串。其他所有情况抛出不含模型正文/密钥的明确异常，原模型请求仍保持 `max_retries=0`、请求级 API Key、loopback gateway、无外部回退。**非流式调用**（包括真实研究用的 `tool_calls`）维持旧语义，不在此任务改写研究工具编排。

## 测试与边界

- 新增 **12 项**纯本地测试：9 种不完整/恶意/歧义响应、1 种合法完成、1 种非流式工具响应、1 种阻断部分文本泄露的下游对接。
- 合并后完整后端预期为 `2429 passed / 16 skipped`。这是合成、契约测试，不是实时 DeepSeek/其他供应商验证。
- 此任务**不等于完成**旧 BYOK T00–T09：SDK/网关真实协议、用户多连接、模型能力/偏好、研究、翻译完整生命周期仍按 `docs/plans/FEATURE-DEVELOPMENT-2026-10-17.md` 的顺序逐项移植及开发。
- CI 只执行现有前后端、静态、安全回归、生产镜像构建和隔离 G1；不操作线上密钥、服务、数据库。
