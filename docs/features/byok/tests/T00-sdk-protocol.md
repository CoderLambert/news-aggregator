# Test T00 · 共享网关端到端技术验真

> **PLANNED / NOT_RUN**：本 Test 是验收契约，尚无 SDK_LOCAL、PROXY_LOCAL 或 PROVIDER_REAL 结果。任务仅使用合成假 Key 与本地受控 HTTP upstream。

对应：[T00 Task](../tasks/T00-sdk-protocol.md)。

| 用例 | 场景 / 故障注入 | 正确性约束 | 状态 |
| --- | --- | --- | --- |
| T00-01 | 三协议完整文字和工具终态 | 原始上游、Proxy、SDK 终态相符；满足协议各自完整条件后才成功 | NOT_RUN |
| T00-02 | partial 事件后正常 EOF、length/incomplete | 不能合成完整终态；保留原始 incomplete 原因 | NOT_RUN |
| T00-03 | 截断 body、超时、SSE error、HTTP error | 安全错误可分类，Key/正文不泄露 | NOT_RUN |
| T00-04 | 半截工具参数、非法 JSON、非白名单工具 | 不派发工具、不成功 | NOT_RUN |
| T00-05 | 两轮工具续接 | 保留 Responses output items、Anthropic thinking/signature、Chat reasoning_content；公开消息不含 continuation | NOT_RUN |
| T00-06 | 不同 Key/model 并发隔离 | 不混用用户凭据、模型、Proxy 项目虚拟 Key 或部署 provider Key | NOT_RUN |
| T00-07 | 成功、异常、取消时关闭 stream/response/HTTP 资源 | 所有已打开资源均关闭 | NOT_RUN |
| T00-08 | 缺 provider Key、错误项目虚拟 Key | 缺 Key fail closed；错误项目凭据在到达 upstream 前被拒绝 | NOT_RUN |
| T00-09 | SDK/Proxy 重试与 fallback 计数 | max_retries=0、num_retries=0、无跨模型 fallback，实际请求数与断言一致 | NOT_RUN |
| T00-10 | v1.104.2 原始上游 EOF 与 Proxy 暴露终态对照 | 仅下游 stop/[DONE] 不足以证明原始上游完整；失败按局部风险记录 | NOT_RUN |

## 如何证明

- **SDK_LOCAL**：使用真实安装的官方客户端 SDK 直连受控合成上游，证明 SDK 请求序列化、响应解析和关闭行为；不证明 Proxy 整合或厂商兼容。
- **PROXY_LOCAL**：锁定真实 LiteLLM Proxy 镜像、真实 SDK、受控 HTTP upstream，记录上游原始请求/终态、Proxy 返回、SDK 输出和请求计数。本卡主要技术门槛。
- **PROVIDER_REAL**：本卡不调用真实厂商，状态保持 NOT_RUN。PROXY_LOCAL 不能推出任何厂商兼容性。
- **日志**：只保留合成凭据标识、事件名、模型别名、耗时、错误类别和请求计数；禁止打印 Key、完整 Authorization、新闻正文或私有 continuation。
- **基线与断言**：同环境记录任务前相关旧聊天/研究/翻译测试基线。若本卡只改探针/协议契约而没改旧测试，明确写“旧测试断言无 diff”；不得放宽旧断言。

## 执行证据（后续实际执行时填写）

| 项目 | 结果 |
| --- | --- |
| 本卡状态 | **NOT_RUN** |
| 精确基线 HEAD | `ea2ce55ae22e19e1604e88031b824b68f2666cec`（此前确认的功能分支基线；执行当天需重新核对） |
| 实现 SHA | 本次架构文档 commit 6440a07197dae4b43b032c782638ad97e9defb59；SDK/Proxy 实施 SHA 未执行 |
| Python / OpenAI SDK / Anthropic SDK / LiteLLM / Docker 版本 | NOT_RUN |
| SDK_LOCAL 执行命令及脱敏输出 | NOT_RUN |
| PROXY_LOCAL 执行命令及脱敏输出 | NOT_RUN |
| PROVIDER_REAL | **NOT_RUN；本卡不授权真实厂商请求** |
| 旧聊天/研究/翻译基线与变更后对照 | 历史准备记录：219 passed, 3 warnings；精确运行命令、依赖版本、功能基线 SHA 与报告文件未在本卡重新执行，不能视为本卡证据 |
| 旧测试断言 diff | 本次 PR 只改文档，不改代码测试或旧断言；T00 的实现前/后回归仍 NOT_RUN |
| 原始终态 / continuation / 请求计数 / 资源关闭 | NOT_RUN |
| 未验证或阻塞原因 | 尚未实现或运行；所有场景按 NOT_RUN 处理 |

没有保留原始事件和脱敏计数证据时，不得改为 PASS。

