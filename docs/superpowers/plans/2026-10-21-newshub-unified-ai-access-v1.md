# NewsHub 统一模型服务逐任务实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement task-by-task. Checkbox steps track delivery and evidence.

**Goal:** 复用 BYOK/LiteLLM 完成受信云与本地模型问答、翻译及能力验证。
**Architecture:** 管理员 manifest 固定端点、协议、认证、网络和准入；同一映射供后端与 Proxy。保留原始完成证据与 owner/epoch/content/worker 围栏，逐步扩展业务。
**Tech stack:** Python 3.12、Django、LiteLLM 1.105.0、Node 22、React/TypeScript。
**Spec:** `docs/superpowers/specs/2026-10-21-newshub-unified-ai-access-v1-design.md`

## Global constraints

- 保留旧 AAD、旧 Key 模式创建 digest、DeepSeek 与 Subscription 行为；无 Key 绝不存假 Key。
- 最多两个独立写入目标；共享 schema/routes/migration 单写者。本计划顺序实施。
- 所有测试在无 .env 的 worktree，临时 DB/ports/Proxy；不读生产凭据。
- 普通用户不传 URL/headers；无收费切换、fallback 或不明结果自动 retry。
- 真实收费服务、生产和合并未授权；指定 Ollama 与合成结果分开报告。

## Review focus

- None 模式伪造为收费连接：Task 2 检查 Key replacement、snapshot.auth_mode 与 profile 准入。
- 同版端点修改：Task 1/3 验证内容摘要改变 alias，使既有 receipt/snapshot 拒绝。
- 带命名空间与标签模型：Task 1/3 验证模型完整往返且不能覆盖 endpoint。
- 原始 EOF 被 LiteLLM 合成 stop：Task 3/4 用真实 Proxy 的缺 stop/DONE/error/length 负控。
- 取消或退出账号后晚结果：Task 4/5 验证 terminal commit fence 和 viewer key。

### Task 1: 服务端受信端点目录与一致路由

**Files:** Create `backend/api/services/ai_endpoint_profiles.py`, `backend/api/tests/test_ai_endpoint_profiles.py`; modify `ai_registry.py`, `ai_model_registry.py`, `settings.py`；后续 Proxy 挂载同一纯 Python 文件。
**Interfaces:** `load_endpoint_profiles(path) -> tuple[dict,...]` 校验管理员 manifest；`profile_route_prefix(connection) -> str|None` 使用内容摘要前缀；`profile_allows_user(profile,user_id) -> bool`；目录只提供无敏感元数据。

- [ ] 写负面测试：重复 ID/版本、非法 URL、未批准私网、无用户范围、非法 auth/protocol、模型 URL/转义/..、命名空间/标签、同版内容变更。
- [ ] 运行 `env -i PATH=/usr/bin:/bin PYTHONPATH=backend:crawler RUN_MAIN=true .venv-ai/bin/python -m pytest -q backend/api/tests/test_ai_endpoint_profiles.py`，先确认缺失行为 FAIL。
- [ ] 实现纯校验及 registry 消费，不改变默认旧路由，不默认发布 local endpoint。
- [ ] 上述测试与 `test_ai_models_t02.py` 通过后 scoped commit。

### Task 2: T01 无 Key 身份与旧兼容

**Files:** Modify `ai_connection_models.py`, `ai_connection_views.py`, `ai_credentials.py`, `ai_worker_fencing.py`, `ai_task_preferences.py`；Create forward migration after `0079`, `test_ai_connections_auth_modes.py`。
**Interfaces:** `ConnectionSnapshot.auth_mode='api_key'`；`execution_credential(connection) -> str|None`；`read_execution_credential(snapshot) -> str|None`；旧快照缺 auth_mode 仅解释为 api_key。CRUD 接收 auth_mode，按可信 profile 校验。

- [ ] 写测试：none 创建不存密文、密钥字段拒绝、API key 必填、none 不可换 Key、owner/停用/重新启用/版本改变阻止旧快照、旧 digest/AAD 不变、未知模式拒绝。
- [ ] 运行新测试确认预期 FAIL；实现加法迁移和 admission，不在 decrypt 中容忍损坏密文。
- [ ] 运行新测试及 `test_ai_connections.py test_ai_worker_fencing.py test_ai_task_preferences.py`；迁移 `makemigrations --check`；scoped commit。

### Task 3: Proxy 配置生成、连接层出站与原始终态

**Files:** Modify `ops/shared-litellm-proxy/provider_key_guard.py`, config/compose/entrypoint；Create manifest generator、出站策略模块与 tests；extend `tools/byok_t00_probe`。
**Interfaces:** Task 1 manifest → 静态 route 配置；ProviderKeyGuard 仅接受批准路由的 Key/none；校验 HTTP 连接目标；逐协议 terminal provenance。

- [ ] 先测请求级 api_base/headers/proxy/fallback/retry 覆盖、DNS 重绑定、redirect、metadata、private、none 升级、站点 Key 继承，上游应 0 次。
- [ ] 对 openai-compatible 原始完整/EOF/error/length/duplicate/DONE 各场景做真实 LiteLLM 探针，native 协议沿现有原生证据。
- [ ] 实现与跑 `python -m unittest discover -s ops/shared-litellm-proxy/tests -p 'test_*.py'`；真实 Proxy probe 报告逐项读取；scoped commit。

### Task 4: 能力证明与业务消费者贯通

**Files:** Modify `ai_gateway.py`, `ai_model_probe.py`, `ai_model_capabilities.py`, `ai_model_views.py`, `ai_article_chat.py`, `ai_private_translation.py`, `research/byok_execution.py`, `channel_ai.py`, `ai_usage.py` 及对应测试。
**Interfaces:** Task 1/3 route descriptor/protocol → 实际调用；Key/None → Proxy；能力/adapter/route 绑定；`delivery_mode` 与稳定安全 error code。

- [ ] 写云/compatible Key/none 问答与分段翻译回归、相同文章切换、raw terminal 失败不保存、取消/撤销 late commit 拒绝、tools 不推断研究、usage owner/no-secret。
- [ ] 逐组 RED→实现→GREEN，移除所有业务 Flash 常量 gate，改为受信完成合同；保留 DeepSeek 专属 thinking 参数仅用于其 route。
- [ ] 运行 T02/T03/T04/T05/research/channel/usage 影响测试，再 Django→SDK→真实 Proxy→合成上游端到端；scoped commit。

### Task 5: 连接、模型、用途和诊断界面

**Files:** Modify `frontend/src/services/aiConnectionsApi.ts`, `AIModelSettingsPage.tsx`, `AIModelsManager.tsx`, `AITaskPreferencesSection.tsx` 及镜像测试；backend 模型发现与诊断 endpoint 沿原权限。
**Interfaces:** 只读 auth_modes/protocol/data_destination、delivery_mode、stream_verified、安全错误；新连接 api_key 可选但仅 none；显式发现不推理。

- [ ] 先写 Key/none 切换清空输入、未授权 profile 不出现、未知状态不变通过、目录失败可手填、保存无推理、退出后的 stale response 回归。
- [ ] 实现 UI，不在持久缓存保留 Key；费用未知不显示零，云/服务器数据目的地明确。
- [ ] Node 22 执行 typecheck、lint、AI settings/API/消费者 Vitest、build；浏览器检查宽/窄屏和键盘；scoped commit。

### Task 6: 整体证据与指定模型验收

**Files:** Extend end-to-end fixtures/tests 与 `docs/superpowers/reports/2026-10-21-newshub-unified-ai-access-v1.md`。
**Interfaces:** 全链用户→连接→模型→用途→快照→Proxy→完成→持久化；每条 F/S/R 关联最终证据。

- [ ] 执行适用后端跨三个测试根、前端与真实 Proxy 合成矩阵；保留命令/exit/SHA/skip 原始结果。
- [ ] 仅对用户指定 Ollama 模型做隔离受控真实调用，Key 从不入日志；问答、翻译、tools 各自记录；其他供应商真实调用 NOT_RUN。
- [ ] fresh independent reviewer 审整个 base→head+dirty diff，修复重要问题并做定向回归；核对所有要求，不以部分绿色宣称全部完成。
- [ ] 按授权交付本地 scoped commits；PR 若创建必须 Draft，Ready/CI/merge/production 状态真实报告；未授权不合并部署。
