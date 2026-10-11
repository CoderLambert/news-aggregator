# BYOK · 个人 API Key 与模型配置

> 设计阶段资料总入口。**本分支目前仅提交设计文档、可交互静态原型与原型检查脚本；尚未开发 BYOK API / React 业务页面，也未验证真实付费模型。**

- 仓库：`CoderLambert/news-aggregator`
- 功能分支：`feat/byok-user-api-keys`
- 上游基线：`feat/news-public-readiness@b874405f31ae303e772d1ed6ef618b68938febed`
- 设计状态：**页面方向已确认；具体 Task/Test 拆分待下一步开展**
- 功能边界：六家主流官方通用 API Key、连接管理、每用途模型选择、个人结果与现有任务系统复用。

## 导航

| 内容 | 文件 | 说明 |
| --- | --- | --- |
| 技术设计 / 风险验证 | [BYOK_IMPLEMENTATION_PLAN.md](BYOK_IMPLEMENTATION_PLAN.md) | 技术选型、代码现状、预防性约束、实施阶段与验证边界 |
| Codex 执行交接 | [CODEX_HANDOFF.md](CODEX_HANDOFF.md) | 开发守则、P0 首步、必须保持的不变量 |
| 页面和交互设计 | [BYOK_PAGE_DESIGN_SPEC.md](BYOK_PAGE_DESIGN_SPEC.md) | 真实 NewsHub 页面接入点、交互流程和状态约束 |
| 独立可交互原型 | [prototype/index.html](prototype/index.html) | 自包含 HTML/CSS/JS，包含模拟连接、模型偏好、文章预览 |
| 原型使用和视觉复现 | [prototype/README.md](prototype/README.md) | 打开方式与生成桌面/手机截图的方法 |
| Task 规划 | [tasks/README.md](tasks/README.md) | 待拆分：按功能交付切片，不按文件罗列 |
| Test 规划 | [tests/README.md](tests/README.md) | 待拆分：变更前基线、状态不变量和回归证明 |

## 设计决定（已固定）

- 两类官方 SDK：`openai`、`anthropic`；三种薄协议适配器：Responses、Chat Completions、Messages。
- 复用现有 `ResearchRun`、`ResearchRunEvent`、`ChatGPTTranslationTask`，不开发第二套任务系统。
- 新增 `/settings/ai`，保留 `/settings/chatgpt`，两种凭据不混用。
- 个人 Key 只用于明确选择的用户任务，永不隐式兜底到管理员 Key 或 ChatGPT 订阅。
- 恢复只读取历史任务，不隐式发起付费请求；上游真实终态与事务提交成功才能显示完成。
- 首批不支持用户任意 Base URL、不接入 Coding/Token Plan。
- 原型所有表单、测试、回答均为浏览器内模拟；**禁止在原型输入真实 API Key**。

## 本阶段交付边界

1. 已完成：产品 UI 方向确认、技术设计基线、独立原型、静态原型验证脚本。
2. 未开始：项目 BYOK 业务代码、真实 SDK 联调、Task 文档拆分、功能级/发布级测试。
3. 后续：先形成 Task/Test 对照，再从 P0 技术切片推进。每项任务必须给出变更前证据、必须保持的契约和实际验收结果。

**备注**：独立 HTML 是审阅原型，不会在生产页面自动出现。设计截图由 `prototype/check_ui.py` 在本地浏览器环境中按需再生成，避免提交冗余二进制截图。
