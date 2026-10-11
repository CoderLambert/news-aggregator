# Test T14 · 公开部署与兼容性发布关卡

> **PLANNED**：本文件为未执行的实施/测试契约，所有测试当前 NOT_RUN。实施时以 `origin/feat/byok-user-api-keys` 最新 HEAD 为准，勿把设计 SHA 当作当前代码。

对应：[T14 Task](../tasks/T14-release.md)。

| 用例 | 场景 / 失败注入 | 正确性约束 | 状态 |
| --- | --- | --- | --- |
| T14-01 | 迁移前后旧订阅、任务、新闻、TTS数据完整 | 数据库副本对账成功，旧路径回归证据 | NOT_RUN |
| T14-02 | 两个用户 Session/CSRF、端点白名单、私网阻断 | 无越权和 SSRF 外泄 | NOT_RUN |
| T14-03 | read_only、PUBLIC_AI_ENABLED、AI_BYOK_ENABLED、worker | 禁用时无新付费调用，既有历史按权限只读 | NOT_RUN |
| T14-04 | 重启、掉线、取消、完成写库失败 | 不产生伪完成或隐式重复调用 | NOT_RUN |
| T14-05 | 六厂商真实结果与用户UAT状态 | 未执行标 NOT_RUN，最终 GO/NO-GO 附明确范围 | NOT_RUN |

## 如何证明

- **基线**：先用该卡涉及的旧测试在同一环境记录原始结果，再引入代码修改；不要凭“测试数量全绿”掩盖不相关回归。
- **实际测试**：新 Django unit/DB/HTTP/worker 或 Vitest/浏览器测试按必要范围补齐；没有业务路径运行的模拟测试不能算功能完整。
- **SDK 真实程度**：实际 SDK + 可控上游为 SDK_LOCAL，真实厂商模型/Key 才能标 PROVIDER_REAL。缺 Key 时明确 NOT_RUN。
- **回归**：每个改动了旧测试的文件列出 diff，说明产品语义的变更依据；不准无依据放宽断言。
- **用户验收**：测试环境开 BYOK→聊天/翻译/研究可用→关 BYOK→任何新收费调用被拒绝且自己旧结果可读；旧订阅功能能跑。

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

