# Test T00-G · 共享 LiteLLM Proxy 运维交付契约

> **PLANNED / NOT_RUN**：尚未创建或部署共享网关服务，本文件为后续验收表。

对应：[T00-G Task](../tasks/T00-gateway-service.md)。

| 用例 | 场景 / 故障注入 | 正确性约束 | 状态 |
| --- | --- | --- | --- |
| T00G-01 | 校验官方镜像发布、签名/证明、版本和 OCI digest | 生产配置固定同一受验证 tag 与 digest，不使用 latest | NOT_RUN |
| T00G-02 | Proxy / Postgres 单机启动和错误配置 | 配置检查和健康检查准确报告依赖、路由和 DB 状态 | NOT_RUN |
| T00G-03 | 每项目独立受限 virtual key | 权限、模型 allowlist、并发/请求预算正确；项目凭据不跨用 | NOT_RUN |
| T00G-04 | Proxy master key 与业务运行环境检查 | master key 只保留在运维边界；任何业务容器均不可读取 | NOT_RUN |
| T00G-05 | 请求无 provider Key、无效 Key 或 Proxy 不可达 | 业务请求 fail closed；无部署 Key、平台 Key、其它用户 Key 或直连 provider fallback | NOT_RUN |
| T00G-06 | 日志、回调、异常和指标脱敏 | 不含任何 Key、提示词、正文或 continuation | NOT_RUN |
| T00G-07 | 重启、Postgres 备份与隔离恢复演练 | 配置和路由恢复一致；含清楚的 RPO/RTO 记录和密钥恢复说明 | NOT_RUN |
| T00G-08 | 固定版本升级失败与回滚 | 有升级前备份、版本/digest 审核、恢复步骤；无盲目 schema 降级 | NOT_RUN |
| T00G-09 | 网关停机期间 NewsHub 运行 | 新闻阅读和已保存历史继续可读，新 AI 请求失败关闭 | NOT_RUN |
| T00G-10 | 真实厂商请求门禁 | T00-G 不计 provider compatibility；真实请求只按单独批准的 T13 执行 | NOT_RUN |

## 执行证据（后续实际执行时填写）

| 项目 | 结果 |
| --- | --- |
| 本卡状态 | **NOT_RUN** |
| 精确基线 HEAD / 实现 SHA | NOT_RUN |
| Proxy 镜像来源、签名、tag、digest | 候选为 `v1.104.2@sha256:3d88bd757134a00e8c00237b85a021ab1f6d54abb9c1df750f411dbe7256a500`；实际验证 NOT_RUN |
| Docker / Postgres / OS 版本 | NOT_RUN |
| 配置验证、健康检查、项目虚拟 Key | NOT_RUN |
| 安全和脱敏检查 | NOT_RUN |
| 备份恢复、升级与回退 | NOT_RUN |
| PROVIDER_REAL | **NOT_RUN；运维验收不代表真实厂商兼容** |
| 业务回归 / 用户 UAT | 分别记录；均 NOT_RUN |
| 未验证或阻塞原因 | 尚未实现、部署或运行 |

不得把文档中候选版本/digest 视为已验证生产服务。

