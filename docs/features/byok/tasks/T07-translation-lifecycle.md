# T07 · 翻译取消与显式重新生成

> **IMPLEMENTED · DRAFT PR #41**。T07 在 T06 基线上确认翻译取消、断开恢复、显式重新生成及过期 worker 的行为已由既有任务链实现；本卡新增后端和前端生命周期契约测试，没有重复改写已有产品代码。测试实现提交：`7479a9ef4e0addd3a859cadcd487b5bfc0dd0c96`。自动化结果和未验证范围见 [Test T07](../tests/T07-translation-lifecycle.md)。

| 属性 | 内容 |
| --- | --- |
| 前置任务 | [T05](T05-private-translation.md) |
| 堆叠依赖 | T06 PR [#40](https://github.com/CoderLambert/news-aggregator/pull/40)，基线 `f1b1ebe0549b961cc434c7bdcf84181b230d5a52` |
| 分支 / PR | `task/byok-T07-translation-lifecycle` / [#41](https://github.com/CoderLambert/news-aggregator/pull/41)（Draft；base `task/byok-T06-long-translation`） |
| 推荐规模 | S-M |
| 对应测试 | [Test T07](../tests/T07-translation-lifecycle.md) |

## 本次交付的完整功能

关闭翻译进度只断开观看；用户可明确取消任务或主动重新生成，失败重试不会覆盖旧成功结果。

**本次实际修改**：沿用既有 ChatGPTTranslationTask generation、lease、CAS 与 UI 行为，新增数据库/worker 和 React hook 测试，验证断开与 POST cancel 不混淆、取消后的旧执行结果被 fence、失败的全新任务不覆盖旧译文，以及过期 started task 不会被 GET 或相同幂等键重试。

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
5. 更新对应 Test 文档中的真实日志、环境、SHA 和 NOT_RUN 项；T07 堆叠于尚未合并的 T06 PR #40。未授权时不合并、不开始下一张卡。

**任务结束**：这条用户流程能运行、失败能清楚识别，主要不变量有自动化验证；更新同名 Test 实际证据并留下单张可审核 PR。当前任何未验证的地方明确写 NOT_RUN。

