# Test T00 · SDK 协议验真

> **PLANNED**：本文件为未执行的实施/测试契约，所有测试当前 NOT_RUN。实施时以 `origin/feat/byok-user-api-keys` 最新 HEAD 为准，勿把设计 SHA 当作当前代码。

对应：[T00 Task](../tasks/T00-sdk-protocol.md)。

| 用例 | 场景 / 失败注入 | 正确性约束 | 状态 |
| --- | --- | --- | --- |
| T00-01 | 真实 SDK 文本和流在三种协议均收到各自完整终态 | 只完整且语义正确时报告成功 | NOT_RUN |
| T00-02 | partial 后 EOF/length/incomplete/stream error/HTTP error | 全部是明确非成功，不能生成 complete | NOT_RUN |
| T00-03 | tools 往返保留 Responses items / Anthropic thinking 签名 / Chat reasoning_content | 仅允许白名单工具和完整合法参数，可见消息剔除私密续接 | NOT_RUN |
| T00-04 | 两组显式 Key/模型并发调用；设置 max_retries=0 | HTTP 请求无凭据混用，无隐式重发 | NOT_RUN |
| T00-05 | 已有聊天/研究/翻译入口未被替换 | 已有旧测试按基线运行 | NOT_RUN |

## 如何证明

- **基线**：先用该卡涉及的旧测试在同一环境记录原始结果，再引入代码修改；不要凭“测试数量全绿”掩盖不相关回归。
- **实际测试**：新 Django unit/DB/HTTP/worker 或 Vitest/浏览器测试按必要范围补齐；没有业务路径运行的模拟测试不能算功能完整。
- **SDK 真实程度**：实际 SDK + 可控上游为 SDK_LOCAL，真实厂商模型/Key 才能标 PROVIDER_REAL。缺 Key 时明确 NOT_RUN。
- **回归**：每个改动了旧测试的文件列出 diff，说明产品语义的变更依据；不准无依据放宽断言。
- **用户验收**：执行一个脚本依次验证正常完成、仅输出 partial 后 EOF、流内错误与 tools→result→final；打印脱敏结果和版本。

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

