# Codex 执行交接：BYOK 与共享 AI 网关

先读同目录 BYOK_IMPLEMENTATION_PLAN.md、tasks/EXECUTION_RULES.md 和当前任务对应的 Task/Test。此文件是方案边界，不代表网关、BYOK 业务或真实厂商调用已验收。

## 固定架构

- LiteLLM Proxy 是新闻、知序、TranslateFlow 等项目可复用的独立服务。用官方容器镜像固定版本与 OCI digest；独立部署、配置和数据库生命周期，不由 NewsHub 启动。本轮仅定义文档，不建仓库、不部署服务、不操作线上环境，也不 fork 或重写 provider 适配。
- 当前记录的镜像候选为 ghcr.io/berriai/litellm:v1.104.2@sha256:3d88bd757134a00e8c00237b85a021ab1f6d54abb9c1df750f411dbe7256a500。T00/T00-G 仍须执行镜像来源/签名与功能验真；在验收前不能称为生产通过。
- 网关负责 provider 协议、受控模型路由、项目级受限虚拟 Key、限流、脱敏用量。业务项目负责网站用户身份、个人 BYOK Key 的安全托管、功能选模、任务幂等/恢复/取消、数据库事务和结果权限。
- Proxy 的 master key 只用于运维和管理 API，绝不进业务运行容器。每个项目拥有独立、受限的虚拟 Key；虚拟 Key 与个人 provider Key 是两种不同凭据。NewsHub、知序、TranslateFlow 彼此不共享虚拟 Key、个人历史或网站用户身份。
- 用户个人 provider Key 只能由所属业务后端在已认证的用户操作中，从加密托管记录按请求显式提供给受信网关。缺 Key 即失败；禁止使用 Proxy 部署/环境 Key、平台服务 Key 或其它用户 Key 兜底。
- 用户请求不能控制 user_config、api_base、任意 headers、网关 model alias、provider profile、fallback 或其它额外参数。业务后端根据受信连接/模型配置构造白名单请求；网关只开放明确配置和验证过的 credential 字段。
- 新闻正文/问题的接收方为业务服务器、共享网关、用户所选厂商。Proxy 与业务日志、回调和分析字段不得记录 Key 或正文；首版关闭共享内容缓存，跨租户缓存须另行审核设计。
- OpenAI/Anthropic 等官方 SDK 可以作为业务后端访问 Proxy 的客户端；业务代码不得实现三套 provider 适配器。初始产品预设为 OpenAI、Claude、DeepSeek、GLM、Qwen、Kimi，不构成 LiteLLM provider 架构上限。首轮 PROVIDER_REAL 只允许 DeepSeek；其他厂商保持 NOT_RUN。

## 分层验证状态

- SDK_LOCAL：真实官方客户端 SDK 直接连接受控合成上游；只证明客户端序列化/解析。
- PROXY_LOCAL：固定 LiteLLM Proxy + 实际客户端 + 受控合成上游；证明集成链路，不代表任何真实厂商可用。
- PROVIDER_REAL：经共享 Proxy 对指定真实厂商、模型、地域执行有界真实调用。首轮仅 DeepSeek，其他厂商不可从 PROXY_LOCAL 推导兼容。
- 当前所有新 SDK_LOCAL、PROXY_LOCAL、PROVIDER_REAL、独立网关运维和用户 UAT 状态均为 NOT_RUN。此前 T00 SDK 任务准备记录的旧业务回归为 219 passed / 3 warnings，只作旧测试基线，不能记作 Proxy 或 provider 验收。

## 任务顺序与独立性

1. T00：用本地实际 LiteLLM Proxy、受控上游和实际 SDK 客户端完成端到端技术门槛，不做新闻业务表、设置页或部署服务。
2. T00-G：单独交付共享 Proxy 运维契约，含固定镜像/digest、Postgres、配置校验、密钥隔离、健康检查、脱敏日志、备份恢复与升级回退。它是 T00 后置子卡，也是 T13 真实厂商验收及 T14 发布门禁的前置条件。
3. T01 只保存/管理网站用户 Key，可先完成，不调用 Proxy。T04 开发和验证可启动临时本地 Proxy 与受控上游，不要求共享生产服务已部署。生产调用遇网关缺失必须清楚失败、不得直连 provider 或回退平台 Key。
4. 按 tasks/README.md 保留 T01–T14 原业务拆分。模型测试、聊天、翻译、研究和问题推荐都由业务后端调用共享网关；持久任务、幂等、取消、事务与用户私有结果仍由原新闻业务系统负责。
5. T13 逐模型记录 PROVIDER_REAL；先只执行 DeepSeek 子卡，其他厂商按 NOT_RUN 记录。T14 同时要求业务功能回归、T00-G 独立网关验收和获授权的 provider/UAT 结果。

独立网关发生故障时，NewsHub 的新闻阅读与已保存历史仍可用；新 BYOK 调用失败关闭。不要引入 Kubernetes、多副本或第二套业务任务框架。

## T00 必验风险

- 使用官方 LiteLLM Proxy 固定版本、两种 SDK 客户端及本地受控上游。覆盖成功、上游语义不完整但正常 EOF、截断 body、超时、SSE error、半截工具参数、两轮工具续接、并发不同用户 Key 隔离、请求计数及资源关闭。
- SDK max_retries=0、Proxy num_retries=0、无 cross-model fallback。验证缺 provider Key 时不会借部署 Key，错误项目虚拟 Key 在到达上游前被拒绝。
- 针对 v1.104.2 streaming_handler 的 EOF 终止行为检查真实原始事件与 Proxy 输出。仅有下游 finish_reason=stop 或 [DONE] 时可能无法区分 Proxy 合成完成与上游真实完成；这是特定原始终态路径风险，不能扩写成“所有网络错误都会假成功”。若失败，只能在锁定版本路径局部修复、使用上游修复，或禁用该具体路由的 streaming；不得全面更换 SDK、写第二套 provider 适配器或降低完整性门槛。
- 业务任务只有在满足终态契约且数据库事务提交成功后才能完成；Proxy 的 HTTP/SSE 结束本身不是业务 complete。

## 不可破坏的不变量

1. GET 恢复只读，不创建任务、不派发工作、不调用 Proxy。
2. request_hash 与 execution_digest 分离；已有幂等请求恢复固定快照，不重新选模型。
3. 保存/轮换/撤销 Key 不会让 Key 进入浏览器持久层、日志、URL、Proxy 回调或 PR。
4. Proxy 项目虚拟 Key 不等于网站账号；用户凭据与项目服务凭据分离，所有权和任务提交权留在业务后端。
5. 只在服务端解析可信端点、模型别名和白名单参数；不把任意 user_config、api_base、headers 交给 Proxy。
6. selection revision、credential_epoch、task generation/run_token 分开；未知请求结果不自动重试。
7. 用户取消由业务后端确认；关闭 SSE 只断开观看。已发送的请求可能仍由厂商计费。
8. Proxy 禁止隐式共享 provider Key、跨模型 fallback 与首版共享内容缓存。
9. usage 中未知 token/cost 用 null；用 Proxy request id 与业务 AICallAttempt 关联。预算是可执行限制，不承诺厂商账单绝对硬上限。
10. 历史结果和新闻阅读在网关故障时仍按原用户权限可读；任务/结果/complete 事件须由业务事务提交确认。

## 执行与交付

实施前核对最新 origin/feat/byok-user-api-keys HEAD、独立工作树、实际 AGENTS、SDK/Proxy/Docker 版本与适用测试。先记录未修改旧回归基线，按单张 Task 工作；需求未改变时禁止通过弱化旧断言制造绿灯。

只允许合成凭据进行 SDK_LOCAL/PROXY_LOCAL。真实厂商调用仅在明确任务获准时使用，首轮只 DeepSeek，由用户本人在终端隐藏输入；不把 Key 发到聊天、日志、GitHub 或提交。

本轮仅更新文档，不创建服务仓库/配置、不部署或操作线上服务。后续 T00 只做本地 Proxy+SDK 技术验真；T00-G 可在隔离测试环境交付共享 Proxy 配置与运维验收，但不做生产 go-live，生产发布归 T14。T00/G、每张 Task 和 Test 分别记录精确 SHA、固定镜像/digest、SDK/Python 版本、脱敏执行日志、测试 diff、PROXY_LOCAL / PROVIDER_REAL / UAT 状态及未验证项。文档审核 PR 以 feat/byok-user-api-keys 为 base，不合并。
