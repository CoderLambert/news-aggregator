# 原 BYOK T01：多连接管理差量交付

> **后续整合状态（2026-10-18）**：本报告记录的是当时“旧单 Key 与新连接并存”的局部交付历史，当前实现已由 [PR #103](https://github.com/CoderLambert/news-aggregator/pull/103) 取代。正式 `main@13584bc` 已移除旧 UserProviderCredential 的业务模型/API/UI/服务；旧密钥通过 `0061` 原子转换为停用的 `UserAIConnection`，失败整批回滚。仅新 `/settings/ai` 负责 Key 管理，ChatGPT 订阅保持独立。PR 级自动化为 2454 passed / 16 skipped，frontend/G1 成功。原 T01 worker 全量 epoch 撤销仍在第 5 批；真实数据库/模型/浏览器人工/生产环境 NOT_RUN。详见[统一计划](../../plans/FEATURE-DEVELOPMENT-2026-10-17.md)。以下保留原始工作记录，**不能当作当前架构说明**。

基线 main `53370185430f0bc7e83534263088a4155f836ed3`。原 Task/Test 继续有效，复用旧 #34 的连接身份、两种凭据版本和 AEAD 设计，不重放旧迁移。原 T01 保持 **PARTIAL**，本次交付连接 CRUD，不假称已完成所有 worker 消费端。

## 实际改动

- `/settings/ai` 管理多个连接、别名、掩码、替换、启停和确认删除；旧 `/settings` 单 Key 与 `/settings/chatgpt` 保留。
- `api/me/ai/` 提供受信提供方目录及本人 CRUD。沿用已有 LiteLLM 提供方目录，不创建另一套 Provider 协议适配，不接受用户自定义 URL/headers/extra_body。
- 0060 只新增原设计 `UserAIConnection`；不改动旧 Key、文章、用户关系或旧迁移。创建请求的 owner+request_id 唯一，HMAC 比较同请求；修改带 revision 冲突检查。每用户最多 20 个未删除连接。
- AES-GCM AAD 绑定用户、连接 UUID、提供方、端点身份/版本与密文版本。启停改变授权 epoch 而不改变密文版本；删除清密文并保留撤销墓碑。缺加密材料拒绝新增/替换/启用，停用和删除仍可撤销。
- 沿用现有 Session/CSRF 与 workspace viewer 约束；服务端不回显请求字段/异常。浏览器立即清除提交 Key；响应未知只做 GET 对账，不自动重发。账号切换或卸载后旧响应不得更新新界面。
- 提供发送前与事务提交期的 epoch 检查服务。测试覆盖这些**服务函数**，不声称既有翻译/研究 worker 已接入新连接。

## 开关与兼容

`AI_BYOK_ENABLED` 默认 `0`，只接受 `0` 或 `1`；仍受站点 full/read_only、登录、CSRF 限制。复用现有稳定 `PROVIDER_CREDENTIAL_ENCRYPTION_KEY` 及 HKDF，缺失时不降级为明文。本次未修改任何部署配置或生产开关。

新连接只负责保存管理，不自动成为旧业务默认。未迁移、未复制、未撤销旧 `UserProviderCredential`；界面明确显示两者边界。新连接不会开启推理或产生模型调用。区域细分的端点档案、旧数据迁移/统一切换以及 T01-03 真正业务 worker 接线仍是原 T01 剩余工作，不改派成其他任务，也不因此放行完整 T02 依赖。

## 测试与审核

新增后端 CRUD、AAD 篡改、epoch/revision、权限/CSRF、开关/无主密钥、重复请求、配额、事务失败、旧数据迁移保留、模型状态一致性测试；前端新增 14 个页面行为测试和 3 个请求边界测试。未删除旧测试、修改旧断言或扩大 skip。

专项命令（隔离空数据库/合成环境）：

```sh
RUN_MAIN=true PYTHONPATH=backend:crawler python -m pytest -q backend/api/tests/test_ai_connections.py backend/api/tests/test_provider_credentials.py
cd frontend
npm run test:run -- tests/pages/AIModelSettingsPage.test.tsx tests/services/aiConnectionsApi.test.ts tests/pages/SettingsPage.credentials-recovery.test.tsx tests/pages/SettingsPage.test.tsx tests/App.readOnly.test.tsx
npm run typecheck
npm run lint
```

当前执行容器无 Django/DRF 或项目 node_modules，且 GitHub/npm DNS 不可用：本地完整 pytest/Vitest/typecheck/lint **NOT_RUN**。实际完成 Python compileall 与 TypeScript transpileModule 语法检查，不以此替代类型或行为测试。远端必需 CI 与最终 head/审核结果以 PR 实际回执为准，通过前不得合并。

审核方式为主执行者自检，不是独立 Agent 审核。真实浏览器、真实 Key/厂商、真实数据库、生产发布及最终人工 UAT **NOT_RUN**。此轮与 AG-04 #99 独立交付，不包含 RSS T27 #98。
