# BYOK 功能开发任务（T00–T14）

**任务已拆分；全部 PLANNED，尚未实施或测试。** 一次只交给 Codex 一张卡；T13 分六个小任务，不能把整张总览作为大提示词发给 Codex。每张卡与 [同编号 Test 契约](../tests/README.md) 一对一。

基线：`feat/news-public-readiness@b874405f`；当前开发分支：`feat/byok-user-api-keys`。开始时必须读取**最新**分支 HEAD。

| Task | 单次可验收的产品功能 | 依赖 | 体量 | 状态 |
| --- | --- | --- | --- | --- |
| [T00 SDK 协议验真](T00-sdk-protocol.md) | 能用目标 Python 环境实际安装的 OpenAI/Anthropic SDK，经受控 HTTP 上游完整跑通 Responses、Chat Completions、Messages 的文本流和工具往返。 | 无 | S·技术门槛 | PLANNED |
| [T01 个人 Key 连接增删改停](T01-credentials.md) | 在正式 /settings/ai 页面新增自己的官方服务商 Key，查看掩码状态，更换、停用和删除连接，登录后的状态能够跨刷新恢复。 | [T00](T00-sdk-protocol.md) | M | PLANNED |
| [T02 录入模型并显式验证](T02-models-and-tests.md) | 用户对自己的连接添加多个模型，手工输入 ID 或选官方预置，主动点击测试文本/工具能力，得到可信的能力标记。 | [T01](T01-credentials.md) | M | PLANNED |
| [T03 用途默认模型设置](T03-preferences.md) | 用户为“默认、文章问答、全文翻译、深度研究、问题推荐”选择模型并点击保存；刷新和重新登录状态一致。 | [T02](T02-models-and-tests.md) | S-M | PLANNED |
| [T04 新闻问答 BYOK 闭环](T04-article-chat.md) | 用户在新闻详情助手选择自己的模型，提问后真实收到流式答案和模型来源，历史记录只属于当前用户。 | [T03](T03-preferences.md) | M | PLANNED |
| [T05 个人全文翻译最小闭环](T05-private-translation.md) | 对一篇安全长度内新闻原文使用个人 Key 翻译，看到进度和完整私有结果；重新打开通过 GET 找回同一任务及译文。 | [T04](T04-article-chat.md) | M（限定安全长度） | PLANNED |
| [T06 长文分块完整翻译](T06-long-translation.md) | 超过一次输出上下文预算的 Markdown 长文，也能安全分块、连续展示进度，并生成没有缺段的完整译文。 | [T05](T05-private-translation.md) | M | PLANNED |
| [T07 翻译取消与显式重新生成](T07-translation-lifecycle.md) | 关闭翻译进度只断开观看；用户可明确取消任务或主动重新生成，失败重试不会覆盖旧成功结果。 | [T05](T05-private-translation.md) | S-M | PLANNED |
| [T08 译文详情、问答与朗读同源](T08-translation-readers.md) | 个人译文生成后刷新页面仍可见，聊天上下文和中文朗读读同一份结果；换/删 Key 不删除历史。 | [T05](T05-private-translation.md)、[T07](T07-translation-lifecycle.md) | M | PLANNED |
| [T09 首次个人模型深度研究](T09-research-first-run.md) | 用户使用已验证工具能力的个人模型，创建研究会话、调用许可检索工具、收到步骤事件并保存完整研究报告。 | [T03](T03-preferences.md)、[T00](T00-sdk-protocol.md) | M | PLANNED |
| [T10 研究续问与安全恢复](T10-research-followup.md) | 已保存研究可续问，断开 SSE 后原会话只读恢复，不再发起新的收费研究；取消只作用准确运行。 | [T09](T09-research-first-run.md) | M | PLANNED |
| [T11 文章问题推荐与缓存](T11-suggestions.md) | 文章首次进入不收费；用户点“生成/换一批”才用自己的模型输出三条问题，并可从私有缓存恢复。 | [T04](T04-article-chat.md) | S-M | PLANNED |
| [T12 个人 AI 使用记录](T12-usage.md) | 用户可查看属于自己的模型调用次数、用途、已知/未知 Token 与模型；只读恢复不计入新调用。 | [T02](T02-models-and-tests.md)、[T04](T04-article-chat.md)、[T05](T05-private-translation.md)、[T09](T09-research-first-run.md)、[T11](T11-suggestions.md) | S-M | PLANNED |
| [T13 六家厂商真实兼容性关卡](T13-providers.md) | 按 OpenAI、Claude、DeepSeek、GLM、Qwen、Kimi 六个官方通用 API Key，逐厂商证明一个指定模型的真实文本/流/工具功能。 | [T00](T00-sdk-protocol.md)、[T02](T02-models-and-tests.md)、[T04](T04-article-chat.md)、[T09](T09-research-first-run.md) | 六个独立小验证 | PLANNED |
| [T14 公开部署与兼容性发布关卡](T14-release.md) | 部署可开关的 BYOK 功能；开关关闭后不再产生新收费请求但历史仍只读；既有 ChatGPT 订阅、新闻、TTS、研究无回归。 | [T04](T04-article-chat.md)、[T05](T05-private-translation.md)、[T06](T06-long-translation.md)、[T07](T07-translation-lifecycle.md)、[T08](T08-translation-readers.md)、[T09](T09-research-first-run.md)、[T10](T10-research-followup.md)、[T11](T11-suggestions.md)、[T12](T12-usage.md)、[T13](T13-providers.md) | M·发布门槛 | PLANNED |

## 关键拆分点

- T00 唯一技术验证：实际 SDK + 受控上游，**不开发页面或持久任务**。
- T01、T02、T03 依次交付“Key 连接”“模型验证”“用途偏好”，每个都有持久化 UI/API 可操作。
- T04 首条实际收费业务链闭环，先稳定文章问答。
- T05 仅在安全长度下交付**持久私有翻译完整链路**。T06 长文、T07 取消重试、T08 下游朗读/聊天与详情一致，分别可验收；不把它们全塞进 T05。
- T09 交付一次真实工具研究和保存；T10 再做续问、复连、取消和服务器 provider continuation。
- T11 推荐问题和缓存、T12 调用记录互相独立，不能暗中自动收费。
- T13 是验收关卡，**每次一个厂商**：[T13-A OpenAI](T13-a-provider.md)、[T13-B Claude / Anthropic](T13-b-provider.md)、[T13-C DeepSeek](T13-c-provider.md)、[T13-D GLM / Z.AI](T13-d-provider.md)、[T13-E Qwen / 百炼](T13-e-provider.md)、[T13-F Kimi / Moonshot](T13-f-provider.md)。
- T14 发布前全局门禁与回归，不代表已获准合并 main 或上线。

## 推荐推进顺序

```text
T00 → T01 → T02 → T03 → T04
                          ├→ T05 → T06
                          │        └→ T07 → T08（个人译文详情/朗读/上下文）
                          ├→ T09 → T10（研究续问与恢复）
                          └→ T11（问题推荐）
T02 开始各个调用共用 AICallAttempt → T12（用量视图）
T13-A..F（各家真实Key/模型独立验收）→ T14 发布前验收
```

先串行推进 **T00–T05** 并重点在 T00、T04、T05 进行纠偏；随后可调整任务顺序，但若同改持久任务/模型或入口，避免并行合并冲突。T09 是第四个重点技术纠偏节点。

## 每次给 Codex 的最小命令

> 请仅执行 `docs/features/byok/tasks/T00-sdk-protocol.md`（下一次换为当前 Txx 任务卡），同时读取相同 ID 的 `docs/features/byok/tests/Txx-*.md`，按 [执行规则](EXECUTION_RULES.md) 交付完整功能。先取最新 `origin/feat/byok-user-api-keys`、既有测试基线、实际 AGENTS。不要执行其它 Txx。完成后新建单任务 PR，base 指向功能分支，报告真实运行证据和未完成项。

## 状态规则

`PLANNED` 计划；`WORKING` 正在实现；`BLOCKED` 关键依赖缺失；`CHANGES_REQUESTED` 违反设计/缺证据；`PASS` 完整功能契约有实际证据；`MERGED` 审查后合并入 BYOK 功能分支。

每完成一个 PR 更新此表与同编号 Test 的真实测试结果及精确 HEAD；**不要**把单测数量当成验收结果。若当前任务规模失控，只沿完整用户操作切出新子卡和 Test，不把半成品交给下一张卡。

