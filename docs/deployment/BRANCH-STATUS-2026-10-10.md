# `feat/news-public-readiness` 分支开发内容与进度

日期：2026-10-10  
基线：当前分支相对 `main` 的 merge-base 为 `8c2823e1fcf8cbea38e9bb7c4e98a33232025fbd`。

## 分支内容概览

- **G1 本地发布准备**：只读访问策略、生产配置与容器/持久化路径、反向代理和本地域名 HTTPS 验收工具链。G1 的本地验收与安全复审记录在 `PROGRESS.md`；没有执行公网部署。
- **G2 账户与订阅安全**：账户、CSRF、数据归属、邀请/限速及 OAuth 订阅接入骨架。NH-PUB-08 已知安全骨架已审查；完整账户域名验收仍未通过。
- **G3 翻译持久恢复**：以 `ChatGPTTranslationTask` 持久化全文翻译状态，加入 generation/run-token/shared-lease fence、断线恢复、owner GET/显式取消，并复用既有执行器。
- **G3 研究任务恢复**：以 `ResearchRun`/事件表持久化研究任务；加入幂等 attach、owner 状态读取/取消、SSE 事件回放和资源上限，以及前端按 viewer 隔离的恢复、取消、重连。关闭研究面板或切换会话只断开浏览器连接，不取消后台任务。
- 取消 AI 费用、日额度、次数与 Token 预算方案；没有共享管理员订阅或站点付费 Provider fallback。

## 当前状态

| 工作流 | 状态 | 说明 |
| --- | --- | --- |
| G1 本地发布准备 | 本地验收/复审完成 | 不代表公网服务器已部署。 |
| G2 账户及本地域名 | **DOING / 未通过** | 固定 G2 R5 候选按合同仅运行一次，失败于 `g2.shared_browser`；精确资源 `cleanup PASS`。账户后续、限速、SSE 未运行，按合同不重试。 |
| G3 翻译恢复 | 本地实现、定向验收、独立复审完成 | 真实 website OAuth / 模型调用仍 `EXTERNAL_BLOCKED`。 |
| G3 研究恢复 | 本地实现、定向验收、独立复审完成 | 真实 website Provider 调用与生产部署仍未获授权。 |

## 本地验证证据

- 后端隔离定向回归：订阅恢复、原订阅兼容、共享翻译、研究恢复、CSRF 与 public-policy 路径，**118 passed，3 warnings**。
- 前端恢复/UI/API/导航定向回归：**5 个文件、51 tests passed**；`npm run typecheck` 与 `npm run build` 通过。
- `makemigrations --check --dry-run` 无 schema 差异；0030/0031 在新建隔离 SQLite 数据库上迁移成功。未迁移用户数据库。
- 独立安全复审 `findings=[]`，未报告 High/Critical 或 material lower-severity blocker。
- Chromium 视觉演练使用真实 `ResearchPanel` 组件及本地隔离模拟 API，观察到显式取消、继续接收和恢复结果；这不是实际 Django/Provider 或正式域名验收。

所有恢复验证都在过滤后的隔离归档、`env -i`、独立 HOME/TMPDIR 与临时数据库中完成；没有调用真实 Provider/OAuth/模型、没有部署或访问 `127.0.0.1:9527`。本次提交排除已修改的 `backend/db.sqlite3`，以及 `.codex/`、`GOAL.md`、`START_HERE.md`、`docs/deployment/README.md`、`reference-plan.md` 和 `docs/plans/` 等既有未跟踪用户文件。详细任务表、命令及 G2 运行报告见 `TASKS.md`、`PROGRESS.md` 与 `HANDOFF-2026-10-10.md`。

本次报告与本地代码变更随 `feat/news-public-readiness` 分支提交并推送。整体 G2/发布验收仍未通过；外部 OAuth 批准和公网部署仍为 `EXTERNAL_BLOCKED`。
