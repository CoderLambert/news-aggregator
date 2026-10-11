# Test T06 · 长文分块完整翻译

> **PLANNED**：本文件为未执行的实施/测试契约，所有测试当前 NOT_RUN。实施时以 `origin/feat/byok-user-api-keys` 最新 HEAD 为准，勿把设计 SHA 当作当前代码。

对应：[T06 Task](../tasks/T06-long-translation.md)。

| 用例 | 场景 / 失败注入 | 正确性约束 | 状态 |
| --- | --- | --- | --- |
| T06-01 | 跨多 chunk 的输入正确翻译并合并 | 保留代码围栏、标题、链接、表格与顺序 | NOT_RUN |
| T06-02 | 中间 chunk EOF/限长/空输出 | failed/interrupted，只有 partial progress，不能写入完整缓存 | NOT_RUN |
| T06-03 | 排队后文章正文变更 | 冻结输入一致，旧结果不冒充新版源内容 | NOT_RUN |
| T06-04 | 上下文/输出预算未知或超限 | 给出明确限制而非静默截断 | NOT_RUN |
| T06-05 | T05 短文本路径回归 | 仍单次正常完成，旧订阅不变 | NOT_RUN |

## 如何证明

- **基线**：先用该卡涉及的旧测试在同一环境记录原始结果，再引入代码修改；不要凭“测试数量全绿”掩盖不相关回归。
- **实际测试**：新 Django unit/DB/HTTP/worker 或 Vitest/浏览器测试按必要范围补齐；没有业务路径运行的模拟测试不能算功能完整。
- **SDK 真实程度**：实际 SDK + 可控上游为 SDK_LOCAL，真实厂商模型/Key 才能标 PROVIDER_REAL。缺 Key 时明确 NOT_RUN。
- **回归**：每个改动了旧测试的文件列出 diff，说明产品语义的变更依据；不准无依据放宽断言。
- **用户验收**：长文含代码、Markdown标题/链接/表格→显示多段进度→合并无丢段→刷新同结果。

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

