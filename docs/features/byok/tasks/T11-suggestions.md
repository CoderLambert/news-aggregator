# T11 · 文章问题推荐与缓存

> **PLANNED**：本文件为未执行的实施/测试契约，所有测试当前 NOT_RUN。实施时以 `origin/feat/byok-user-api-keys` 最新 HEAD 为准，勿把设计 SHA 当作当前代码。

| 属性 | 内容 |
| --- | --- |
| 前置任务 | [T04](T04-article-chat.md) |
| 推荐规模 | S-M |
| 对应测试 | [Test T11](../tests/T11-suggestions.md) |

## 本次交付的完整功能

文章首次进入不收费；用户点“生成/换一批”才用自己的模型输出三条问题，并可从私有缓存恢复。

**允许修改范围**：复用 NewsSuggestedQuestionsView 和当前助手 UI；新增 owner/news/source_hash/execution_digest/prompt_version 私有缓存；显式 POST 生成、GET 读取缓存和输出校验。

**本次明确不做**：不在列表或详情加载自动调用个人 Key；格式错不能把免费模板冒充 AI 成功。

### 可直接复现的验收路径

打开文章无调用→点击生成→得到三条→刷新无调用→切模型重新生成并显示新来源。

### 对应 Test 用例

| Test ID | 可操作情境 | 必须观察到 | Test 文件 |
| --- | --- | --- | --- |
| T11-01 | 明确点击生成得三个有效问题并缓存 | 可以展示模型来源，刷新只读 | [Test 契约](../tests/T11-suggestions.md) |
| T11-02 | 首次进入页面或只读缓存/模板 | Provider 调用数 0 | [Test 契约](../tests/T11-suggestions.md) |
| T11-03 | 另一用户、来源 hash 变化或更换模型 | 不返回无关旧问题 | [Test 契约](../tests/T11-suggestions.md) |
| T11-04 | 空结果/格式错/网络失败 | 标明失败，固定免费模板仍可用 | [Test 契约](../tests/T11-suggestions.md) |
| T11-05 | 现有推荐问题/文章助手 | 保持原有 API 兼容 | [Test 契约](../tests/T11-suggestions.md) |

### 立即停止并纠偏

页面 GET 导致收费、问题缓存串用户或与原文失配，停止。

### Codex 一次任务交付要求

1. 查看当前工作目录 AGENTS、分支和未提交改动；读取本卡和同编号 Test、技术方案/最新相关代码。
2. 同环境记录受影响旧测试的基线；用既有 Django/React/SSE/SDK/持久任务，先验证关键假设再编码。
3. 本次只交付这一项**可以运行的完整功能**，包括权限、正常操作与最主要的失败路径；不跨到其它 Txx。
4. 跑最小定向单元/契约测试以及受影响旧功能回归，列出修改过的测试断言 diff；需求未变时禁止改断言迁就代码。
5. 更新对应 Test 文档中的真实日志、环境、SHA 和 NOT_RUN 项；单张任务 PR base 指向 `feat/byok-user-api-keys`。未授权时不合并 main、不开始下一张卡。

**任务结束**：这条用户流程能运行、失败能清楚识别，主要不变量有自动化验证；更新同名 Test 实际证据并留下单张可审核 PR。当前任何未验证的地方明确写 NOT_RUN。

