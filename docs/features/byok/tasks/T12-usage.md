# T12 · 个人 AI 使用记录

> **PLANNED**：本文件为未执行的实施/测试契约，所有测试当前 NOT_RUN。实施时以 `origin/feat/byok-user-api-keys` 最新 HEAD 为准，勿把设计 SHA 当作当前代码。

| 属性 | 内容 |
| --- | --- |
| 前置任务 | [T02](T02-models-and-tests.md)、[T04](T04-article-chat.md)、[T05](T05-private-translation.md)、[T09](T09-research-first-run.md)、[T11](T11-suggestions.md) |
| 推荐规模 | S-M |
| 对应测试 | [Test T12](../tests/T12-usage.md) |

## 本次交付的完整功能

用户可查看属于自己的模型调用次数、用途、已知/未知 Token 与模型；只读恢复不计入新调用。

**允许修改范围**：复用从 T02 开始的 AICallAttempt 网关账目，对测试/聊天/翻译/研究工具轮次/推荐做一致归类；新增 owner-scoped 只读 usage 接口和轻量使用记录 UI。

**本次明确不做**：不显示未经证明的厂商账户余额或费用，不补造历史消耗，不做计费中心。

### 可直接复现的验收路径

测试模型+问答各一次→显示两条 attempt→重新 GET 历史不增加→失败/断线标未知 usage。

### 对应 Test 用例

| Test ID | 可操作情境 | 必须观察到 | Test 文件 |
| --- | --- | --- | --- |
| T12-01 | 每次实际上游尝试对应一次记录，不按 SSE 用户订阅计数 | 含用户、用途、模型、时间、状态，无原文和密钥 | [Test 契约](../tests/T12-usage.md) |
| T12-02 | 上游 usage 缺失或请求结果未知 | 显示未知/NULL 而不是 0 | [Test 契约](../tests/T12-usage.md) |
| T12-03 | GET恢复/只读缓存反复执行 | 不会额外增加 attempt | [Test 契约](../tests/T12-usage.md) |
| T12-04 | B 读取 A 使用记录 | 严格拒绝 | [Test 契约](../tests/T12-usage.md) |
| T12-05 | 现有限流、取消、异常路径 | 不会因统计副作用重复调用 Provider | [Test 契约](../tests/T12-usage.md) |

### 立即停止并纠偏

出现 Key/新闻全文日志或用户跨账号查询成功时停止。

### Codex 一次任务交付要求

1. 查看当前工作目录 AGENTS、分支和未提交改动；读取本卡和同编号 Test、技术方案/最新相关代码。
2. 同环境记录受影响旧测试的基线；用既有 Django/React/SSE/SDK/持久任务，先验证关键假设再编码。
3. 本次只交付这一项**可以运行的完整功能**，包括权限、正常操作与最主要的失败路径；不跨到其它 Txx。
4. 跑最小定向单元/契约测试以及受影响旧功能回归，列出修改过的测试断言 diff；需求未变时禁止改断言迁就代码。
5. 更新对应 Test 文档中的真实日志、环境、SHA 和 NOT_RUN 项；单张任务 PR base 指向 `feat/byok-user-api-keys`。未授权时不合并 main、不开始下一张卡。

**任务结束**：这条用户流程能运行、失败能清楚识别，主要不变量有自动化验证；更新同名 Test 实际证据并留下单张可审核 PR。当前任何未验证的地方明确写 NOT_RUN。

