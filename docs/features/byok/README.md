# BYOK · 个人 API Key 与模型配置

> 本目录记录 BYOK 产品设计、单卡任务契约和实际执行证据。各任务状态以对应 Task/Test 文档为准；T02、T03、T04 已有独立实现分支等待评审，T04 的测试与未验证项见同编号 Test。

- 任务状态：T00/T00-G 仍为 PLANNED，T01 为 BLOCKED，T02/T03/T04 为 READY FOR REVIEW；后续任务按单卡推进。
- 架构：业务后端经独立 LiteLLM Proxy 访问 provider；用户 provider Key、业务项目 virtual key、Proxy master key 分别隔离。
- 首批六个 UI 预设为 OpenAI、Claude、DeepSeek、GLM、Qwen、Kimi，不构成 Proxy 支持上限；首轮 PROVIDER_REAL 只允许 DeepSeek。
- 业务项目继续拥有网站用户、个人 Key 加密存储、任务幂等/恢复/取消、事务和用户私有结果。Proxy 负责 provider 协议、受信路由、项目级受限虚拟 Key、限制和脱敏 usage。

## 导航

| 内容 | 文件 | 说明 |
| --- | --- | --- |
| 技术设计 | [BYOK_IMPLEMENTATION_PLAN.md](BYOK_IMPLEMENTATION_PLAN.md) | 角色边界、Key 与数据流安全、任务阶段和证据状态 |
| Codex 执行交接 | [CODEX_HANDOFF.md](CODEX_HANDOFF.md) | 固定架构、任务依赖、终态/续接门槛 |
| 页面设计 | [BYOK_PAGE_DESIGN_SPEC.md](BYOK_PAGE_DESIGN_SPEC.md) | 设置页交互、数据接收方与用户路径 |
| 静态原型 | [prototype/index.html](prototype/index.html) | 纯浏览器内模拟，不接 Proxy/API |
| 原型说明 | [prototype/README.md](prototype/README.md) | 本地预览与限制 |
| Task 总表 | [tasks/README.md](tasks/README.md) | T00–T14 单卡拆分与依赖图 |
| Test 总表 | [tests/README.md](tests/README.md) | SDK_LOCAL / PROXY_LOCAL / PROVIDER_REAL / UAT 证据规则 |
| T00 技术验真 | [tasks/T00-sdk-protocol.md](tasks/T00-sdk-protocol.md) | 锁定真实 Proxy + SDK + 受控 HTTP upstream |
| T00-G 运维契约 | [tasks/T00-gateway-service.md](tasks/T00-gateway-service.md) | 独立 Proxy/Postgres、密钥隔离、健康/脱敏/备份/升级 |
| 执行规则 | [tasks/EXECUTION_RULES.md](tasks/EXECUTION_RULES.md) | 单任务执行、基线与回归规则 |

## 固定决策摘要

- T00 EOF 风险复现夹具固定为 ghcr.io/berriai/litellm:v1.104.2@sha256:3d88bd757134a00e8c00237b85a021ab1f6d54abb9c1df750f411dbe7256a500。来源：官方 [v1.104.2 release](https://github.com/BerriAI/litellm/releases/tag/v1.104.2)；2026-10-11 查询 GHCR OCI index 的 Docker-Content-Digest 响应头为该 SHA256（[manifest endpoint](https://ghcr.io/v2/berriai/litellm/manifests/v1.104.2)）。此历史风险复现镜像不是 T00-G 部署推荐。
- T00-G 部署候选暂未解析。执行时核验当时官方稳定 release 的签名/证明及 registry 实际 manifest digest，分别记录版本和 digest；如与 T00 复现镜像不同，须用部署候选再执行兼容验真。
- 官方 SDK 仅作业务后端的 Proxy 客户端；不在 NewsHub 编写三套 provider 协议适配器。T00 必须验证三协议原始终态、工具双轮 continuation、凭据隔离、资源关闭与重试计数。
- 项目 virtual key 用于业务后端认证 Proxy；用户 provider Key 按用户授权经业务后端显式传入 Proxy。Proxy master key 仅用于运维，绝不进业务运行容器。
- 不传任意 user_config、api_base、headers、callback 或路由/fallback 配置；仅使用服务端可信 endpoint、model 和 credential 字段白名单。
- 用户正文/问题的接收方是业务后端、共享 Proxy 和用户选择的 provider；不写入日志/回调，首版共享内容缓存关闭。
- 没有用户 Key 或 Proxy 不可用时 fail closed；不得借部署/平台/其他用户 Key、直连 provider 或跨模型 fallback。
- T01 连接管理不依赖共享服务交付；T04/T09 可用临时本地 Proxy 和受控 upstream 验收。T00 PROXY_LOCAL 通过后可在独立用户确认下进行 DeepSeek 早期文本冒烟，该冒烟不依赖 T00-G，且不替代 T13 产品功能矩阵。T00-G 是 T13 完整真实功能矩阵与 T14 发布门禁的前置条件。
- SDK_LOCAL 与 PROXY_LOCAL 是本地合成测试；只有指定模型的获授权真实调用才是 PROVIDER_REAL。此前的 219 passed / 3 warnings 只作历史业务回归参考。

