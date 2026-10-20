# NewsHub 统一模型接入审核与实施合同

日期：2026-10-21。源码基线：`a6cf437d45b66b962f35e4427ad8c05c589e990a`。
输入：用户下载的 `NewsHub-Unified-AI-Access-V1-Design-Draft.md`（253 行）及审核、执行提示词；附件 `pasted-text-1.txt`。
状态：审核修订；实施与验收按下列矩阵分别记录，不以设计存在证明功能完成。
授权：用户明确要求审核完善后自动开发；阶段人工停顿由这一直接指令覆盖。允许本地开发、隔离合成测试和用户指定 Ollama 测试；不包含生产、自动合并或其他真实收费供应商调用。测试 Key 不入 Git、日志或文档。

## 目标与范围

保留 `UserAIConnection`、AES-GCM 原 AAD、epoch/version、T02 证明、T03 用途、T01 Worker 和 LiteLLM。通过同一连接→模型→用途路径接入官方 API、OpenRouter、硅基流动、Ollama、LM Studio、vLLM 和管理员兼容端点，完成真实业务问答、全文翻译。不能仅增加选项或通过 Mock 测试便称完成。

保留 DeepSeek 现有行为及 ChatGPT Subscription 独立路径；研究、建议和分类按其独立能力合同启用。工具文本通过不代表研究工具回放通过。所有失败保持所选模型，不换收费服务，不重试发送状态不明的请求。

## 审核结论与替代方案

采用“现有 BYOK + 服务端版本化端点目录 + 协议适配 + 原始完成证据”。

| 路线 | 安全、兼容与维护代价 | 结论 |
| --- | --- | --- |
| 每个业务实现供应商分支 | 重复鉴权、取消和终态处理；增加一个服务要改多个业务 | 不采用 |
| 扩展现有 BYOK/LiteLLM | 沿用 owner/epoch；集中管理可信端点、能力与终态；须验证固定版本内部机制 | 采用 |
| 新建通用网关 | 多套凭据与 HTTP 出站边界，迁移与回归面最大 | 不采用 |

不把其他 Chat 路由简单加入 DeepSeek 白名单。先贯通端点和无 Key 身份，再证明协议完成；无法证明流式的协议可明确显示 buffered，但最终接入目标不缩小为只能保存配置。

## 当前源码证据与影响边界

| 合同 | 当前文件与事实 | 改动职责 |
| --- | --- | --- |
| T01 | `ai_connection_models.py` 没有 auth_mode；`ai_credentials.py:require_active_snapshot` 必须解密 | 加法迁移，显式无凭据类型，保留旧 AAD |
| T02 | `ai_model_registry.py` 除 OpenRouter 外仅 bare ID；`ai_model_probe.py` 要求非空 Key | 兼容命名空间及标签；同一可信路由；版本绑定证明 |
| T03 | `ai_task_preferences.py:_selected_state` 以密文是否存在判断可用 | 用认证模式及实际 profile 授权判断 |
| T04 | `ai_article_chat.py` 在准备、执行两处限制 DeepSeek Flash | 使用经过证明的路由/协议合同 |
| T05 | `ai_private_translation.py` 快照、排队、claim 多处检查同一常量 | 同 T04，保持内容版本、lease/generation 与 commit fence |
| 网关 | `ai_gateway.py:_GatewayCompletions` 仅 Flash streaming；原生 Responses/Messages 已有 adapter | 显式受信协议，不从用户 model ID 猜协议 |
| Proxy | `provider_key_guard.py` 固定 LiteLLM 1.105.0；原始解析器/Router provenance | 保留 DeepSeek，逐协议证明后扩展；所有请求拒绝 URL/header/fallback 覆盖 |
| T07/T08 | `research/byok_execution.py`、`channel_ai.py`、`channel_model.py`、`ai_suggestions.py` | 检查快照序列化、无凭据传递、工具回放与原结构化约束 |
| T12 | `ai_usage.py` 与 usage 适配 | 保留 owner、未知 token/费用；增加协议/终态可追溯字段 |
| 前端 | `aiConnectionsApi.ts`、`AIModelSettingsPage.tsx`、`AIModelsManager.tsx`、用途选择器 | Key/none、来源说明、模型/能力诊断、失败原因及安全 DTO |

现有 DeepSeek raw stop + clean EOF 语义与新 Chat 原始 `[DONE]` 要求分别测试，不悄悄改变历史合同。

## 受信端点与路由

管理员维护 JSON manifest，后端和 Proxy 使用同一纯 Python 校验模块及同一配置副本。普通 API 不接受 Base URL、Headers、协议覆盖或网络参数。默认不发布任何无 Key/内网端点。

每项包含固定 `profile_id`、正整数 `version`、`provider_id`/服务预设、显示名、`protocol_family`、`api_base`、`auth_modes`、明确出站域/IP/端口策略及访问用户范围。私网/无 Key 必须显式列出允许用户；所有连接 admission、claim、dispatch、commit 重新验证准入。不向未授权用户显示私网配置或地址。

新 profile 的 route prefix 由 profile/version/规范化内容摘要产生。摘要包含目的地、auth、协议、准入和校验器版本；修改同版配置仍导致新 prefix，旧 model receipt/TaskModelSnapshot.alias 不匹配而失效。Proxy 静态生成配置，禁止用户触发动态注册。两端配置不一致只能失败，不能将旧 Key 发往新地址。发布需离线验证、受控重启，不由连接保存触发。

上游模型 ID 作为不透明数据。允许 provider/model、model:tag、点、短横线、下划线、@；拒绝 URL、编码转义、控制字符、空白、路径逃逸、双斜线、query/fragment，以及将路由前缀伪装成模型选择。兼容端点 wildcard 的目的地与协议固定，suffix 仅作为模型名传上游。旧 OpenAI/Anthropic 原生协议保持现有选择。

出站保护必须位于实际连接层：核对目标 host、解析后数值 IP、端口和地址策略，固定 DNS 解析结果用于 connect，禁止重定向、代理环境继承和未经授权的 loopback、metadata、私网、IPv4-mapped/其他编码绕过。不能仅依赖表单校验。不得默许原有公网 wildcard 透传 api_base。

## 认证、幂等与持久化

新增 `UserAIConnection.auth_mode = api_key | none`，旧行默认 api_key；不重写密文，旧 AAD 字节不变。新 manifest 连接另存不可变 `endpoint_policy_digest`，仅新连接使用 v3 AAD 域绑定该摘要和认证模式，防止同版目标改变后旧 Key 被继承。
none 只对 manifest 已批准 auth mode 且用户有权限的端点有效，密文与 encryption_key_id 必须为空。`decrypt_credential` 继续严格拒绝无密文，另一个统一 admission 函数返回 `None` 表达已授权无凭据；不得返回空字符串或保存假 Key。

ConnectionSnapshot 增加有默认值的 auth_mode，旧持久化快照只按原 api_key 解码；unknown/malformed auth mode 拒绝。enqueue/claim/dispatch/commit 比较模式、endpoint、epoch/version。none→api_key 不通过更换 Key 隐式转换，必须新建连接。停用/重启/删除同样递增 epoch；模型 evidence 及所有结果提交保留原围栏。

api_key 模式的 `creation_digest` 保持旧字节形式，以免旧 request_id 重放变成冲突；none 增加独立 digest 域及模式。不同模式重用 request_id 返回冲突。对 none 的 Key replacement 拒绝且不改变 epoch。

## 完成、能力与消费

探针及业务使用相同 route/protocol。能力证明绑定 owner、connection、auth/epoch/version、profile/version、route alias、model/revision 和 adapter 版本；实际成功 attempt 必须存在。unknown 不转成 supported。

非流式响应核对原始 JSON 完成原因及 normalized 原因一致。Chat 新流适配要求原始 JSON stop、原始终止帧、正确 provenance、无 error/length/filter、不重复 terminal，只有经过校验后释放终态。Responses 要求 completed 的原生终态；Messages 要求 message_stop 和有效 stop_reason。工具调用不能作为最终文本 stop。

buffered 输出明确标示 delivery_mode=buffered；不得用 `[DONE]` 或 EOF 伪造成功。部分文字可显示但不得保存 completed，取消/撤销后即使上游已返回也不能 commit。保留输出上限、连接超时、总预算、分段数与单次 dispatch。

OpenRouter 请求显式关闭 provider fallback，披露上游供应商可能未知；不承诺固定推理厂商。Ollama local endpoint 可代理云模型，因此 UI 不承诺离线；LM Studio 支持 Key/none，依管理员发布。GET 设置/目录无推理，模型发现必须显式操作且有数量/超时上限；发现失败保留手工 ID。

## 实施批次及验收

| 阶段 | 交付 | 主要负面用例 | 完成证据 |
| --- | --- | --- | --- |
| G0 | 独立审核、修订合同、逐任务计划 | 原始 EOF 与 normalized stop；出站覆盖；none 伪造 | 源码+隔离 Proxy 探针，分级记录 |
| G1 | 受信 manifest、认证模式、迁移与 T01/T02/T03 | 旧 AAD/幂等兼容、模式替换、owner/epoch/端点变更 | 集成 API/DB/快照与实际 Proxy |
| G2 | 云/兼容路由、原始终态、业务问答翻译 | 断流/error/length/重复终态、取消、真实 send 次数 | 合成上游→真实 Proxy→Django→结果 |
| G3 | UI、模型发现、诊断、usage | 默认不推理、Key 不入缓存、权限退出、手机布局 | TS/lint/测试/build 与浏览器 |
| G4 | 工具回放/研究/分类、指定 Ollama、整体验收 | 未验证 tools、输入恶意、无隐式切换、版本撤销 | 合成回归+授权真实服务分别记录 |

功能要求 F01 DeepSeek 回归；F02 OpenAI/百炼切换；F03 OpenRouter/硅基命名空间；F04 Ollama/LM Studio Key/none；F05 vLLM；F06 同文章问答翻译不同模型；F07 tools 研究门禁；F08 手工 ID；F09 设置无推理。安全要求 S01 连接层 SSRF；S02 管理员发布；S03 参数覆盖拒绝；S04 owner 隔离；S05 版本撤销；S06 AAD/迁移兼容；S07 none 不能升级权限；S08 日志/cache 无密钥。终态要求 R01 完整；R02 EOF；R03 error；R04 超限；R05 cancel；R06 late commit fence；R07 不重试；R08 billing unknown。

所有要求最终须逐条对应文件、命令与保留结果。当前源码结论均 SOURCE_ONLY；运行前不得标 PROVEN。真实 OpenAI/百炼/OpenRouter/硅基/LM Studio/vLLM 及生产/UAT 未运行均写 NOT_RUN；用户指定 Ollama 单独验收。最终 CI 按实际 SHA，全量门禁与 Draft 快检区分，不自动合并/部署。

## 上游核对

- Ollama OpenAI subset、local ignored Key/cloud distinction：<https://docs.ollama.com/api/openai-compatibility>（2026-10-21 读取）。
- LM Studio optional authentication：<https://lmstudio.ai/docs/developer/core/authentication>（2026-10-21 读取）。
- OpenRouter provider routing：<https://openrouter.ai/docs/guides/routing/provider-selection>（2026-10-21 读取）。
- vLLM serving：<https://docs.vllm.ai/en/latest/serving/openai_compatible_server/>。

回滚：新路由先停用/撤销且不重试未知派发；旧功能保持。代码回退不能替代 DB schema 回滚，auth_mode 加法列保留。部署仅生成配置与说明，不触碰真实服务。
