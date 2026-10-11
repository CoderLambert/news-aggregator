# Test T02 · 录入模型并显式验证

> **PLANNED**：本文件为未执行的实施/测试契约，所有测试当前 NOT_RUN。实施时以 `origin/feat/byok-user-api-keys` 最新 HEAD 为准，勿把设计 SHA 当作当前代码。

对应：[T02 Task](../tasks/T02-models-and-tests.md)。

| 用例 | 场景 / 失败注入 | 正确性约束 | 状态 |
| --- | --- | --- | --- |
| T02-01 | 新增两模型并重新进入列表 | 按连接/用户隔离，目录失败仍允许输入模型ID | NOT_RUN |
| T02-02 | 手动触发测试，不触发保存即测试 | 每个真实上游尝试单独记账，提示可能收费 | NOT_RUN |
| T02-03 | 工具能力与文本能力分开显示 | 未验证/失败工具的模型不可标记研究可用 | NOT_RUN |
| T02-04 | 换 Key/模型参数后旧成功回执迟到 | 不能改变当前状态，未知模型保持未验证 | NOT_RUN |
| T02-05 | 任意 URL/extra_body/unsupported model 参数 | 不能进入 SDK 权限面，不自动落到管理员 Key | NOT_RUN |

## 如何证明

- **基线**：先用该卡涉及的旧测试在同一环境记录原始结果，再引入代码修改；不要凭“测试数量全绿”掩盖不相关回归。
- **实际测试**：新 Django unit/DB/HTTP/worker 或 Vitest/浏览器测试按必要范围补齐；没有业务路径运行的模拟测试不能算功能完整。
- **SDK/Proxy 真实程度**：真实官方 SDK + 受控 upstream 为 SDK_LOCAL；锁定 LiteLLM Proxy + 真实 SDK + 受控 upstream 为 PROXY_LOCAL；只有指定真实 provider/model/region 请求为 PROVIDER_REAL。三者分开记录，缺少对应真实执行证据时标 NOT_RUN。
- **回归**：每个改动了旧测试的文件列出 diff，说明产品语义的变更依据；不准无依据放宽断言。
- **用户验收**：保存两模型→测试其中文字成功而工具未知→换 Key 后旧测试状态过期→再次测试明确成功或失败。

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

