# 本地完整运行时实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `newshub-local-main` 的手工验收运行时强制启动并验证管理页列出的全部依赖服务。

**Architecture:** 保留轻量 `compose.yaml` 作为开发基座，新增一个本地完整覆盖层和唯一激活脚本。脚本在仓库外冻结精确候选代码并与既有数据库/数据所有者分离，持久内部密钥，幂等初始化 Miniflux 专用账号与 LiteLLM 项目 Key，然后以 `runtime_health` 的全七项 ready 作为成功门禁。

**Tech Stack:** Docker Compose v2, Bash, Python 3 standard library, Django, React/TypeScript, pytest, Vitest.

## 全局约束

- 暂停预热和健康门禁不主动调用真实模型或订阅源，不自动重试付费探针；业务 I/O 明确释放后，已有授权队列与订阅按正常规则继续处理。
- 不删除或重建现有数据卷，不轮换已存在的运行时密钥。
- 保留 `newshub-local-main`、`127.0.0.1:19527`、当前 SQLite 与用户 BYOK 配置。
- 不修改生产 Compose 的服务选择语义。

---

### Task 1：完整本地 Compose 合约

- [ ] 先写合成测试，要求 app、indexer、RSS、频道、Redis 和 AI 网关服务都存在且安全连线。
- [ ] 实现 `compose.local-full.yaml`，复用现有固定镜像和最小权限。
- [ ] 确认定向合成测试通过。

### Task 2：幂等本地激活与回退

- [ ] 先写假 Docker/临时密钥测试，覆盖首次启动、重复执行、配置缺失和不健康回退。
- [ ] 实现本地运行时 bootstrap 辅助程序与 `local-full-runtime.sh`。
- [ ] 强制所有七项健康检查 ready，禁止 disabled 被视为成功。

### Task 3：AI 网关错误可见性

- [ ] 先增加 `gateway_unavailable` 组件回归测试。
- [ ] 实现精确中文提示，保留费用确认和不自动重试。
- [ ] 运行定向测试、typecheck 与 build。

### Task 4：本地候选验收与交付

- [ ] 运行 Compose/部署、后端健康和前端定向回归。
- [ ] 以新入口更新 `newshub-local-main`，保留数据与回退点；暂停预热阶段不发送 Provider/订阅源请求。
- [ ] 确认运行时七项全部 ready，保留真实 DeepSeek/RSS 业务验收为用户手动步骤。
