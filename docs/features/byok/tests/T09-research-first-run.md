# Test T09 · 首次个人模型深度研究

> **PLANNED**：本文件为未执行的实施/测试契约，所有测试当前 NOT_RUN。实施时以 `origin/feat/byok-user-api-keys` 最新 HEAD 为准，勿把设计 SHA 当作当前代码。

对应：[T09 Task](../tasks/T09-research-first-run.md)。

| 用例 | 场景 / 失败注入 | 正确性约束 | 状态 |
| --- | --- | --- | --- |
| T09-01 | 新建研究→调用一个合法工具→保存结果/Run/Event | 真正上游最终完成后事务提交 | NOT_RUN |
| T09-02 | 生产环境个人合法 Key 与无 Key/未获批订阅 | 前者按 BYOK 开关鉴权；后者仍受阻断 | NOT_RUN |
| T09-03 | 未验证 tools、工具名非法、参数无效 | 拒绝派发或拒绝执行，消息仅为不受信任数据 | NOT_RUN |
| T09-04 | 工具写入失败、任务取消、最终 CAS失败 | 不能误报 succeeded | NOT_RUN |
| T09-05 | 现有研究历史/SSE/Idempotency-Key | 不复制或破坏旧 run 机制 | NOT_RUN |

## 如何证明

- **基线**：先用该卡涉及的旧测试在同一环境记录原始结果，再引入代码修改；不要凭“测试数量全绿”掩盖不相关回归。
- **实际测试**：新 Django unit/DB/HTTP/worker 或 Vitest/浏览器测试按必要范围补齐；没有业务路径运行的模拟测试不能算功能完整。
- **SDK/Proxy 真实程度**：真实官方 SDK + 受控 upstream 为 SDK_LOCAL；锁定 LiteLLM Proxy + 真实 SDK + 受控 upstream 为 PROXY_LOCAL；只有指定真实 provider/model/region 请求为 PROVIDER_REAL。三者分开记录，缺少对应真实执行证据时标 NOT_RUN。
- **回归**：每个改动了旧测试的文件列出 diff，说明产品语义的变更依据；不准无依据放宽断言。
- **用户验收**：选已验证模型→发起新研究→实际工具调用/记录→完整答案入库→GET读旧报告。

## 执行证据（后续任务填写）

| 项目 | 结果 |
| --- | --- |
| 本卡状态 | **NOT_RUN** |
| 精确基线 HEAD 与本任务 HEAD | NOT_RUN |
| DB / SDK / 浏览器 / OS 版本 | NOT_RUN |
| 定向测试和原始 stdout | NOT_RUN |
| 旧基线与增量回归对照 | NOT_RUN |
| SDK_LOCAL / PROXY_LOCAL / PROVIDER_REAL / UAT 分别记录 | NOT_RUN |
| 测试代码 diff（包括旧断言修改） | NOT_RUN |
| 可复现功能演示结果 | NOT_RUN |
| 未验证、失败原因、修复 PR | NOT_RUN |

任何来源缺失，保留 NOT_RUN，不能伪造 PASS。

