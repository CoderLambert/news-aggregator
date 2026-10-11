# Test T03 · 用途默认模型设置

> **PLANNED**：本文件为未执行的实施/测试契约，所有测试当前 NOT_RUN。实施时以 `origin/feat/byok-user-api-keys` 最新 HEAD 为准，勿把设计 SHA 当作当前代码。

对应：[T03 Task](../tasks/T03-preferences.md)。

| 用例 | 场景 / 失败注入 | 正确性约束 | 状态 |
| --- | --- | --- | --- |
| T03-01 | 保存五个偏好并重新 GET | 只对当前用户有效，必须明确点击保存 | NOT_RUN |
| T03-02 | 草稿撤销与保存失败 | 草稿状态真实，不宣称持久化成功 | NOT_RUN |
| T03-03 | 偏好指向 B 的模型或停用连接 | 拒绝，缺省时不得自动用站点/订阅凭据 | NOT_RUN |
| T03-04 | 改变默认与正在运行任务的执行快照 | 已开始任务完全不变，历史仍可读 | NOT_RUN |
| T03-05 | 阅读设置/ChatGPT设置与 390px 布局 | 旧入口正常，新页面易于操作 | NOT_RUN |

## 如何证明

- **基线**：先用该卡涉及的旧测试在同一环境记录原始结果，再引入代码修改；不要凭“测试数量全绿”掩盖不相关回归。
- **实际测试**：新 Django unit/DB/HTTP/worker 或 Vitest/浏览器测试按必要范围补齐；没有业务路径运行的模拟测试不能算功能完整。
- **SDK/Proxy 真实程度**：真实官方 SDK + 受控 upstream 为 SDK_LOCAL；锁定 LiteLLM Proxy + 真实 SDK + 受控 upstream 为 PROXY_LOCAL；只有指定真实 provider/model/region 请求为 PROVIDER_REAL。三者分开记录，缺少对应真实执行证据时标 NOT_RUN。
- **回归**：每个改动了旧测试的文件列出 diff，说明产品语义的变更依据；不准无依据放宽断言。
- **用户验收**：配置五个用途→显示未保存→保存→刷新→不同账号各自读取→停用连接显示需重选，不偷偷兜底。

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

