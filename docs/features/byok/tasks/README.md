# BYOK 功能开发任务（T00–T14）

**任务按单卡推进，状态以各 Task 和对应 Test 记录为准。** T00/T00-G 仍为 PLANNED，T01 因缺少在途 worker 集成为 BLOCKED，T02、T03 与 T04 已完成限定范围实现并等待评审。T13 分为六个模型/厂商验证子卡。每张 Task 与 [同编号 Test 契约](../tests/README.md) 配对；T00-G 是新增的运维测试契约。

基线：`feat/byok-user-api-keys@ea2ce55ae22e19e1604e88031b824b68f2666cec`（执行当天仍须核对最新远端 HEAD）。本系列 Task 尚未在该 SHA 上实施；工作分支不得从更早功能分支重置。

| Task | 单次可验收的功能/门槛 | 依赖 | 体量 | 状态 |
| --- | --- | --- | --- | --- |
| [T00 本地共享网关技术验真](T00-sdk-protocol.md) | 锁定的真实 LiteLLM Proxy + 官方客户端 SDK + 受控 HTTP 上游跑通三协议、原始终态、工具往返、故障、Key 隔离、关闭与无重试；本地通过后可单独申请一次 DeepSeek 早期文本冒烟。 | 无 | S·技术门槛 | PLANNED |
| [T00-G 共享网关运维交付](T00-gateway-service.md) | 独立 Proxy/Postgres 服务配置、项目 virtual key、模型隔离、脱敏用量、第二个通用 CLI 消费者与 NewsHub 启停隔离、备份恢复、升级回退。此卡不部署于本次文档 PR。 | T00 | 运维子卡 | PLANNED |
| [T01 个人 Key 连接增删改停](T01-credentials.md) | 在正式 /settings/ai 页面管理网站用户自己的供应商 Key，掩码、替换、停用、删除，跨刷新恢复。 | 无 | M | BLOCKED |
| [T02 录入模型并显式验证](T02-models-and-tests.md) | 添加可信预设/手动模型 ID，主动测试文本与工具能力；本地测试使用临时 Proxy 和受控上游。 | T01、T00 本地技术门槛 | M | READY FOR REVIEW |
| [T03 用途默认模型设置](T03-preferences.md) | 为默认、问答、翻译、研究、问题推荐选择并保存模型。 | T02 | S-M | READY FOR REVIEW |
| [T04 新闻问答 BYOK 闭环](T04-article-chat.md) | 新闻详情通过业务后端调用 Proxy；本地开发可运行临时 Proxy+受控上游，不要求共享生产服务已交付。 | T03、T00 本地技术门槛 | M | READY FOR REVIEW |
| [T05 个人全文翻译最小闭环](T05-private-translation.md) | 一篇安全长度新闻持久生成、私有结果、重开恢复。 | T04 | M | PLANNED |
| [T06 长文分块完整翻译](T06-long-translation.md) | 长文分块且完整合并。 | T05 | M | PLANNED |
| [T07 翻译取消与显式重新生成](T07-translation-lifecycle.md) | 观看断开、服务端取消和重新生成语义正确。 | T05 | S-M | PLANNED |
| [T08 译文详情、问答与朗读同源](T08-translation-readers.md) | 私有译文被详情、聊天、朗读一致读取，换 Key 不删除历史。 | T05、T07 | M | PLANNED |
| [T09 首次个人模型深度研究](T09-research-first-run.md) | 许可工具研究、工具续接与完整持久结果；本地运行使用临时 Proxy+受控上游。 | T03、T00 本地技术门槛 | M | PLANNED |
| [T10 研究续问与安全恢复](T10-research-followup.md) | 断开后的只读恢复、取消与服务端 continuation。 | T09 | M | PLANNED |
| [T11 文章问题推荐与缓存](T11-suggestions.md) | 显式生成三条私有问题；首次进入不收费。 | T04 | S-M | PLANNED |
| [T12 个人 AI 使用记录](T12-usage.md) | 查看自己的调用用途、次数、已知/未知 Token。 | T02、T04、T05、T09、T11 | S-M | PLANNED |
| [T13 首批六个产品预设的真实验证](T13-providers.md) | 六个首批预设逐子卡记录真实模型、区域和能力；首轮唯一获准的真实厂商为 DeepSeek，其余保持 NOT_RUN。六个预设不是 Proxy 能力上限。 | T00、T00-G、T02、T04、T09 | 六个独立小验证 | PLANNED |
| [T14 业务发布验收](T14-release.md) | 整体业务安全、回归、功能开关和发布判定，并独立检查共享网关与获准 provider/UAT 证据。 | T04–T13、T00-G | M·发布门槛 | PLANNED |

## 关键拆分点

- T00 仅完成真实 LiteLLM Proxy、SDK 与受控上游的本地技术验真；不开发业务表、页面或共享部署。
- T00-G 是 T00 之后的独立共享服务运维交付子卡。T01 的凭据管理不依赖网关部署；T04/T09 的开发测试可启动临时本地 Proxy 和受控上游。生产请求没有可用网关时必须清楚失败，禁止直连 provider 或回退平台 Key。
- Proxy 管 provider 协议、可信路由、项目级受限虚拟 Key、限流和脱敏用量。业务项目继续拥有网站用户身份、用户 BYOK 密文、任务幂等/恢复/取消、事务和私有结果。
- 用户 provider Key 与业务项目 virtual key 不同。Proxy master key 只用于运维；绝不进入业务运行容器。每个项目各有 virtual key，彼此不共享用户身份、历史或缓存。
- 不传任意 `user_config`、`api_base`、headers、callback、路由/fallback 配置；业务后端仅构造受信端点、模型和凭据字段白名单。
- 新闻正文/问题的接收方是业务后端、共享 Proxy 和用户选择的 provider；日志与回调不得包含 Key 或正文；首版共享内容缓存关闭。
- 本地测试级别分开记：SDK_LOCAL 是真实 SDK+受控上游；PROXY_LOCAL 是真实 Proxy+SDK+受控上游；PROVIDER_REAL 才是指定真实 provider/model 的线上请求；UAT 是最终用户操作。四种证据不能互相代替。
- T00 PROXY_LOCAL 通过后可独立用户确认一次 DeepSeek 早期文本冒烟，不等 T00-G；该记录不代替 T13 矩阵。T13 的完整 provider 功能矩阵仍要求 T00-G，其他首批预设维持 NOT_RUN，不因 PROXY_LOCAL 成功声称兼容。产品首批六个预设不限制未来 Proxy 支持范围。
- T14 之前独立验收服务健康、安全、日志、备份/恢复、升级与回退。网关故障时新闻与保存历史仍可读，新 AI 请求失败关闭。

## 推荐推进顺序

```text
T00 ─→ T00-G ─→ T13 完整产品功能矩阵 / T14 网关验收
 └──→ [可选 DeepSeek 早期文本冒烟：单独确认，不依赖 T00-G]

T01 → T02 → T03 → T04 → T05 → T06
                          └────→ T07 → T08
            └───────────────→ T09 → T10
            └───────────────→ T11
T01 和 T04 的本地/业务开发不等待 T00-G 共享服务交付
T02 开始共享 AICallAttempt 账目 → T12
T13-A..F 每个指定模型独立记 PROVIDER_REAL，首轮仅 DeepSeek获准
T14 业务发布验收
```

## 每次给 Codex 的最小命令

> 请仅执行 `docs/features/byok/tasks/T00-sdk-protocol.md`（下一轮替换为当前唯一获准的 Task），并读相同 ID 的 Test 契约及 [执行规则](EXECUTION_RULES.md)。先核对 origin 功能分支 HEAD、既有工作树、AGENTS 与旧测试基线。不得使用既有 provider Key、全局环境 Key 或运行真实厂商请求，除非单独明确授权。完成一张可审核任务 PR，base 为 `feat/byok-user-api-keys`；不合并、不开始下一个 Task。

## 状态规则

`PLANNED` 计划；`WORKING` 正在实现；`BLOCKED` 关键依赖或契约范围内集成缺失；`READY FOR REVIEW` 本卡限定范围实现与验证完成，仍公开记录的 PARTIAL/NOT_RUN 不得表述为完整验收；`CHANGES_REQUESTED` 违反设计/缺证据；`PASS` 完整契约有实际证据；`MERGED` 审查后合并入 BYOK 功能分支。文档或 mock 不能构成 SDK/Proxy/provider PASS。

