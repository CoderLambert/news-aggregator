# T07 · 翻译取消与显式重新生成

> **PLANNED**：本文件为未执行的实施/测试契约，所有测试当前 NOT_RUN。实施时以 `origin/feat/byok-user-api-keys` 最新 HEAD 为准，勿把设计 SHA 当作当前代码。

| 属性 | 内容 |
| --- | --- |
| 前置任务 | [T05](T05-private-translation.md) |
| 推荐规模 | S-M |
| 对应测试 | [Test T07](../tests/T07-translation-lifecycle.md) |

## 本次交付的完整功能

关闭翻译进度只断开观看；用户可明确取消任务或主动重新生成，失败重试不会覆盖旧成功结果。

**允许修改范围**：复用 ChatGPTTranslationTask 的 generation、lease、CAS，在 UI 区分断开、POST cancel、全新任务 retry；旧成功结果不可变；旧执行者结果 fencing。

**本次明确不做**：不开发新任务状态系统；不承诺已发出上游请求绝不计费。

### 可直接复现的验收路径

翻译运行→关闭面板再连仍为同任务→明确取消后状态可查→重试新 task_id→旧译文仍可看。

### 对应 Test 用例

| Test ID | 可操作情境 | 必须观察到 | Test 文件 |
| --- | --- | --- | --- |
| T07-01 | 关闭连接后再 GET 恢复 | 没有新增模型尝试，服务端任务不会假 cancelled | [Test 契约](../tests/T07-translation-lifecycle.md) |
| T07-02 | 明确 POST cancel 与完成竞态 | 服务器确认后取消状态不能被旧提交覆盖 | [Test 契约](../tests/T07-translation-lifecycle.md) |
| T07-03 | 显式重新生成与失败结果 | 新 task_id，新结果，旧成功依然可读 | [Test 契约](../tests/T07-translation-lifecycle.md) |
| T07-04 | worker 崩溃或超时后结果不明 | interrupted、禁止隐式重试导致二次扣费 | [Test 契约](../tests/T07-translation-lifecycle.md) |
| T07-05 | 现有订阅任务取消/版本语义 | 旧功能无回归 | [Test 契约](../tests/T07-translation-lifecycle.md) |

### 立即停止并纠偏

旧任务回执可覆盖取消/新任务、恢复 GET 自动执行，立即停。

### Codex 一次任务交付要求

1. 查看当前工作目录 AGENTS、分支和未提交改动；读取本卡和同编号 Test、技术方案/最新相关代码。
2. 同环境记录受影响旧测试的基线；用既有 Django/React/SSE/SDK/持久任务，先验证关键假设再编码。
3. 本次只交付这一项**可以运行的完整功能**，包括权限、正常操作与最主要的失败路径；不跨到其它 Txx。
4. 跑最小定向单元/契约测试以及受影响旧功能回归，列出修改过的测试断言 diff；需求未变时禁止改断言迁就代码。
5. 更新对应 Test 文档中的真实日志、环境、SHA 和 NOT_RUN 项；单张任务 PR base 指向 `feat/byok-user-api-keys`。未授权时不合并 main、不开始下一张卡。

**任务结束**：这条用户流程能运行、失败能清楚识别，主要不变量有自动化验证；更新同名 Test 实际证据并留下单张可审核 PR。当前任何未验证的地方明确写 NOT_RUN。

