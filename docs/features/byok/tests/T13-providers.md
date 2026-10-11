# Test T13 · 六家厂商真实兼容性关卡

> **PLANNED**：本文件为未执行的实施/测试契约，所有测试当前 NOT_RUN。实施时以 `origin/feat/byok-user-api-keys` 最新 HEAD 为准，勿把设计 SHA 当作当前代码。

对应：[T13 Task](../tasks/T13-providers.md)。

| 用例 | 场景 / 失败注入 | 正确性约束 | 状态 |
| --- | --- | --- | --- |
| T13-01 | 六张子卡分别有真实通用 Key +指定模型的文本结果 | 只有实测成功标文本已验证 | NOT_RUN |
| T13-02 | 原生真实终态与断流/输出限制 | SDK 会识别失败与不完整 | NOT_RUN |
| T13-03 | 工具能力/特殊 reasoning 续接 | 仅对实际通过的模型启用研究工具 | NOT_RUN |
| T13-04 | 同一环境双用户/不同 Key | 不串路由或 Key，也不 fallback | NOT_RUN |
| T13-05 | 某厂商无 Key 或额度不足 | 独立 BLOCKED/NOT_RUN，不伪造成功 | NOT_RUN |

## 如何证明

- **基线**：先用该卡涉及的旧测试在同一环境记录原始结果，再引入代码修改；不要凭“测试数量全绿”掩盖不相关回归。
- **实际测试**：新 Django unit/DB/HTTP/worker 或 Vitest/浏览器测试按必要范围补齐；没有业务路径运行的模拟测试不能算功能完整。
- **SDK 真实程度**：实际 SDK + 可控上游为 SDK_LOCAL，真实厂商模型/Key 才能标 PROVIDER_REAL。缺 Key 时明确 NOT_RUN。
- **回归**：每个改动了旧测试的文件列出 diff，说明产品语义的变更依据；不准无依据放宽断言。
- **用户验收**：六份独立的提供商验证记录；没有合法凭据的厂家逐项 BLOCKED/NOT_RUN。

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

