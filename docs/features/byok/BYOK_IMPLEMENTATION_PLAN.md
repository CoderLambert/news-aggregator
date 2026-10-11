# 新闻资讯项目 BYOK：确定实施方案与验证记录

版本：1.0 · 2026-10-11  
适用仓库：CoderLambert/news-aggregator  
交付性质：开发设计基线；本功能分支仅收录方案及静态原型，尚未修改业务实现，也没有调用真实厂商收费接口。

## 0. 决策摘要

采用 **OpenAI 官方 Python SDK + Anthropic 官方 Python SDK + 三个薄协议适配器**。在当前 Django 后端内实现，不另建项目、不部署网关、不更换研究 Agent 框架、不新增第二套任务系统。

三种协议：`openai_responses`、`openai_chat`、`anthropic_messages`。首批产品支持范围是 OpenAI、Claude、GLM、DeepSeek、Qwen、Kimi 的通用开放平台 API Key；具体「厂商 × 模型 × 参数模式 × 功能」只有通过真实联调才标记为已验证。

**修正上一版两项决定：**

1. 首版不采用 LiteLLM 为核心执行依赖。核查 v1.104.2 源码发现：流结束且没有收到结束原因时，统一流封装可以生成 `finish_reason="stop"`。仅依赖这个标准化字段不能证明上游完整完成。为六家厂商额外耦合其内部状态，不如使用官方 SDK 的原始协议事件。此结论不是“所有 LiteLLM 网络错误都会假成功”，也不代表否定其更大规模网关场景。[S2]
2. 不新增并行的 `UserTranslationTask`。部署准备分支已经有 `ChatGPTTranslationTask`，扩展它的凭据变体，复用同一租约、取消、提交和持久化机制。[S3]

本方案确定架构、行为和实施边界；实际 SDK 安装兼容性、六家真实模型调用、仓库基线回归以及公网部署尚未得到运行时证明。开发第一项工作是第 11 节的有界验证切片，而不是重新讨论技术栈。

## 1. 代码基线与事实

本次查询得到：

| 版本 | 精确 SHA | 使用方式 |
| --- | --- | --- |
| main | `8c2823e1fcf8cbea38e9bb7c4e98a33232025fbd` | 对照已合并功能 |
| feat/news-public-readiness | `b874405f31ae303e772d1ed6ef618b68938febed` | 本方案的增量设计基线 |

建议开发分支从已经核实的 readiness 基线创建；执行当天重新核对 HEAD、未合并修复和测试基线。不得把该分支称为已经部署或发布验收通过。此次读取该版本仓库根目录 `AGENTS.md` 返回 404；执行者仍须检查实际工作目录中的上级及子目录指导文件。[S1]

### 已存在，应直接复用

- ResearchRun / ResearchRunEvent：用户隔离、幂等键、每个会话唯一活动任务、事件序号、租约、提交 CAS、显式排队恢复、只读 GET 重放。[S4]
- ChatGPTTranslationTask：持久任务、generation、provider_started、进度、最终结果、租约和取消。[S3]
- 共享的受限后台线程执行器、现有前端 Query 缓存与 SSE 工具。[S5]
- 现有 Session 认证、CSRF、用户聊天写入约束、公共模式开关、译文共享机制。公共机制保留，但新 BYOK 不自动参与公共发布。[S6][S7]

### 已确认需要改的接入边界

| 位置 | 已观察事实 | 定向修改 |
| --- | --- | --- |
| `research/agent_loop.py` | 从全局 get_clients 获取客户端，消息序列化丢弃 reasoning_content | 注入用户执行快照；由适配器保留续接状态 |
| `public_policy.py` + research/job_manager | production 条件直接拦截研究 | 保留站点总开关；凭据策略在认证和服务端解析后判断，并覆盖 Worker |
| `chatgpt_subscription_jobs.py` | translation 任务是订阅专用外键；read handle 的 wait_for_update 可派发 queued 工作 | 扩展凭据变体；新只读恢复不能复用带派发副作用的方法 |
| `subscription_views.py` / 订阅保存路径 | 私有翻译与公共共享发布相连 | BYOK 私有提交分支不得调用 publish_translation |
| `serializers.py`、`tts_service.py`、聊天上下文 | 个人译文读取主要识别活动订阅连接 | 共用个人结果解析入口；读取历史不要求 Key 仍有效 |

这里的兼容性缺口来自源码和隔离函数实验；不能写成已经复现六家厂商的线上失败。[S5–S9]

## 2. 产品范围

### 本期完成

- 登录用户添加多个服务连接；同厂商可配置不同账户。
- 每个连接添加多个模型配置；支持版本化预置目录和手动模型 ID。
- 一个默认模型，文章问答、全文翻译、推荐问题、深度研究可单独覆盖。
- 保存、模型发现、测试模型三个独立动作；测试需要明确点击，显示可能计费。
- 已保存／凭据启用状态／最近测试结果分别建模；保存成功不意味着可调用，测试失败不抹掉已保存配置。
- 各功能显示实际使用的服务商、模型与结果来源。
- 个人结果默认私有，跨设备按网站用户恢复；浏览器不保存 Key。
- 更换或删除 Key、停用连接；已有个人结果继续可读。

### 本期不做

独立模型代理服务、模型市场、自动跨厂商回退、Coding/Token Plan、订阅登录能力重构、任意用户 Base URL、浏览器直连厂商、Embedding 模型切换、新搜索工具框架、完整计费中心。

不改变已有公共译文和订阅连接的历史行为；BYOK 与旧路径通过明确的凭据类型分流。其他兼容服务后续增加可信预设及契约测试；不能仅添加一个厂商名字就声称该厂商所有模型都支持。

## 3. 厂商与 SDK 方案

| 厂商 | 首版协议 / SDK | 端点配置 |
| --- | --- | --- |
| OpenAI | Responses / openai | 官方端点；使用 store=false，按原始 Responses 状态判断完成 |
| Claude | Messages / anthropic | 官方端点；保留原始内容块、工具块和必要签名 |
| DeepSeek | Chat Completions / openai | 官方通用端点；思考模式需要保留 reasoning_content |
| GLM | Chat Completions / openai | 智谱国内与 Z.AI 分别提供官方预设 |
| Qwen | Chat Completions / openai | 百炼地域和共享／业务空间端点分别配置 |
| Kimi | Chat Completions / openai | Moonshot 国内与国际站分别配置 |

OpenAI、Anthropic 有官方 Python SDK。DeepSeek、智谱/Z.AI、百炼、Kimi 官方文档提供 OpenAI SDK 兼容接入；所以不需要六个 SDK，也不需要自行实现 HTTP/SSE 解码器。[S10–S16]

端点是后端可信配置，不接受前端任意完整 URL。验证过的典型通用地址：

```text
OpenAI       https://api.openai.com/v1
Anthropic    https://api.anthropic.com
DeepSeek     https://api.deepseek.com
GLM CN       https://open.bigmodel.cn/api/paas/v4/
Z.AI         https://api.z.ai/api/paas/v4/
Qwen 北京    https://dashscope.aliyuncs.com/compatible-mode/v1
Qwen 新加坡  https://dashscope-intl.aliyuncs.com/compatible-mode/v1
Kimi 国际    https://api.moonshot.ai/v1
```

端点注册表可以保留其他已核实官方区域预设。Qwen WorkspaceId 作为受限字段输入，后端从固定域名模板生成地址；不允许字段包含点、斜杠、端口或 URL 语法。端点/地域变更创建新连接，不能把已保存 Key 自动转发至另一个地址。

**套餐边界：**百炼官方明确 Coding Plan、Token Plan 仅限交互式 AI 工具，不能用于后端服务。该新闻网站预设只接通用按量 API，不把现有 Coding 环境变量移植到网站用户路径。其余套餐同样不能依据“HTTP 能调通”推断用途授权。[S13]

### 模型与参数

- 目录是版本化数据，不将某一代模型 ID 散落在业务代码。
- 列表发现是可选能力；某厂商不支持列表 API，仍可用目录或手填 ID，不能使配置流程卡住。
- 测试结果绑定 connection credential_epoch + model config revision + endpoint profile revision；过期测试不能覆盖新配置状态。
- `text`、`tools`、`structured_output`、`thinking`、`streaming`、上下文与输出预算独立标记。只有需要的能力不足时禁用对应功能。
- 未知模型可以保存。完成测试前标为未验证；没有可信上下文限制时，不自动把整篇长文发送给它，应要求有效的模型限制资料或采取保守输入限制。
- 模型参数采用厂商/模型白名单，不能透传 arbitrary extra_body、headers、base_url、callback。必要的厂商扩展由适配器构造。

## 4. 模块和协议契约

```text
React AI 设置 / 现有功能入口
  -> Django Session + CSRF + 用户权限
  -> 解析本次操作并冻结 ExecutionSnapshot
  -> 现有任务 / 研究循环 / 聊天写入边界
  -> AI Gateway（应用授权、预算、日志脱敏）
  -> OpenAI Responses | OpenAI Chat | Anthropic Messages
  -> 官方 SDK
  -> 用户所选厂商

原始模型终态 -> 业务校验 -> 事务提交结果与任务终态 -> complete 事件

GET 历史 / GET 重放 -> 用户隔离的持久记录；无 SDK / executor / createTask 依赖
```

建议新模块：

| 模块 | 职责 |
| --- | --- |
| `services/ai/registry.py` | 官方端点、模型配置和能力白名单 |
| `services/ai/credentials.py` | 应用内密钥封装、用户归属、凭据版本与生命周期 |
| `services/ai/contracts.py` | ExecutionSnapshot、ModelTurn、ModelEvent、ProviderError |
| `services/ai/routing.py` | 默认/功能选模；读取既有幂等记录；冻结非秘密配置 |
| `services/ai/gateway.py` | 调用许可、请求实例、超时、用量与安全错误 |
| `services/ai/adapters/openai_responses.py` | 原始 Responses 输入输出、工具续接 |
| `services/ai/adapters/openai_chat.py` | Chat 兼容协议 + 少量厂商字段策略 |
| `services/ai/adapters/anthropic_messages.py` | 原始 Messages 内容块、工具结果、终态 |
| `services/article_translations.py` | 同一用户结果身份下的详情、聊天、朗读解析 |

现有研究、翻译调度仍在原模块，不搬迁成通用 workflow 框架。旧订阅函数保留包装入口；内部执行按 credential_kind 选择受限适配器。

核心接口（签名契约，非已实现代码）：

```python
resolve_execution(user, task_kind, model_config_id=None) -> ExecutionSnapshot
complete_turn(execution, conversation, tools, guard) -> ModelTurn
stream_turn(execution, conversation, guard) -> Iterator[ModelEvent]
read_task(user, task_id) -> TaskView
read_article_translation(user, article_id, artifact_id=None) -> TranslationView
```

`ModelTurn` 至少包含 `text`、`tool_calls`、`finish`、`usage`、服务端专用 `continuation`。不让 UI 或恢复模块看到可以调用 Provider 的对象。

### 续接状态与可见消息分离

DeepSeek 思考模式工具调用必须回传 reasoning_content；Anthropic 可能需要保留 thinking block/signature；Responses 需要正确回传输出 items / 工具结果。现有“只保留 content 和 tool_calls”不足以承担这三种协议。[S8][S11][S14][S17]

在现有会话持久化记录中增加带版本和协议标签的 provider_state，服务器续接使用它；公开 API 返回经过白名单投影的可见 messages。续接字段不能作为 URL、Key、工具白名单或执行权限的来源。

研究会话首版固定 provider+model+协议配置；更换研究模型新建研究会话，可显式复制可见研究结论，不自动移植另一个厂商的原始续接状态。文章普通问答可在下一次提问切换模型，并仅带入允许共享的可见历史。运行中的任务均不变更快照。

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

## 7. 密钥与公共部署安全

- 采用现有 cryptography 库的 AEAD，独立稳定应用加密密钥；AAD 绑定 owner、connection_id、provider/endpoint profile、credential_epoch、格式版本。保留旧订阅密文格式，不能无意改变其 HKDF/AAD 导致旧令牌无法解密。
- 应用加密主密钥置于部署 Secret，不进入数据库、仓库或日志；提供 key_id、轮换和备份恢复说明。缺密钥时失败关闭，不回退明文存储。
- 查询接口只有 has_key、末四位、启用状态；Key 写入接口单向写入。禁止 Key 进入 localStorage、Query持久化、URL、分析埋点和错误回执。
- 后端按调用创建显式 api_key/base_url 的 SDK 客户端；不通过每用户修改环境变量或进程全局客户端切换 Key。关闭跨站重定向，保持 TLS 验证。
- 用户不能编辑任意 Base URL。管理员注册新端点也需要明确的新连接/凭据授权，不能重新解释已有端点 ID 并把旧 Key 转发过去。
- 官方域名白名单不是完整 SSRF 防护：服务出站网络应阻断私网/云元数据网段；DNS、重定向、代理环境和域名归属均需在目标部署验证。
- middleware 保留全站只读/AI开关；credential-specific policy 在认证后解析真实拥有的连接，不信任请求中的 `credential_kind` 标签。提交、恢复、Worker和每次模型调用共用同一策略。
- 所有未配置/失败的 BYOK 用户路径不能落入站点环境 Key。原有管理员批处理需要在单独明确的 operator context 下运行。
- 页面注明：Key 会由本站服务器加密托管，管理员控制的运行环境仍可解密；这不是零知识保管。新闻正文/问题将发送给所选厂商。搜索抓取/TTS是独立的数据接收方，不能宣称所有处理都只流向所选 LLM。

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
| POST /api/ai/connections/{id}/test/ | 固定合成输入的有界模型测试；注明可能计费 |
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

沿用已有执行器和限流。当前进程内并发限制不是跨进程全局限额；首版保持既有单执行器部署形态，不同时引入水平扩容。新接口纳入已有鉴权/限流和资源预算测试；未来多Worker须另行验证跨进程容量约束。

迁移顺序：

1. 同环境记录不改动测试的基线、依赖版本、现有失败与选定Git SHA。
2. 增量建配置表并扩展任务/结果字段；旧行默认subscription；先在数据库副本运行迁移与回滚检查。
3. 调整现有任务执行的凭据适配边界，旧接口响应和行为保持兼容。
4. 增加BYOK私有结果读取、统一详情/聊天/TTS解析；历史读取不需要有效Key。
5. 前端在服务端能力旗标开启后显示配置入口；AI_BYOK_ENABLED默认关闭，先局部测试再开放。
6. 回退优先关闭新生成旗标，保留已生成私有内容可读。新数据产生后不得执行会丢掉BYOK字段的盲目降级迁移。

## 11. 确定的实施任务和结束条件

> **任务拆分更新（2026-10-11）：** P0–P5 是阶段路线，不是一个 Codex 实现任务。实际按 [tasks/README.md](tasks/README.md) 的 T00–T14 单张功能卡交付，每张配套 [tests/README.md](tests/README.md) 的 Test 契约。T00 不再包含连接管理/持久化/GET 恢复的实现，分别在后续业务功能切片完成。

| ID | 工作 | 依赖/完成标准 |
| --- | --- | --- |
| P0 | 官方SDK最小协议切片 | 目标Python环境安装并锁定两个SDK/依赖；3种协议的实际SDK测试、原始终态、两轮工具续接、显式Key隔离成立 |
| P1 | 个人连接/模型/快照与一次文章问答 | 真实Session+CSRF入口，两个用户不同Key不会串用；模型测试、默认选择、站点不兜底；保留旧问答行为 |
| P2 | 个人全文翻译闭环 | 扩展原任务与结果表；完成一次生成、持久化、关闭、重开、详情/上下文/朗读一致；GET零新调用 |
| P3 | 个人深度研究 | 复用ResearchRun/事件/工具；按快照调用；生产凭据策略正确，工具续接不丢失、不能执行非允许工具 |
| P4 | 推荐问题/用量/其余厂商与配置体验 | 六家通用Key预设逐项接入；缓存/测试状态/参数能力可信；缺少真实证据的模型不标记已验收 |
| P5 | 回归与交付 | 基线对比、迁移数据对账、故障不变量、账号切换、恢复与取消验证，提供精确SHA和证据 |

### P0 不是再次大规模调研

只在真实项目环境实现薄适配器与一个最小调用脚本，不先完成设置页或全部业务改造。

- 使用真实SDK连接可控的本地测试上游（或当前SDK匹配的注入传输层），验证实际请求headers/URL/body与响应解析；不能用只替换gateway返回值的mock冒充SDK兼容。
- 3种协议各验证：正常完成、只返回partial后EOF、明确length/incomplete、HTTP错误、流内错误、工具调用→结果→最终回答、资源关闭、无隐式重试。
- DeepSeek重点验证开启思考时的reasoning_content续接；Claude验证原始内容块/签名；OpenAI验证Responses工具items。Kimi/GLM/Qwen按所选真实模型参数验证，不能从通用兼容性推导全部特殊能力。
- 获得本地测试Key后，每家至少一个指定模型完成文字生成/流式以及研究所需工具往返，结果绑定具体模型/日期。Key只通过本地环境或配置输入，不发送聊天、测试日志、GitHub或Slack。
- 任一适配器尚未证明原始终态/续接，就不扩散到所有功能。不需要某一家真实Key才能编写其余共用功能，但不能声称该家完成验收。
- 当前不能确定可运行的包版本组合；P0负责记录可安装且通过契约的精确lock/hash。这是依赖兼容实测，不授权顺带升级所有项目依赖或更换架构。

### 测试修改规则

同环境对比变更前后。旧测试基线通过、新分支失败而产品行为未变：修实现。需求明确改了语义：先在契约中写明差异再改对应断言；证明无关行为未改变。两边均失败：记录既有问题/环境/不稳定性，单独处理，不伪装新增回归，也不自动忽略其发布风险。

## 12. 本次实际验证证据

### 已执行

1. 通过GitHub连接器读取精确分支、现有模型、研究任务/循环、翻译任务、公共策略和接口。
2. 对复制出的原始消息序列化函数执行相同续接断言：明确失败，reasoning_content为None。`baseline_failure.txt`保留退出码1对应输出；没有修改仓库原测试。
3. 对LiteLLM指定版本复制出的finish_reason_handler进行隔离执行：缺失两个终态字段时产生stop；已知length保持length。仅复现该函数行为，没有运行LiteLLM完整网络栈。
4. 用真实SQLite事务、唯一/CHECK约束和AES-GCM、合成凭据验证设计原型：并发提交/claim、owner隔离、AAD绑定、只读重放、数据库重开读取、撤销、旧提交fencing、终态门槛、事务回滚、事件唯一性。

验证目录最新输出：`17 passed, 1 xfailed`。其中15项是候选约束/序列化原型，2项是LiteLLM隔离方法反例，1项是明确标识的原始序列化反例。单独运行原始反例使用 `--runxfail` 得到 `1 failed`，防止将预期失败误报为旧实现已经满足契约。

### 没有执行

官方SDK安装/运行、六家真实模型调用、完整仓库基线/回归、浏览器真实交互、Django迁移、部署与多进程故障恢复。

当前容器外网DNS不可达，且未安装Django/openai/anthropic/LiteLLM；未提供或读取真实厂商Key。所有实验Key和Provider输出都是合成夹具。SQLite原型证明的是局部约束可行，不等同于当前Django系统已经拥有这些保证。原型文件不能直接作为生产实现复制。

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

