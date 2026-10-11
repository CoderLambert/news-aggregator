# Test T13 · 首批六个产品预设的真实验证关卡

> **PLANNED**：本文件为未执行的实施/测试契约，所有测试当前 NOT_RUN。实施时以 `origin/feat/byok-user-api-keys` 最新 HEAD 为准，勿把设计 SHA 当作当前代码。

对应：[T13 Task](../tasks/T13-providers.md)。

| 用例 | 场景 / 失败注入 | 正确性约束 | 状态 |
| --- | --- | --- | --- |
| T13-01 | 首批六个子卡分别记录真实 Key 与指定模型文本结果 | 首轮只 DeepSeek 获准 PROVIDER_REAL；其他预设保持 NOT_RUN | NOT_RUN |
| T13-02 | 经 Proxy 的原始终态与断流/输出限制 | 有真实上游证据后才标记对应模型；PROXY_LOCAL 不作真实兼容结论 | NOT_RUN |
| T13-03 | 工具能力/特殊 reasoning 续接 | 仅对真实验收通过的特定模型开放研究工具 | NOT_RUN |
| T13-04 | 同一环境双用户/不同 provider Key | 不串 Proxy 项目身份、路由或 Key，也不 fallback | NOT_RUN |
| T13-05 | 某厂商无 Key 或额度不足 | 独立 BLOCKED/NOT_RUN，不伪造成功 | NOT_RUN |

## 如何证明

- **基线**：先用该卡涉及的旧测试在同一环境记录原始结果，再引入代码修改；不要凭“测试数量全绿”掩盖不相关回归。
- **实际测试**：新 Django unit/DB/HTTP/worker 或 Vitest/浏览器测试按必要范围补齐；没有业务路径运行的模拟测试不能算功能完整。
- **SDK/Proxy 真实程度**：真实官方 SDK + 受控 upstream 为 SDK_LOCAL；锁定 LiteLLM Proxy + 真实 SDK + 受控 upstream 为 PROXY_LOCAL；只有指定真实 provider/model/region 请求为 PROVIDER_REAL。三者分开记录，缺少对应真实执行证据时标 NOT_RUN。
- **回归**：每个改动了旧测试的文件列出 diff，说明产品语义的变更依据；不准无依据放宽断言。
- **用户验收**：首批六个产品预设各有独立记录；首轮只运行获准的 DeepSeek 子卡。其他五个真实兼容性继续 NOT_RUN；T00-G 运维通过也不构成 provider 证据。

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

