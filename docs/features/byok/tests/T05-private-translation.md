# Test T05 · 个人全文翻译最小闭环

> **PLANNED**：本文件为未执行的实施/测试契约，所有测试当前 NOT_RUN。实施时以 `origin/feat/byok-user-api-keys` 最新 HEAD 为准，勿把设计 SHA 当作当前代码。

对应：[T05 Task](../tasks/T05-private-translation.md)。

| 用例 | 场景 / 失败注入 | 正确性约束 | 状态 |
| --- | --- | --- | --- |
| T05-01 | 完整上游终态+事务提交结果、任务和完成事件 | 结果有稳定 task_id/result_id，关 SSE 不影响已成功内容 | NOT_RUN |
| T05-02 | 重复 Idempotency-Key 同请求/不同请求/同源并发 | 前者同任务，后者409，无二次自动调用 | NOT_RUN |
| T05-03 | partial EOF/length/DB提交失败 | 进度不能作为完成译文，禁止 complete | NOT_RUN |
| T05-04 | A/B 使用自己的 Key 译同篇文章 | 不同用户/连接隔离，BYOK内容不发布 shared | NOT_RUN |
| T05-05 | 旧 subscription 翻译任务和旧迁移行 | 旧语义/外键约束保持 | NOT_RUN |

## 如何证明

- **基线**：先用该卡涉及的旧测试在同一环境记录原始结果，再引入代码修改；不要凭“测试数量全绿”掩盖不相关回归。
- **实际测试**：新 Django unit/DB/HTTP/worker 或 Vitest/浏览器测试按必要范围补齐；没有业务路径运行的模拟测试不能算功能完整。
- **SDK 真实程度**：实际 SDK + 可控上游为 SDK_LOCAL，真实厂商模型/Key 才能标 PROVIDER_REAL。缺 Key 时明确 NOT_RUN。
- **回归**：每个改动了旧测试的文件列出 diff，说明产品语义的变更依据；不准无依据放宽断言。
- **用户验收**：短/中篇 Markdown→个人模型翻译→显示成功→刷新通过 GET 恢复同一个 result_id；超过预算明确拒绝。

## 执行证据（后续任务填写）

| 项目 | 结果 |
| --- | --- |
| 本卡状态 | **NOT_RUN** |
| 精确基线 HEAD 与本任务 HEAD | NOT_RUN |
| DB / SDK / 浏览器 / OS 版本 | NOT_RUN |
| 定向测试和原始 stdout | NOT_RUN |
| 旧基线与增量回归对照 | NOT_RUN |
| SDK_LOCAL / PROVIDER_REAL / UAT 分别记录 | NOT_RUN |
| 测试代码 diff（包括旧断言修改） | NOT_RUN |
| 可复现功能演示结果 | NOT_RUN |
| 未验证、失败原因、修复 PR | NOT_RUN |

任何来源缺失，保留 NOT_RUN，不能伪造 PASS。

