# DeepSeek 第二窗口真实验收

运行时代码：`main@6a2cc025c338ef0308024151be4fbd796f7f3a39`（PR #153）。本窗口由用户新目标授权复用此前提供的 DeepSeek Key；它与[第一窗口](byok-deepseek-real-2026-10-20.md)的 6 次请求分开记账，不覆盖旧结果。以下为**官方 SDK→固定 Proxy 镜像→DeepSeek 官方 API 的 PROVIDER_REAL**，不是完整产品/生产验收。

## 环境与边界

- 日期 2026-10-20（Asia/Shanghai）；OpenAI SDK 3.28.0、httpx2 2.13.1；官方默认端点 `https://api.deepseek.com/chat/completions`，不覆盖地域/URL；请求和原始响应模型均为 `deepseek-flash`。API 未声明物理服务地域，不推断地理位置。
- LiteLLM 镜像 digest `60947db020b57e204823d3fbc8bb295c85be890d7c9adcc77fb4f5fc2fe410b2`，当前 guard SHA-256 `e62ecde33852732c1e98ab7fb5080c3b0e069fc56a631b1771c2a726068037f7`。本地项目 Key 仅准入该 alias，独立临时 Postgres/网络/记录器，无生产服务和数据。
- SDK、Proxy 与记录器均不重试。记录器固定官方 TLS 主机、校验实际 provider Key 身份，拒绝正文携带 api_key、未知模型、超 256 输出 Token 请求与第 7 次出站。全部提示和工具结果是合成内容。
- 实际 **6 次出站 / 6 次 HTTP 200 / 零重试**，每次请求上限 256 输出 Token；上游报告总输入 1152、总输出 212 Token。没有据此估算账单金额。

## 逐项结果

| 请求 | 实测 | 结果 |
|---|---|---|
| 1–2 | 关闭思考，合法空参数工具调用→匹配工具 ID 的合成结果→正确最终文本，原始终态 tool_calls→stop | PASS |
| 3 | 开启思考且允许工具，返回合法 tool_calls，但上游 reasoning_tokens=0、无 reasoning_content | 工具请求有效；非空工具思考回传未观察到，完整思考工具往返 NOT_RUN。保留原 harness 的 FAIL，不推断模型不支持 |
| 4 | 正常真实流式输出，经当前业务 `verified_text_deltas`，原始 stop / DONE、文本与干净结束均核对 | PASS |
| 5–6 | 思考文本与同模型续问，答案正确，均原始 stop；第 5 次原始非空思考内容与第 6 次实际出站 assistant 字段哈希完全一致 | 文本续问与原样传输 PASS；不是工具思考上下文验收 |

后两次是独立的文本思考/续问用例，没有重发第 3 次工具请求或扩大 6 次限额。[官方思考模式文档](https://api-docs.deepseek.com/guides/thinking_mode/)区分带 tools 的思考上下文回传和不带 tools 的普通多轮；本次第 5–6 次没有 tools，传回的旧思考内容会被供应商忽略。因此哈希一致只证明传输保真，不能证明供应商使用了该思考上下文。工具调用仍须另外验证非空思考的完整往返，不能用此结果替代。

SDK 传入过 low，但实际出站账本未含 reasoning_effort；本次只证明 thinking 开关，不声明 low 强度透传。未为此新增厂商旁路或适配器。[API 参数定义](https://api-docs.deepseek.com/api/create-chat-completion/)与上述思考合同按本次日期核对；实际出站事实以[脱敏账本](byok-deepseek-followup-2026-10-20.json)为准。

## 隔离与清理

Proxy 日志未检出真实 provider Key、项目/master Key 或合成提示；公开记录不含 Key、原始思考、工具参数正文或私有历史。完整原始脱敏计数留在 `/tmp/newshub-deepseek-final-20261020/`，不复制真实数据库。

已移除临时 provider Key 和身份哈希文件；本次 Compose 容器、卷、网络全部清理，临时项目/master/Postgres secret 文件删除。**仅表示本次本地副本清理，不表示供应商账户 Key 已撤销。** 没有生产迁移、发布、切源或停止原有服务。

## 保留的未验证项

T13-C 仍为 PARTIAL：非空思考工具完整往返、两个不同真实用户 Key 的并发隔离、真实长文/收费 UI 全链与人工 UAT 未完成。其它厂商和地域没有提供 Key/授权，保持 NOT_RUN。固定镜像的双项目/不同合成 Key 隔离通过不替代真实双 Key。后续若继续这些可自动化用例，须准备受保护凭据引用和新的有界额度；本窗口不会再发请求。
