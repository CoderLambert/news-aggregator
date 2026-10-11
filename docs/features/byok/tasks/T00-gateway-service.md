# T00-G · 共享 LiteLLM Proxy 运维交付契约

> **PLANNED**：本卡只定义共享网关交付边界，尚未创建服务仓库、配置、数据库或部署资源；所有运维验收均 NOT_RUN。

| 属性 | 内容 |
| --- | --- |
| 前置任务 | T00 本地 Proxy 技术验真 |
| 推荐规模 | 独立运维子卡 |
| 对应测试 | [Test T00-G](../tests/T00-gateway-service.md) |
| 阻塞关系 | T13 的完整真实功能矩阵与 T14 发布验收必须先通过；不阻塞 T01/T04/T09 本地开发，也不阻塞提供独立 DeepSeek 直连诊断。经 LiteLLM 的早期 DeepSeek 请求仍要求 T00 PROXY_LOCAL 通过并由用户单独确认 |

## 目标与边界

为新闻、知序、TranslateFlow 等业务项目定义可在隔离环境独立运行、升级、备份和回滚的 LiteLLM Proxy 服务交付。T00-G 只验收测试环境运行和运维契约；生产 go-live 由 T14 独立决定。执行时解析当时官方稳定 release，核验发布来源、签名/证明和 registry manifest 的实际 digest，再固定 tag+digest；不预选当前候选，也不使用 latest 或可变 tag。若部署候选不同于 T00 的 v1.104.2 EOF 风险复现夹具，分别记录两者并针对部署版本补做兼容验真。

Proxy 负责 provider 协议、可信模型路由、各业务项目独立的受限 virtual key、请求/并发限制、usage 采集与脱敏。每个业务项目有单独配置与虚拟 Key，可限制可用模型和请求额度。Proxy master key 仅用于隔离的运维/管理流程，不能进入任一业务运行容器。

Proxy 不建立新闻任务、新闻历史或网站用户表，不持有业务侧用户身份/任务状态。网站账号与 Proxy user/virtual key 不是同一身份。用户 provider Key 由拥有该用户连接的业务后端加密保存，并在每个获准请求中显式传递给受信 Proxy；项目虚拟 Key 仅授权业务后端使用该项目。缺用户 Key 或 Proxy 不可用时业务调用 fail closed，不能使用 Proxy 部署 provider Key、平台 Key 或其它用户 Key 兜底。

共享网关服务有自己的配置、Postgres、密钥和运维生命周期，不由 NewsHub Web/Worker 启停。NewsHub、知序和 TranslateFlow 不共享虚拟 Key、用户历史、缓存命名空间或权限。PROXY_LOCAL 未通过时，可向用户提供独立 DeepSeek 直连诊断供选择，但它不计为 T00 或网关验收；通过 T00 PROXY_LOCAL 后，才可经单独用户确认进行一次 LiteLLM 路径的早期 DeepSeek 文本冒烟，且不要求 T00-G 备份/升级运维验收全部完成。两种路径都不替代 T13 的产品功能矩阵。首轮真实 provider 仍只有 DeepSeek。

## 运维交付要求

- 单机部署即可；本卡不引入 Kubernetes、多副本 Proxy 或第二套业务任务框架。跨主机部署必须使用 TLS 和鉴权；同主机通信也应限制网络可达范围。
- 配套独立 Postgres，校验启动配置、模型路由、虚拟 Key 权限、预算/并发/限流及健康检查。预算只代表可执行的应用限制，不承诺绝对厂商账单硬上限。
- Proxy 与 Postgres 的日志、错误回执、回调和观测字段必须遮蔽 master key、项目虚拟 Key、用户 provider Key、提示词、正文、私有 continuation。
- 在同一 Proxy 部署中接入第二个独立通用 CLI 消费者，使用专属项目配置和不同 virtual key；验证其模型 allowlist 生效、未授权模型在到达 upstream 前被拒绝、日志/usage 可区分两个项目。停止或重启 NewsHub Web/Worker 时，第二个消费者应继续通过独立 Proxy 使用服务。
- 禁用部署级隐式 provider Key、跨模型 fallback、未授权重试和共享内容缓存。逐项验证空 Key/错误 project key/代理不可达时无绕行。
- 提供 secret 配置、密钥轮换、备份和恢复演练、健康检查、日志保留、升级评审、升级前备份与回滚步骤。升级仅通过单独批准的新镜像版本及 digest；回滚不得混淆数据库兼容性。
- 网关停机不影响 NewsHub 新闻浏览与已存历史；所有新 BYOK 上游请求须清晰失败，业务侧不得绕开 Proxy 直连供应商。
- T00-G 不是独立直连诊断或早期 LiteLLM 请求的前置条件。PROXY_LOCAL 未通过时，只可提供独立直连诊断供用户选择，不能作为网关验收；LiteLLM 路径须先 PROXY_LOCAL 全过，再由用户确认模型、安全合成输入、请求/输出上限与预算。T13 的完整产品功能矩阵仍按本卡运维门槛执行。T00-G 运维成功不等于任何供应商/模型兼容或业务功能 go-live。

## 明确不做

本任务不在本次文档 PR 中创建服务仓库、配置、云资源、Postgres、容器或部署；不操作线上环境/SSH，不保存真实用户 Key，不调用真实 provider，不把 Proxy 用作新闻任务系统，不把 master key 交给业务项目，不调整 T01/T04/T09 等业务卡的任务边界。

## 交付与验收

交付独立的服务配置和运维说明，固定经来源、签名/证明与 registry manifest 实际核验的镜像 tag+digest，含最小模型路由和项目虚拟 Key 权限策略；记录可脱敏复现的启动、配置验证、健康检查、错误 key 拒绝、重启、备份/恢复和版本回退证据。

T00-G 的 PASS 只说明共享网关运维链路符合约定。T13 子卡仍须按真实模型、地域、日期和有界请求单独记 PROVIDER_REAL；当前只获准 DeepSeek。T14 再单独评估业务发布。

