# AI 模型探针与本地侧车网络恢复实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 防止本地前端预览使共享 app 网络的侧车失联，并让用户看到模型探针的真实安全结果。

**Architecture:** 预览脚本从 Compose JSON 合并配置推导 `network_mode: service:<app>` 的侧车，并将它们与 app 作为同一重建单元。前端使用已有 `AIModelProbeReceipt` 的 `status` 和 `safe_error_code` 生成一次性、不泄密的结果提示。

**Tech Stack:** Bash, Docker Compose v2 JSON config, Python 3 standard library, React/TypeScript, Vitest/Testing Library.

**Spec:** `docs/development/任务计划/ai-probe-runtime-recovery/design.md`

## 全局约束

- 不自动调用真实模型，不自动重试未知探针。
- 不重建镜像、不迁移或删除数据卷、不读取或输出凭据。
- 仅修复本地预览入口与已有模型管理界面，不扩展到生产发布流程。
- 所有运行时验收使用当前本地 Compose 项目；自动测试使用合成资源。

## 评审重点

- Compose 配置中没有侧车时，预览仍只重建 app，且不产生空参数。
- 多个侧车共享 app 网络时，激活和回滚使用同一服务集合。
- Compose JSON 无效或指向未知服务时安全失败，不执行 Docker 更改。
- 已完成但结果未知的探针显示警告而非成功提示，且费用确认复位。
- 请求级失败继续冻结写操作并要求 GET 对账，不被新的结果提示覆盖。

---

### Task 1：预览脚本侧车重建单元

**Files:**
- Modify: `scripts/deploy/local-frontend-preview.sh`
- Test: `scripts/deploy/tests/test_local_frontend_preview.sh`
- Modify: `docs/deployment/production-containers.md`

**Interfaces:**
- Consumes: `docker compose ... config --format json` 的 `services.<name>.network_mode` 字段。
- Produces: `RECREATE_SERVICES` Bash 数组，首项为 `app`，后续为排序后的 `service:app` 侧车。

- [x] 在 `test_local_frontend_preview.sh` 中增加合成 Compose 配置和假 Docker，断言激活与回滚命令均包含 app 及侧车，无侧车时仅包含 app。
- [x] 运行 `bash scripts/deploy/tests/test_local_frontend_preview.sh`，确认新断言在当前脚本上 FAIL。
- [x] 在任何 Docker 更改前解析合并 Compose JSON，验证服务名安全且目标存在，生成 `RECREATE_SERVICES`。
- [x] 将激活、恢复和最终输出改为同一重建单元，保留镜像一致性与挂载校验。
- [x] 同步本地预览文档，说明共享 app 网络的侧车会一起重建。
- [x] 重跑脚本定向测试，预期 PASS。

### Task 2：探针结果可读反馈

**Files:**
- Modify: `frontend/src/components/workspace/AIModelsManager.tsx`
- Test: `frontend/tests/pages/AIModelsManager.test.tsx`

**Interfaces:**
- Consumes: `AIModelProbeReceipt.status` 与 `AIModelProbeReceipt.safe_error_code`。
- Produces: `probeResultMessage(receipt): { tone: 'success' | 'warning'; message: string }`。

- [x] 新增组件测试：文本成功显示“已验证支持”；`result_unknown` 显示网关/网络结果未确认；`incomplete_or_invalid` 显示响应不完整；`unsupported` 显示明确不支持。
- [x] 运行 `cd frontend && npm run test:run -- tests/pages/AIModelsManager.test.tsx`，确认新测试 FAIL。
- [x] 实现结果映射与独立警告样式，使 `perform` 保留现有未知写入对账行为，并在已完成探针后使用返回 receipt。
- [x] 断言已完成未知结果不自动重发、模型列表仍仅 GET 刷新、费用确认框复位。
- [x] 运行定向组件测试、`npm run typecheck` 和受影响 lint，预期 PASS。

### Task 3：当前本地运行时恢复与验收

**Files:**
- Runtime only: Compose project `newshub-main-ad36959`

**Interfaces:**
- Consumes: 当前 Compose 文件集、现有镜像、secrets 和数据卷；不读取 secret 内容。
- Produces: 应用新脚本的预览 app 与同组侧车，全部健康。

- [x] 用当前 Compose 文件集强制重建 `app`、`channel-worker`、`translation-redis`、`ai-gateway`，不重建镜像、不删除卷。
- [x] 等待所有目标服务 healthy，确认 `ai-gateway` readiness 不再因 PostgreSQL 不可达而失败。
- [x] 通过真实浏览器确认 AI 设置页可加载、探针按钮仍需明确费用确认，且不点击收费探针。
- [x] 使用 `newshub-test-acceptance` 指定的 Luna 代理运行定向回归和本地验收，分别报告 PASS/FAIL/NOT_RUN。
