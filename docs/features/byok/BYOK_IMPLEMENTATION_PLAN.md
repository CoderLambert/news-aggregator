# 新闻资讯项目 BYOK：确定实施方案与验证记录

版本：1.0 · 2026-10-11  
适用仓库：CoderLambert/news-aggregator  
交付性质：设计与任务契约；当前独立分支仅更新文档和静态原型，没有改业务实现、部署网关或调用真实厂商接口。

## 0. 决策摘要

采用独立共享 LiteLLM Proxy + 业务后端调用 + 用户自有 provider Key 显式逐请求传递。Proxy 使用固定官方镜像，不随 NewsHub 部署或启动。新闻、知序和 TranslateFlow 等业务项目分别持有受限 Proxy virtual key；各自继续拥有网站用户身份、用户 Key 加密存储、任务/事务和私有历史。

当前记录的镜像候选为 ghcr.io/berriai/litellm:v1.104.2@sha256:3d88bd757134a00e8c00237b85a021ab1f6d54abb9c1df750f411dbe7256a500。这是待 T00 验证签名、digest 和端到端行为的候选，不是生产验收。Proxy 自有 Postgres、配置、密钥与运维生命周期，需在 T00-G 独立交付；本次只改 BYOK 文档，不建服务仓库、不部署或调用真实 provider。

边界按所有权划分：
- 业务项目：登录用户、其 provider Key 的加密托管和所有权、可信连接/模型/输入快照、选择、任务幂等/恢复/取消、调用记账、事务与结果权限。
- LiteLLM Proxy：provider 协议、可信模型路由、每个业务项目的受限 virtual key、请求限制和脱敏 usage。
- provider：接收经用户明确授权的提示词与请求，按其服务条款计费。

Proxy master key 仅用于隔离的运维/管理 API，绝不进入业务运行容器。项目 virtual key 与用户 provider Key 是不同凭据。用户 Key 只能由对应业务后端在授权操作中从密文存储解出，并按 T00 实证确认的白名单 credential 字段逐请求传给受信 Proxy；缺 Key 即失败，禁止部署/环境 provider Key、平台 Key、其它用户 Key、直连 provider 或跨模型 fallback 兜底。

初始六个产品预设为 OpenAI、Claude、DeepSeek、GLM、Qwen、Kimi；这是首批 UI/测试范围，不是 LiteLLM 的 provider 架构上限。PROVIDER_REAL 首轮只对 DeepSeek 开放；其它厂商保持 NOT_RUN，直至分别获准并按真实模型/地域验收。

业务通过官方客户端 SDK 访问 Proxy，由 Proxy 管理 Responses、Chat Completions、Messages 上游协议。NewsHub 内不实现三套 provider 适配器。T00 必须真实运行锁定 Proxy + 官方 SDK + 受控 HTTP upstream，核验原始终态、continuation、工具往返、请求计数和 Key 隔离。v1.104.2 EOF/终态风险是特定路径验证点；若原始完成证据无法穿过 Proxy，局部修复、等官方修复或禁用该路由 streaming，不能降低完整性门槛或改回另一套架构。

当前新 SDK_LOCAL、PROXY_LOCAL、PROVIDER_REAL、T00-G 与 UAT 均未执行。本次既有 219 passed / 3 warnings 记录仅是旧业务回归的历史基线，不是新网关验收。本分支只更新文档。

## 1. 代码基线与事实

BYOK 功能分支当前已核对 HEAD 为 ea2ce55ae22e19e1604e88031b824b68f2666cec；本次文档变更在独立 task 分支进行，后续执行仍要重新核对远端 HEAD、未提交改动和同环境测试基线。

| 引用 | 精确 SHA | 使用方式 |
| --- | --- | --- |
| feat/byok-user-api-keys | ea2ce55ae22e19e1604e88031b824b68f2666cec | 当前文档更新的已核对基线 |
| feat/news-public-readiness | b874405f31ae303e772d1ed6ef618b68938febed | 原计划所引用的代码观察基线，不再作为新任务分支起点 |
| main | 8c2823e1fcf8cbea38e9bb7c4e98a33232025fbd | 原设计调研中的历史对照 |

建议后续单任务从执行当天核对的最新 BYOK 功能分支 HEAD 创建独立分支，不重置用户工作树。旧 readiness 源码记录不表示已部署或发布验收通过。每次仍须检查实际上级与子目录指导文件。[S1]

### 已存在，应直接复用

- ResearchRun / ResearchRunEvent：用户隔离、幂等键、每个会话唯一活动任务、事件序号、租约、提交 CAS、显式排队恢复、只读 GET 重放。[S4]
- ChatGPTTranslationTask：持久任务、generation、provider_started、进度、最终结果、租约和取消。[S3]
- 共享的受限后台线程执行器、现有前端 Query 缓存与 SSE 工具。[S5]
- 现有 Session 认证、CSRF、用户聊天写入约束、公共模式开关、译文共享机制。公共机制保留，但新 BYOK 不自动参与公共发布。[S6][S7]

### 已确认需要改的接入边界

| 位置 | 已观察事实 | 定向修改 |
| --- | --- | --- |
| `research/agent_loop.py` | 从全局 get_clients 获取客户端，消息序列化丢弃 reasoning_content | 注入用户执行快照；由 ProxyClient 保留并校验服务端续接状态 |
| `public_policy.py` + research/job_manager | production 条件直接拦截研究 | 保留站点总开关；凭据策略在认证和服务端解析后判断，并覆盖 Worker |
| `chatgpt_subscription_jobs.py` | translation 任务是订阅专用外键；read handle 的 wait_for_update 可派发 queued 工作 | 扩展凭据变体；新只读恢复不能复用带派发副作用的方法 |
| `subscription_views.py` / 订阅保存路径 | 私有翻译与公共共享发布相连 | BYOK 私有提交分支不得调用 publish_translation |
| `serializers.py`、`tts_service.py`、聊天上下文 | 个人译文读取主要识别活动订阅连接 | 共用个人结果解析入口；读取历史不要求 Key 仍有效 |

这里的业务边界来自源码观察；旧隔离函数实验不等于完整 Proxy 行为，也不能写成已经复现六家厂商的线上失败。[S5–S9]

## 2. 产品范围

### 本期业务产品目标

- 登录用户添加多个自有 API 连接；同一 provider 可登记多个账户。
- 每个连接添加多个模型配置；预置目录版本化，也允许保存手动 model ID。
- 一个默认模型，文章问答、全文翻译、推荐问题、深度研究可分别覆盖。
- 保存、模型发现、用户主动模型测试是分开的动作；测试前提示输入会经业务后端、共享 Proxy 发送到选定 provider，可能收费。
- 已保存状态、credential 可用状态、能力验证和最近测试结果分开显示；保存成功不等于模型可调用。
- 各功能显示实际使用的 provider、model 和结果来源。
- 个人结果默认私有，跨设备按网站用户身份恢复；浏览器不保存 provider Key。
- 换/删 Key、停用连接不删除历史个人结果。

### 本期不做

不在 NewsHub 内置 Proxy/网关服务，不把 Proxy 用作业务任务队列，不开发模型市场或自动跨 provider fallback，不提供 Coding/Token Plan/订阅 Token 代替通用 API Key，不开放任意用户 Base URL，不让浏览器直连 Proxy/provider，不改订阅登录能力，不换研究 Agent 框架，不开发第二套业务任务系统或完整计费中心。

Proxy 服务的独立配置、运行、数据库和运维交付属于 T00-G；不由 BYOK 业务进程管理。以后可增加可信 provider 预设或模型，不将首批六个 UI 预设写死成架构上限，也不因 LiteLLM 路由成功就声明 provider 的每个模型/region/功能均已验证。

## 3. 厂商、路由与客户端方案

| 首批产品预设 | Proxy 路由的上游协议 | 地域/端点配置 |
| --- | --- | --- |
| OpenAI | Responses（优先）；必要 Chat Completions 单独验收 | 官方端点 |
| Claude | Anthropic Messages | 官方端点 |
| DeepSeek | Chat Completions；思考模式需保留 reasoning_content | 官方通用 API 端点 |
| GLM | Chat Completions | 智谱国内与 Z.AI 分别为可信 preset |
| Qwen | Chat Completions | 百炼地域与业务空间端点分别配置 |
| Kimi | Chat Completions | Moonshot 国内、国际端点分别配置 |

后端用 OpenAI/Anthropic 官方客户端 SDK 连接受信 Proxy endpoint；Proxy 负责上游 provider 协议、密钥路由和响应转换。NewsHub 不再内置三套直接访问 provider 的协议适配器，也不让模型配置改变 Proxy URL。通过 Proxy 的实际 SDK/端到端能力由 PROXY_LOCAL 测试证明；通过某真实厂商/模型/region 的能力仅能由获授权的 PROVIDER_REAL 证明。首轮只针对 DeepSeek 申请真实调用。

可信的初始通用 API endpoint preset：

    OpenAI       https://api.openai.com/v1
    Anthropic    https://api.anthropic.com
    DeepSeek     https://api.deepseek.com
    GLM CN       https://open.bigmodel.cn/api/paas/v4/
    Z.AI         https://api.z.ai/api/paas/v4/
    Qwen 北京    https://dashscope.aliyuncs.com/compatible-mode/v1
    Qwen 新加坡  https://dashscope-intl.aliyuncs.com/compatible-mode/v1
    Kimi 国际    https://api.moonshot.ai/v1

endpoint 只存在于业务端和 Proxy 管理配置的受信注册表，普通用户不能提交任意完整 URL。Qwen WorkspaceId 等附加项只允许受限值，由管理端固定模板拼接；地域或 endpoint 变更需创建新连接/重新授权，不得悄悄把已保存 Key 发往新主机。

套餐边界：百炼 Coding Plan、Token Plan 仅限交互式 AI 工具，不能用于后端服务。此站只接可用于后端服务的通用按量 API；不把用户 Coding 环境变量或 ChatGPT 订阅凭据移植到网站 BYOK。其它套餐需逐个核对条款。

## 4. 模块和 Proxy 请求契约

    浏览器
      -> NewsHub Django Session + CSRF + 用户权限
      -> 解析当前用户拥有的连接/模型与任务意图，冻结 ExecutionSnapshot
      -> 现有聊天 / 研究 / 翻译业务任务与提交事务
      -> Business ProxyClient：项目 virtual key + 本次用户 provider Key + allowlisted request
      -> 独立 LiteLLM Proxy：模型路由、上游协议与 provider 调用
      -> 用户明确选择的 provider

    Proxy 上游原始终态 -> 业务完整性/工具策略校验 -> DB 结果 + succeeded + complete 同事务

    GET 历史 / GET 重放 -> 用户隔离持久记录；不创建任务、不连接 Proxy、不启动 executor

业务侧模块仍围绕用户配置和任务边界：

| 模块 | 职责 |
| --- | --- |
| services/ai/registry.py | 可信 provider/地域/模型 alias、能力白名单及 Proxy route 注册 |
| services/ai/credentials.py | 用户 Key 的应用内加密、所有权、epoch 和生命周期；绝不将 Key 写入日志 |
| services/ai/contracts.py | ExecutionSnapshot、ModelTurn、ModelEvent、安全 ProviderError 与服务端 continuation 类型 |
| services/ai/routing.py | 用户默认/功能选模；读取既有幂等记录；冻结非秘密执行配置 |
| services/ai/proxy_client.py | 业务 project virtual key、Proxy endpoint、受控 provider credential 字段、请求超时、用量和脱敏错误 |
| services/article_translations.py | 详情、聊天、朗读解析同一用户结果身份 |
| 现有 research/translation/chat 模块 | 继续负责业务任务、锁/租约、工具许可、恢复、取消、事务与结果访问 |

不在 NewsHub 新建 provider 的 Responses/Chat/Messages 适配器；不把 LiteLLM proxy 做成用户任务系统。公共模型层可由 Proxy 支持多种 provider，但业务 API 只接受自有 model config ID 和受信 route，不透传任意 provider options。

核心内部接口（签名契约，非已实现代码）：

    resolve_execution(user, task_kind, model_config_id=None) -> ExecutionSnapshot
    complete_turn(execution, conversation, tools, guard) -> ModelTurn
    stream_turn(execution, conversation, guard) -> Iterator[ModelEvent]
    read_task(user, task_id) -> TaskView
    read_article_translation(user, article_id, artifact_id=None) -> TranslationView

ModelTurn 至少包含可见文本、经过 allowlist 的完整工具调用、finish、usage、服务端专用 continuation。不能把 continuation 序列化到普通聊天消息、API 可见字段、日志、回调或浏览器缓存。

### Proxy continuation 与可见消息分离

业务 continuation 由 Proxy/API 回合实际返回的 provider 原生信息组成并带协议/版本标签，限定大小、按用户和会话隔离。T00 PROXY_LOCAL 必须证明 Responses output items、Anthropic thinking/signature、Chat reasoning_content 能在两轮工具 continuation 中正确经过 Proxy；SDK_LOCAL 直连 upstream 不够。若 Proxy 特定客户端/路由无法往返某协议原始状态，在 T00 记录具体事件/请求/输出并停止对应路径，不可悄悄改为直接 provider adapter。

公开消息是从服务端会话状态生成的白名单投影。续接字段不构成 Key 来源、工具 allowlist、用户权限或执行配置。研究会话首版固定 provider/model/route 配置；切换模型新开会话，可显式复制可见研究结论，不迁移不兼容的原始续接状态。

## 5. 数据设计：扩展现有执行数据，而非重建

### 新增个人配置数据

| 模型 | 核心字段 / 约束 |
| --- | --- |
| UserAIConnection | user、provider_id、endpoint_profile/version、加密 Key、encryption_key_id、credential_epoch、enabled/deleted；终点不可任意修改 |
| UserAIModelConfig | connection、model_id、受限参数、revision、能力/测试快照；归属通过 connection 解析 |
| UserAITaskPreference | user、task_kind（含 default）、model_config；unique(user,task_kind) |
| AICallAttempt | user、task/request identity、attempt_id、用途、snapshot_digest、provider_request_id、状态、Token（nullable）、耗时；无 Key/正文/原始错误 |
| UserSuggestedQuestions | user、news、source_hash、config_digest、prompt_version、questions；相同用户和输入配置的缓存约束 |

数据库外键不能单独保证跨表 user 相同。偏好、连接、任务、结果的关系须在统一服务入口做 owner 校验，并在提交 CAS 中再次检查；不能把它错误描述成普通 ForeignKey 已经提供的保证。

### 扩展已有任务和译文表

1. **ResearchRun**：增加 execution_snapshot/version、execution_digest。其幂等、事件序号、租约和提交事务不更换。
2. **ResearchSession**：增加绑定执行配置/协议标签和服务端 provider_state；现有 messages 是可见视图，序列化禁止泄露 provider_state。
3. **ChatGPTTranslationTask**：保留原数据库表与旧入口，增加 `credential_kind`、可空 `api_connection`、BYOK request identity 与 execution snapshot。原 subscription connection 改为可空；旧行默认 subscription。
4. **ChatGPTArticleTranslation**：同样扩展凭据变体、目标语言、配置摘要、提示词版本、来源任务。BYOK 结果一旦完成保持不可变；显式重新生成建立新任务和新结果，不静默覆盖曾经引用的结果 ID。
5. 旧订阅任务原有“按 generation 更新”的语义保留。BYOK 每次显式重试采用新任务 ID/幂等键；同一幂等请求只恢复原任务。

数据库 CHECK 至少包含：

```text
subscription: subscription_connection 非空，api_connection 为空
api_key:      api_connection 非空，subscription_connection 为空
```

BYOK 任务不得持有共享租约；私有结果提交分支不得调用公共发布函数。追加 BYOK 条件唯一约束 `(user, idempotency_key)`；保留旧订阅唯一约束。BYOK 同一输入和配置的活动翻译只允许一个；不同幂等键并发命中已有活动任务时返回明确冲突和该用户可恢复的 task_id，不创建第二次调用。

BYOK 结果按来源任务唯一保存；缓存查找用 `(user, news, source_hash, target_language, execution_digest)` 的索引读取最近一次完整结果，不以 credential_epoch 或当前启用状态作为历史读取条件。

连接删除采用停用、清除密文、递增 credential_epoch 和保留无秘密墓碑记录。删除连接不级联删除已完成内容；删除网站账户走独立的用户数据删除策略。本站删除不等于撤销厂商平台的原始Key；需要彻底撤销时提示用户在厂商平台操作。数据库备份中旧密文的保留/到期删除也应说明，不能承诺线上清空等于所有备份立即擦除。

## 6. 必须保持的不变量

### 6.1 身份与幂等

- owner 来自登录 Session；客户端不能提供受信任 user_id。
- request_hash 对客户端明确提交的意图计算；execution_digest 对服务端冻结后的执行配置计算，二者不是同一事实。
- 命中已有 `(user, idempotency_key)` 后先验证原始请求并返回原任务，不重新读取当前默认模型。用户期间改默认模型，不影响同一请求的恢复。
- 同键不同请求返回 409，不另起付费任务。
- 对一次会话/文章运行的旧回执，用 user、task_id、attempt generation、lease token 校验后才能提交。

### 6.2 冻结真实输入

execution_snapshot保存非秘密执行配置；另在现有任务记录中保存受大小限制、用户隔离的input_snapshot，包含本次实际原文/所需历史和摘要。排队后原文发生变化，不得用新正文搭配旧source_hash发起请求。提示词模板版本固定，缓存摘要覆盖真实输入而不只是article_id。

BYOK运行期间原文变更但任务/凭据仍有效时，可把完整结果保存为旧原文版本的私有结果；读取当前文章时显示stale，不替换新正文对应译文。旧订阅路径原本的拒绝旧原文发布行为不在本期改写。这一BYOK语义要在新增测试中明确，不能据此修改旧订阅断言。

### 6.3 选择、凭据、任务三个版本分开

- selection/model revision：决定未来任务；已开始任务不受默认选择变化影响。
- credential_epoch：换 Key、停用、删除时递增，阻断旧凭据后续调用。
- task generation / run_token：决定哪个执行者有提交权限。

不要用一次“改默认模型”把已经成功保存的结果变成无效，也不要让旧 Key 测试响应覆盖新 Key 状态。

### 6.4 服务端任务、连接和展示分开

| 情况 | 固定语义 |
| --- | --- |
| 关闭面板 / Abort SSE | 只停止订阅；服务端任务继续，UI 不显示 cancelled |
| 明确取消任务 | POST cancel；服务器确认和封禁提交后才显示任务取消 |
| 重新打开已有会话 | GET 状态/结果，再 GET 事件；不自动创建新任务 |
| queued 从未调用上游 | 显式 POST resume 或已授权调度器恢复同一任务 |
| running 租约过期、结果不明 | interrupted；不自动重发模型请求 |
| 原文已变更 | 历史结果仍是已保存；当前文章匹配状态标为 stale，不冒充新版译文 |
| 重复事件 / 迟到响应 | 按 task identity + sequence / generation 去重与丢弃 |

现有 translation read handle 的 wait_for_update 有 queued 派发行为。不能把它接到新的只读 GET。GET 的租约状态可以通过只读投影报告过期；修复/派发动作放在显式写入口或 Worker。[S5]

### 6.5 完整终态后再提交

| 协议 | 完整模型回合证据 | 不能当成最终任务成功 |
| --- | --- | --- |
| Responses | 原始 response.completed 且状态完整，区分文字回答与工具调用 | EOF、response.failed、response.incomplete、单有 delta |
| Chat Completions | 收到上游实际 finish_reason；最终正文接受 stop | EOF、length、content_filter；tool_calls 只是中间回合 |
| Messages | 原始 message_stop，加有效 stop_reason；最终正文接受 end_turn | 单有文字、max_tokens、error；tool_use 只是中间回合 |

`complete` 是持久化完成事件，不是上游迭代结束事件。事务内完成结果、任务 succeeded 和最终事件写入；事务失败时三者均不报告成功。进度只能作为 partial 展示，不写入完整译文缓存。

用户拒绝/安全拒绝属于单独可展示结果；翻译不得把拒绝文本登记成完整译文。工具回合缺失/截断参数不执行工具；仅执行当前运行允许的工具并验证参数。文章、检索结果属于不受信任数据，不得改变系统策略。[S10][S11]

### 6.6 不承诺无法证明的 exactly-once

本地数据库事务不能与第三方推理服务组成一次原子事务。在放行请求前持久记录“可能开始上游请求”，释放数据库事务后才进行网络调用。进程在记录后但发送前崩溃也按不确定状态处理，宁可让用户明确重试，不隐式多扣费。

首版 SDK 自动重试设为 0，不使用跨厂商自动回退；超时/中断不透明重发。暂停/撤销会阻断尚未获准的新调用并封禁旧提交，但已经发出的请求只能尽力终止，厂商仍可能计费。这个边界在 UI 和日志中必须如实表达。

## 7. 密钥、Proxy 与数据流安全

- 用户 provider Key 采用现有 cryptography 库 AEAD 加密，AAD 绑定 owner、connection_id、provider/endpoint profile、credential_epoch、格式版本。应用加密主密钥置于业务项目部署 Secret，不进入数据库、仓库或日志；缺 Secret 时 fail closed。
- 用户 Key 只在所属业务后端获准发起模型调用时从存储短暂解密，经 TLS 显式发送给受信 LiteLLM Proxy 已验证的 per-request credential 字段；候选字段能力须由 T00 实测。Proxy 项目 virtual key 在后端服务 Secret 中，用于认证该项目对 Proxy 的访问。两者不能混用。
- Proxy master key 只用于隔离的服务运维和管理 API。它不进入业务项目、NewsHub Web/Worker 或任何浏览器。每个业务项目单独受限 virtual key 和模型 allowlist，项目之间不共享用户身份、密钥或内容缓存。
- 禁止客户端控制/透传 user_config、api_base、任意 headers、callback、route/fallback/retry 选项或 Proxy 管理参数。业务按连接和 model config ID 从受信目录构造 endpoint/model/credential allowlist。阻断私网与云元数据出站地址；DNS、重定向及实际部署 egress policy 须验收。
- Proxy、业务日志、异常、回调、用量和 tracing 均需遮蔽 provider Key、project virtual key、master key、新闻正文、问题、工具私参和 continuation。使用 request ID 关联 Proxy 记录与 AICallAttempt。
- 明确告知用户：新闻正文/问题会由业务后端发送给独立共享 Proxy，再到用户选择的 provider。首版关闭共享内容缓存。Provider 接收数据及计费条款由用户所选服务商决定。
- 缺 Key、密文不可解、Proxy 不可达、错误 project virtual key 都明确失败；禁止使用 Proxy 环境 provider Key、平台服务 Key、管理员 Key、别的用户 Key、订阅凭据、直接 provider 调用或模型 fallback 兜底。
- 保留旧订阅密文格式/权限边界。旧订阅任务默认保持既有 credential_kind；BYOK 调用不修改订阅 OAuth token AAD/HKDF。
- Proxy 与业务数据库是独立服务生命周期；NewsHub 停止/重启不得意外改变网关/Postgres。网关故障时新闻浏览和已保存历史可读，新 AI 请求 fail closed。
- 预算/限流是应用可执行的请求约束，不许承诺等同 provider 账单的绝对硬上限；取消请求也不能保证已发出的 provider 请求停止计费。

## 8. 前端与 API

### 前端最短用户路径

设置 → AI 服务 → 选择厂商/地域 → 输入 Key → 保存 → 添加模型 → 显式测试 → 设置默认 → 在新闻详情发起一次操作 → 查看结果来源 → 重新进入恢复结果。

沿用现有路由、组件风格、Query和SSE工具，增加 AIConnectionsSettings、ConnectionForm、ModelConfigForm、FeatureModelPicker 等小组件；不把无关UI重构混入本次工作。

查询缓存包含 viewer_id；切换账户取消旧请求并清除相关缓存和Key表单状态。模型配置 mutation、测试回执都按 owner/config revision fencing。配置页支持移动宽度、密码字段、键盘焦点和明确错误说明。

### 接口草案（沿用仓库命名风格实现）

| 接口 | 行为 |
| --- | --- |
| GET /api/ai/providers/ | 无秘密的可信厂商目录 |
| GET/POST /api/ai/connections/ | 当前用户连接列表/新增 |
| PATCH/DELETE /api/ai/connections/{id}/ | 更新显示名/开关；删除清除Key |
| PUT /api/ai/connections/{id}/key/ | 替换Key并更新epoch；不回传Key |
| GET /api/ai/connections/{id}/models/ | 已知模型和发现状态 |
| POST /api/ai/connections/{id}/models/refresh/ | 显式刷新；不支持时返回说明，可继续手填 |
| POST /api/ai/connections/{id}/test/ | 用户显式发起有界模型测试，经业务后端→共享 Proxy→所选 provider；注明发送对象和可能计费 |
| /api/ai/model-configs/ | 模型配置CRUD，owner限定 |
| GET/PATCH /api/ai/preferences/ | 默认与功能偏好 |
| GET /api/ai/usage/ | 本站调用统计，不伪装厂商余额 |

现有生成接口添加 model_config_id 和 Idempotency-Key；旧订阅接口通过兼容包装保留。新增中性的 GET translation task/result 和显式 resume/cancel 入口。任务返回 task_id、snapshot摘要；结果返回 result_id、model、source_hash、完成时间。前后端字段由一个契约版本维护，不重写全套SSE协议。

首次进入页面只读已有推荐问题/公共缓存/固定模板，不自动扣用户Key。点击“生成/换一批”才发起 BYOK；如未来要自动推荐，应让用户单独开启。只返回经过校验的3条问题，模型输出无效返回明确状态和免费模板，不能把模板记作生成成功。

## 9. 译文、聊天上下文与朗读的同一身份

统一读取顺序：显式指定且属于当前用户的 result_id → 当前用户匹配文章版本的个人结果 → 公共结果 → 兼容旧数据。结果来自不同模型时展示来源；用户主动重新翻译不能被公共缓存悄悄替代。

具体生成模式区分 `prefer_existing` 与 `generate_private`；后者在明确用户动作下使用个人模型，不写入共享译文。已存在任务的恢复始终按 task_id/result_id，不按“当前默认模型”重新查一个不同任务。

详情、聊天上下文、TTS使用同一解析器。中文朗读沿用现有TTS提供方，私人译文的音频缓存命名空间包含用户与结果身份。只改内容解析，不趁机开发TTS多厂商配置。

结果长度和模型上下文按配置控制；长文切块保留Markdown代码/链接边界，逐块完整后才合并。固定32000输出限制或纯字符截断不能当作所有模型通用策略。超限时必须提前给出处理方式，不能把截断结果保存为完成。

## 10. 用量、部署与迁移

AICallAttempt记录每次上游尝试而非每条SSE订阅。Token缺失为unknown/null，不能显示0；请求已经发送但结果不明记录unknown。测试、推荐问题、研究多轮分别计入。同一GET恢复的Provider调用数必须为0。

首版仅有本地可执行的输出上限、研究轮数、请求/并发限制与本站用量。费用能可靠计算时显示带币种和价格版本的估算；不能保证用户在其它应用的消耗或厂商真实余额，也不做“绝不会超支”的承诺。

业务继续沿用已有执行器和限流。共享 LiteLLM Proxy 与独立 Postgres 单独部署、管理和升级，不由 NewsHub 容器启动。T00-G 验证配置/健康、项目 virtual key、脱敏、备份恢复和升级回滚；服务故障时新 BYOK 请求失败关闭，旧新闻和历史结果仍可读。当前业务侧单执行器部署边界保留，不借共享 Proxy 引入水平扩展或第二套任务队列。新接口还须验证 Proxy 请求超时和受限资源预算；预算不等于厂商账单绝对硬上限。

迁移顺序：

1. 同环境记录不改动测试的基线、依赖版本、现有失败与选定Git SHA。
2. 增量建配置表并扩展任务/结果字段；旧行默认subscription；先在数据库副本运行迁移与回滚检查。
3. 调整现有任务执行的凭据适配边界，旧接口响应和行为保持兼容。
4. 增加BYOK私有结果读取、统一详情/聊天/TTS解析；历史读取不需要有效Key。
5. 前端在服务端能力旗标开启后显示配置入口；AI_BYOK_ENABLED默认关闭，先局部测试再开放。
6. 回退优先关闭新生成旗标，保留已生成私有内容可读。新数据产生后不得执行会丢掉BYOK字段的盲目降级迁移。

## 11. 确定的实施任务和结束条件

> 阶段路线按 [tasks/README.md](tasks/README.md) 拆为 T00–T14 单卡交付，并由同编号 Test 契约验收。T00 是本地 Proxy 技术门槛，T00-G 是后置独立网关运维卡；它们不得并入业务表、页面或第二套任务系统。

| ID | 工作 | 依赖/完成标准 |
| --- | --- | --- |
| T00 | 本地共享网关端到端技术门槛 | 官方 LiteLLM Proxy 固定版本/digest + 官方客户端 SDK + 受控 HTTP upstream。三协议终态、异常、工具双轮、continuation、显式 credential isolation、资源关闭与重试/请求计数均有原始证据 |
| T00-G | 独立共享 Proxy 运维交付 | 独立配置/Postgres、每项目 restricted virtual key、master key 运维隔离、健康/配置检查/日志脱敏/备份恢复/升级回退；真实 provider 仍单独验收 |
| P1 / T01–T04 | 连接/模型/偏好/新闻问答 | T01 不调用 Proxy；本地测试用临时 Proxy + controlled upstream；生产缺网关须 fail closed |
| P2 / T05–T08 | 个人全文翻译闭环 | 扩展原任务与结果；关闭/重开/详情/上下文/朗读一致；GET 零新 Proxy 请求 |
| P3 / T09–T10 | 个人深度研究 | 复用 ResearchRun/事件/工具；本地用受控 Proxy；快照调用、工具 allowlist、服务端 continuation |
| P4 / T11–T13 | 推荐问题、用量和首批预设验证 | 首批六个产品预设逐项记录；首轮只有 DeepSeek 可以获批 PROVIDER_REAL，其他持续 NOT_RUN |
| P5 / T14 | 回归与发布 | 业务基线对比、迁移数据对账、故障不变量、账号切换、恢复/取消、T00-G 及明确范围的 provider/UAT 门禁 |

### T00 技术验真门槛

只使用临时本地 LiteLLM Proxy、受控 HTTP upstream、官方 SDK 和本次生成的合成假 Key。不得读现有 Key、借用全局环境凭据或访问真实 provider。

- 实际运行三协议的完整文本流与两轮工具调用；保存 raw upstream 与 Proxy/SDK 观察到的终态。
- 覆盖正常 EOF 但语义 incomplete、explicit length/incomplete、截断 body、超时、SSE 内错误、HTTP 错误、部分/无效/不在 allowlist 的工具参数及资源关闭。
- continuation 必须保留 Responses 原始 output items、Anthropic thinking/signature、Chat reasoning_content；对外可见消息不得带私密续接。
- 两组 provider Key/model 并发隔离；Proxy 项目 virtual key 与个人 provider Key 有不同用途；缺用户 Key 不借用部署 Key；错误项目 Key 在到达 upstream 前拒绝。
- SDK max_retries=0、Proxy num_retries=0、无 model fallback。代理 upstream request counter 证明失败时没有隐式重发。
- 精确检查 v1.104.2 streaming EOF 路径。单有 Proxy 的 stop/[DONE] 不能作为上游完整证据。若原始终态无法验证，按 T00 BLOCKED 记录，并只考虑该版本路径的局部修复、等上游修复或关闭具体路由的 streaming；不改成所有 SDK 的自写适配器，不降低终态要求。

### T00-G 共享服务运维验收门槛

T00-G 与业务代码独立交付，验证官方镜像签名/来源与 tag+digest、Proxy/Postgres 单机服务、项目级 virtual key 限制、master key 隔离、请求/并发预算、健康/配置检查、日志回调脱敏、密钥轮换、备份恢复演练、固定版本升级/回滚。单机规模，不引入 Kubernetes、多副本或新的业务任务框架。共享网关挂掉不影响新闻和旧历史阅读；BYOK 新调用清晰失败且不得直连 provider。T00-G 本身不证明 provider 兼容。

### 首轮真实 Provider 验收边界

PROVIDER_REAL 必须在独立 T13 子卡，由用户确认后从用户终端隐藏输入 Key；请求只经共享 Proxy 到官方通用 API。首轮只 DeepSeek；使用明确模型、合成短文本、关闭自动重试、设置明确请求数和输出 token 上限。其他五个预设保持 NOT_RUN；不能以 SDK_LOCAL、PROXY_LOCAL 或 LiteLLM 路由支持声明通过。运行前应提供推荐模型及最小请求预算给用户确认。

## 12. 本次实际验证证据

### 当前文档任务的事实

- 已通过 GitHub 连接器核对 `origin/feat/byok-user-api-keys` 精确 HEAD 为 `ea2ce55ae22e19e1604e88031b824b68f2666cec`，与用户提供值一致；本次文档更改在独立任务分支上。
- 此次只改 BYOK 设计/Task/Test/原型说明，不安装 SDK/Proxy、不创建或启动共享网关、不执行测试或 provider 请求、不读取任何真实 Key，不动 NewsHub 业务源码和线上环境。
- 所有新增 SDK_LOCAL、PROXY_LOCAL、T00-G、PROVIDER_REAL、UAT 证据都保持 NOT_RUN，具体见各 Test 占位表。

### 仅供历史回归参考的准备记录

较早的 T00 SDK 任务准备在隔离环境对旧业务测试记录过 219 passed、3 warnings；摘要记载的环境是 Python 3.14.8、Django 6.1、pytest 9.1.1，功能分支基线是 ea2ce55。由于当时报告/精确完整命令没有随当前文档任务带入，本次没有重跑，不能将其当作当前文档分支的变更后对照，也不能证明 Proxy/SDK/provider 验收。

更早设计记录还提到 17 passed / 1 xfailed 的隔离实验，内容包括局部序列化约束、SQLite 原型和复制的 LiteLLM helper 函数。它没有运行完整 LiteLLM Proxy 网络栈，也没有真实客户端 SDK 或真实 provider；这些局部实验只属历史设计调研，不能作为本架构的 SDK_LOCAL / PROXY_LOCAL / PROVIDER_REAL 通过证据。

### 尚未执行

本次文档更新的自动测试、业务源代码回归、真实 SDK 请求、锁定 Proxy E2E、共享 Proxy 服务部署/运维、厂商请求、用户 UAT 均 NOT_RUN。实施每张卡时须在对应 Test 中记录准确命令、执行时环境版本、基线与实现 SHA、脱敏日志、旧断言 diff 及其修改前后对照。没有这些证据不得标 PASS。

## 13. 参考资料

以下为本次读取的源代码和厂商一手文档；动态文档未来变化时以实际使用的版本和日期重新核对。

- [S1 仓库分支](https://api.github.com/repos/CoderLambert/news-aggregator/branches?per_page=100)
- [S2 LiteLLM v1.104.2 streaming_handler](https://github.com/BerriAI/litellm/blob/v1.104.2/litellm/litellm_core_utils/streaming_handler.py)；[发布元数据](https://github.com/BerriAI/litellm/releases/tag/v1.104.2)
- [S3 readiness模型定义](https://github.com/CoderLambert/news-aggregator/blob/b874405f31ae303e772d1ed6ef618b68938febed/backend/api/models.py)
- [S4 research job_manager](https://github.com/CoderLambert/news-aggregator/blob/b874405f31ae303e772d1ed6ef618b68938febed/backend/api/services/research/job_manager.py)
- [S5 subscription jobs](https://github.com/CoderLambert/news-aggregator/blob/b874405f31ae303e772d1ed6ef618b68938febed/backend/api/services/chatgpt_subscription_jobs.py)
- [S6 public policy](https://github.com/CoderLambert/news-aggregator/blob/b874405f31ae303e772d1ed6ef618b68938febed/backend/api/public_policy.py)
- [S7 subscription views](https://github.com/CoderLambert/news-aggregator/blob/b874405f31ae303e772d1ed6ef618b68938febed/backend/api/subscription_views.py)
- [S8 agent loop](https://github.com/CoderLambert/news-aggregator/blob/b874405f31ae303e772d1ed6ef618b68938febed/backend/api/services/research/agent_loop.py)
- [S9 serializers](https://github.com/CoderLambert/news-aggregator/blob/b874405f31ae303e772d1ed6ef618b68938febed/backend/api/serializers.py)；[TTS](https://github.com/CoderLambert/news-aggregator/blob/b874405f31ae303e772d1ed6ef618b68938febed/backend/api/services/tts_service.py)
- [S10 OpenAI流式Responses](https://developers.openai.com/api/docs/guides/streaming-responses)
- [S11 Anthropic流式Messages](https://platform.claude.com/docs/en/build-with-claude/streaming)
- [S12 OpenAI官方SDK](https://developers.openai.com/api/docs/libraries)
- [S13 百炼Base URL与套餐限制](https://help.aliyun.com/zh/model-studio/base-url)
- [S14 DeepSeek思考和工具续接](https://api-docs.deepseek.com/guides/thinking_mode/)
- [S15 GLM OpenAI兼容](https://docs.bigmodel.cn/cn/guide/develop/openai/introduction)；[Z.AI快速开始](https://docs.z.ai/guides/overview/quick-start)
- [S16 Kimi API概览](https://platform.kimi.ai/docs/api/overview)；[百炼OpenAI兼容](https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope)
- [S17 OpenAI迁移Responses](https://developers.openai.com/api/docs/guides/migrate-to-responses)

