# T04 · 新闻问答 BYOK 闭环

> **READY FOR REVIEW（2026-10-12）**：显式个人模型选择、Responses 流式新闻问答、完整终态后保存问答对、模型来源展示和失效/迟到结果保护已实现。SDK_LOCAL 与临时 Proxy 闭环已通过；并发双用户操作、真实 Provider 与人工 UAT 仍有未验证项，见 [Test T04](../tests/T04-article-chat.md)。

T04 实现提交：`4f47aacbb959ffdc79acf73c7d66795572799a39`；[PR #38 Draft](https://github.com/CoderLambert/news-aggregator/pull/38) 以 T03 提交 `68895c1e26660564ddc01d474caaef510770a22b` 为 base。父 PR [#37 Draft](https://github.com/CoderLambert/news-aggregator/pull/37) 尚未合并。

| 属性 | 内容 |
| --- | --- |
| 前置任务 | [T03](T03-preferences.md) |
| 推荐规模 | M |
| 对应测试 | [Test T04](../tests/T04-article-chat.md) |

## 本次交付的完整功能

用户在新闻详情助手选择自己的模型，提问后真实收到流式答案和模型来源，历史记录只属于当前用户。

**允许修改范围**：复用 NewsChatView、现有聊天 SSE 和会话持久化；按每轮显式 model_config_id 解析快照，由业务后端调用独立 Proxy、前端模型选择器、历史隔离与来源展示。业务测试可启动临时 LiteLLM Proxy 和受控 upstream；不依赖共享生产网关。生产配置缺 Proxy 时安全失败，不直连 provider。

**本次明确不做**：不重做聊天 UI 框架、不开发研究 Agent、不能隐式回落管理员/订阅 Key。

### 可直接复现的验收路径

A 对文章提问→流回答→关闭助手再打开读到历史→A 切模型仅影响下次提问；B 无 A 的任何记录。

### 对应 Test 用例

| Test ID | 可操作情境 | 必须观察到 | Test 文件 |
| --- | --- | --- | --- |
| T04-01 | 正文与问答经业务后端→临时 LiteLLM Proxy→受控 upstream 返回 | 显示模型来源，历史持久可读 | [Test 契约](../tests/T04-article-chat.md) |
| T04-02 | 半截流中断/无终态/Key失效 | 不保存为成功，不默默重试/回退 | [Test 契约](../tests/T04-article-chat.md) |
| T04-03 | A/B 并发同文问答及 A 退出后旧流迟到 | 各自模型、session和Query缓存互不覆盖 | [Test 契约](../tests/T04-article-chat.md) |
| T04-04 | 本次改模型与长期偏好 | 只改本次调用，不改变用途默认或既有任务 | [Test 契约](../tests/T04-article-chat.md) |
| T04-05 | 既有 ChatGPT 订阅问答/焦点键盘 | 兼容原行为，旧断言不迁就回归 | [Test 契约](../tests/T04-article-chat.md) |

当前证据：T04-01 与 T04-04 为 PASS；T04-02、T04-03、T04-05 为 PARTIAL。未验证范围和环境限制以同编号 Test 的记录为准。

### 立即停止并纠偏

SSE EOF 被算完成、其他用户输出进入当前会话或 fallback 被触发时停下。

### Codex 一次任务交付要求

1. 查看当前工作目录 AGENTS、分支和未提交改动；读取本卡和同编号 Test、技术方案/最新相关代码。
2. 同环境记录受影响旧测试的基线；用既有 Django/React/SSE/SDK/持久任务，先验证关键假设再编码。
3. 本次只交付这一项**可以运行的完整功能**，包括权限、正常操作与最主要的失败路径；不跨到其它 Txx。
4. 跑最小定向单元/契约测试以及受影响旧功能回归，列出修改过的测试断言 diff；需求未变时禁止改断言迁就代码。
5. 更新对应 Test 文档中的真实日志、环境、SHA 和 NOT_RUN 项；单张任务 PR 以精确 T03 依赖分支为 base，并注明父 PR #37 尚未合并。未授权时不合并、不开始下一张卡。

**任务结束**：这条用户流程能运行、失败能清楚识别，主要不变量有自动化验证；更新同名 Test 实际证据并留下单张可审核 PR。当前任何未验证的地方明确写 NOT_RUN。

