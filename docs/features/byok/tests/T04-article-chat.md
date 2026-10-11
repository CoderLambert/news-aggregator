# Test T04 · 新闻问答 BYOK 闭环

> **PLANNED**：本文件为未执行的实施/测试契约，所有测试当前 NOT_RUN。实施时以 `origin/feat/byok-user-api-keys` 最新 HEAD 为准，勿把设计 SHA 当作当前代码。

对应：[T04 Task](../tasks/T04-article-chat.md)。

| 用例 | 场景 / 失败注入 | 正确性约束 | 状态 |
| --- | --- | --- | --- |
| T04-01 | 正文与问答成功经实际 SDK Stream 返回 | 显示模型来源，历史持久可读 | NOT_RUN |
| T04-02 | 半截流中断/无终态/Key失效 | 不保存为成功，不默默重试/回退 | NOT_RUN |
| T04-03 | A/B 并发同文问答及 A 退出后旧流迟到 | 各自模型、session和Query缓存互不覆盖 | NOT_RUN |
| T04-04 | 本次改模型与长期偏好 | 只改本次调用，不改变用途默认或既有任务 | NOT_RUN |
| T04-05 | 既有 ChatGPT 订阅问答/焦点键盘 | 兼容原行为，旧断言不迁就回归 | NOT_RUN |

## 如何证明

- **基线**：先用该卡涉及的旧测试在同一环境记录原始结果，再引入代码修改；不要凭“测试数量全绿”掩盖不相关回归。
- **实际测试**：新 Django unit/DB/HTTP/worker 或 Vitest/浏览器测试按必要范围补齐；没有业务路径运行的模拟测试不能算功能完整。
- **SDK 真实程度**：实际 SDK + 可控上游为 SDK_LOCAL，真实厂商模型/Key 才能标 PROVIDER_REAL。缺 Key 时明确 NOT_RUN。
- **回归**：每个改动了旧测试的文件列出 diff，说明产品语义的变更依据；不准无依据放宽断言。
- **用户验收**：A 对文章提问→流回答→关闭助手再打开读到历史→A 切模型仅影响下次提问；B 无 A 的任何记录。

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

