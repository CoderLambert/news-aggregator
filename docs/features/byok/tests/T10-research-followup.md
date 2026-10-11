# Test T10 · 研究续问与安全恢复

> **PLANNED**：本文件为未执行的实施/测试契约，所有测试当前 NOT_RUN。实施时以 `origin/feat/byok-user-api-keys` 最新 HEAD 为准，勿把设计 SHA 当作当前代码。

对应：[T10 Task](../tasks/T10-research-followup.md)。

| 用例 | 场景 / 失败注入 | 正确性约束 | 状态 |
| --- | --- | --- | --- |
| T10-01 | 二轮工具调用保留原生 provider continuation | 可见消息与秘密续接分离，最终完整入库 | NOT_RUN |
| T10-02 | GET status/stream 重连 | 零新任务、零 provider 请求 | NOT_RUN |
| T10-03 | 重复 POST 同幂等键/不同请求同键 | 同运行 / 409 冲突，无重复收费 | NOT_RUN |
| T10-04 | cancel、迟到 response、运行租约过期 | run_token/CAS 阻止旧提交，未知上游状态不重发 | NOT_RUN |
| T10-05 | 既有研究会话继续读取与历史权限 | 不回归 | NOT_RUN |

## 如何证明

- **基线**：先用该卡涉及的旧测试在同一环境记录原始结果，再引入代码修改；不要凭“测试数量全绿”掩盖不相关回归。
- **实际测试**：新 Django unit/DB/HTTP/worker 或 Vitest/浏览器测试按必要范围补齐；没有业务路径运行的模拟测试不能算功能完整。
- **SDK/Proxy 真实程度**：真实官方 SDK + 受控 upstream 为 SDK_LOCAL；锁定 LiteLLM Proxy + 真实 SDK + 受控 upstream 为 PROXY_LOCAL；只有指定真实 provider/model/region 请求为 PROVIDER_REAL。三者分开记录，缺少对应真实执行证据时标 NOT_RUN。
- **回归**：每个改动了旧测试的文件列出 diff，说明产品语义的变更依据；不准无依据放宽断言。
- **用户验收**：研究完成→提追问→工具二轮→断线重连 GET 恢复同 run_id→明确取消仅取消最新任务。

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

