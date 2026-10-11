# Test T12 · 个人 AI 使用记录

> **PLANNED**：本文件为未执行的实施/测试契约，所有测试当前 NOT_RUN。实施时以 `origin/feat/byok-user-api-keys` 最新 HEAD 为准，勿把设计 SHA 当作当前代码。

对应：[T12 Task](../tasks/T12-usage.md)。

| 用例 | 场景 / 失败注入 | 正确性约束 | 状态 |
| --- | --- | --- | --- |
| T12-01 | 每次实际上游尝试对应一次记录，不按 SSE 用户订阅计数 | 含用户、用途、模型、时间、状态，无原文和密钥 | NOT_RUN |
| T12-02 | 上游 usage 缺失或请求结果未知 | 显示未知/NULL 而不是 0 | NOT_RUN |
| T12-03 | GET恢复/只读缓存反复执行 | 不会额外增加 attempt | NOT_RUN |
| T12-04 | B 读取 A 使用记录 | 严格拒绝 | NOT_RUN |
| T12-05 | 现有限流、取消、异常路径 | 不会因统计副作用重复调用 Provider | NOT_RUN |

## 如何证明

- **基线**：先用该卡涉及的旧测试在同一环境记录原始结果，再引入代码修改；不要凭“测试数量全绿”掩盖不相关回归。
- **实际测试**：新 Django unit/DB/HTTP/worker 或 Vitest/浏览器测试按必要范围补齐；没有业务路径运行的模拟测试不能算功能完整。
- **SDK 真实程度**：实际 SDK + 可控上游为 SDK_LOCAL，真实厂商模型/Key 才能标 PROVIDER_REAL。缺 Key 时明确 NOT_RUN。
- **回归**：每个改动了旧测试的文件列出 diff，说明产品语义的变更依据；不准无依据放宽断言。
- **用户验收**：测试模型+问答各一次→显示两条 attempt→重新 GET 历史不增加→失败/断线标未知 usage。

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

