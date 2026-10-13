# RSS地址校验提示与本地验收记录

- 日期：2026-10-13
- 分支：feat/newshub-smart-workspace
- 交付范围：修正Q01错误反馈并记录实际产品验收；保留Q02和8项验收阻塞。

## 变更目标

添加频道输入不合法公开地址时，DRF返回顶层校验数组，原传输层只识别detail，导致错误提示暗示登录故障。现在识别安全校验数据，保留输入便于更正。

## 实际变更

| 文件 | 模块 | 变更 |
|---|---|---|
| frontend/src/services/workspaceApi.ts | 工作区传输 | 识别DRF校验数组/url/non_field_errors；区分400/422、401、403、网络及5xx，拒绝HTML和无界错误文本 |
| frontend/tests/services/workspaceApi.test.ts | 传输测试 | 校验响应、认证/权限、网络与内部诊断安全回归 |
| frontend/tests/components/AddChannelDialog.validation.test.tsx | 组件测试 | 校验信息可见、输入保留、修改后重新匹配、确认订阅保持禁用 |
| docs/features/smart-workspace/LOCAL-QA-2026-10-13.md | 产品验收 | 45项真实证据、Q01/Q02及明确阻塞 |
| 本文 | 变更记录 | 交付范围、验证和后续事项 |

## 实现与兼容

纯前端错误映射修复，后端校验和采集策略不变。只展示有界纯文本API消息，5xx使用安全通用提示，不把内部诊断显示给用户。401提示登录，403提示权限或会话，网络错误提示检查网络。没有数据库迁移或服务权限变更。

## 验证

在相同基线的原隔离QA副本已完成：15项针对测试、76文件537项前端测试、类型检查、lint、构建，以及Chrome直接UI复测。迁移到隔离Git检出后再次核对差异：前端76文件537测试、npm run typecheck、npm run lint、Vite build --configLoader runner和git diff --check均通过。此处构建使用只读既有依赖，package-lock一致。

## 风险和后续

Q02“提交后立即Escape关闭但后台仍提交”保持未修复，对应G04 FAIL。TTS/真实模型和管理员验收仍有8项BLOCKED。未将这些标成通过；本次提交不包含Q02修复，不触碰用户原checkout的数据库，未部署生产。
