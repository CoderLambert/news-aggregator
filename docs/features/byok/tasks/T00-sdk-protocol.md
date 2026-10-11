# T00 · 共享网关端到端技术验真

> **PLANNED**：本卡尚未执行，SDK_LOCAL、PROXY_LOCAL 和 PROVIDER_REAL 都是 NOT_RUN。实现时先核对最新 `origin/feat/byok-user-api-keys`、独立工作树与实际 Python、Docker、Proxy 版本；本文件不代表通过验收。

| 属性 | 内容 |
| --- | --- |
| 前置任务 | 无 |
| 推荐规模 | S·技术门槛 |
| 对应测试 | [Test T00](../tests/T00-sdk-protocol.md) |
| 后续运维子卡 | [T00-G 共享网关运维契约](T00-gateway-service.md) |

## 目标

以锁定的官方 LiteLLM Proxy 镜像、官方客户端 SDK、受控本地 HTTP 上游，证明真实 SDK→Proxy→上游及返回链路的协议、完整性和凭据隔离。不能只 mock gateway、只调用 Proxy 的函数，或仅用 SDK 直连上游。

候选镜像为 `ghcr.io/berriai/litellm:v1.104.2@sha256:3d88bd757134a00e8c00237b85a021ab1f6d54abb9c1df750f411dbe7256a500`。T00 必须先核对官方发布/签名和 digest；若验证不通过，记录阻塞并停下，不自行换版本。实际 Python、客户端 SDK 与锁文件版本由本卡实测后写入 Test 文档。

官方 SDK 只作为业务后端访问 Proxy 的客户端；LiteLLM Proxy 负责向 OpenAI Responses、OpenAI Chat Completions、Anthropic Messages 上游路由和转换。不得新增三套 provider HTTP/SSE 适配器。项目虚拟 Key 用于业务后端认证 Proxy；用户 provider Key 是另一凭据，由业务后端按请求显式提交到 Proxy 支持且已验证的受限凭据字段。不得把 Proxy master key 放入业务请求。

## 允许修改范围

- 固定本探针所需的最小客户端 SDK 与运行依赖版本，不升级全项目或系统软件。
- 定义最小 ModelTurn、ModelEvent、安全错误和仅服务端可见 continuation 契约；对外可见消息必须排除 continuation。
- 提供独立可运行 CLI 探针：启动或连接锁定的 LiteLLM Proxy，连接受控本地 HTTP 上游，并由真实安装的 SDK 发请求。
- 验证 OpenAI Responses、OpenAI Chat Completions、Anthropic Messages 的原始终态、原生不完整状态、工具续接与资源关闭。保留 Responses 原始 output items、Anthropic thinking/signature、Chat reasoning_content。
- Proxy 和 SDK 重试均设为 0；禁用模型 fallback。记录代理上游请求计数，证明失败时没有隐式重发。

## 明确不做

不创建业务数据库模型/迁移、设置页、新闻业务调用、用户任务系统、共享生产网关部署或真实厂商调用；不操作 ssh tencent 或线上环境，不读取环境/文件/旧配置中的 provider Key。所有测试凭据必须是本次探针生成的合成假 Key。不得把本地 Proxy 集成证据记为真实 provider 兼容。

## 必验场景

| ID | 受控场景 | 验收要求 |
| --- | --- | --- |
| T00-01 | 三协议正常完整终态 | 保存原始上游事件与 Proxy/SDK 结果；只有各协议终态均完整且语义正确才可返回成功 |
| T00-02 | 语义不完整但正常 EOF、显式 length/incomplete | 均不得合成 complete；保留原始原因 |
| T00-03 | 上游截断 body、超时、SSE 流内错误、HTTP 错误 | 返回安全且可分类错误，不暴露 Key/正文；请求次数符合一次，无自动重试 |
| T00-04 | 部分工具参数、非法 JSON、非白名单工具 | 不执行工具、不生成成功最终答案 |
| T00-05 | 两轮工具往返 | Responses 原始 items、Anthropic thinking/signature、Chat reasoning_content 在服务端 continuation 中完整回送；公开消息不可见私密状态 |
| T00-06 | 两组显式不同 provider Key/model 并发请求 | 请求在对应账户和模型间隔离；不读取全局或 Proxy 部署 provider Key |
| T00-07 | 正常完成、异常、取消后的资源关闭 | SDK response/stream 与 HTTP 资源均关闭 |
| T00-08 | 缺 provider Key、错误项目虚拟 Key | 缺个人 Key 时拒绝且不借部署 Key；错误项目虚拟 Key 到达上游前被 Proxy 拒绝 |
| T00-09 | Proxy 与 SDK 请求计数 | max_retries=0、num_retries=0、无 fallback；计数证明失败未隐式重发或改模型 |

## LiteLLM 流终态验真阻塞规则

针对 v1.104.2 已知 EOF/终态风险，必须比较受控上游原始终止事实、Proxy 的原始响应/事件、客户端收到的终态及错误状态。仅有 Proxy 下游 `finish_reason=stop` 或 `[DONE]` 不能证明上游成功完整结束。该风险只针对实测到的具体路径，不能概括为所有网络错误都会假成功。

若代理无法给业务层提供可验证的原始完成证据，停止该路径验收并报告原始请求、事件序列和脱敏日志。只考虑锁定版本的局部补丁、等待官方修复，或禁用该具体路由的 streaming；不得改成另一套 provider 适配器、扩大为所有 SDK 的重构，或降低完整性契约。

## 可复现验收路径

在隔离环境运行 CLI，探针启动固定版本 Proxy 和受控本地 upstream，先执行文本与两轮工具成功路径，再注入 EOF/截断/超时/SSE 错误/HTTP 错误。stdout 只输出版本、用例状态、耗时、脱敏错误类别及请求计数。使用合成的 Proxy 项目虚拟 Key 和合成 provider Key；运行前后核对没有读取现存凭据或发送外网 provider 请求。

## 任务完成条件

- SDK_LOCAL 与 PROXY_LOCAL 各自单独报告。SDK_LOCAL 只能表示 SDK 直连受控上游；本卡主要门槛是 PROXY_LOCAL。
- Test 文档记录精确基线 HEAD、实现 SHA、Python/SDK/Proxy/Docker 版本、完整执行命令、脱敏输出、旧测试对照和旧断言 diff；真实厂商状态保持单独的 PROVIDER_REAL=NOT_RUN。
- 原始终态、continuation、凭据隔离、资源关闭或请求计数有任一无法核验时，T00 为 BLOCKED，不得继续把本地链路描述为完整通过。
- T00-G 是共享服务运维交付卡；它不阻塞 T01/T04 本地开发，也不能由本地技术验真代替。

