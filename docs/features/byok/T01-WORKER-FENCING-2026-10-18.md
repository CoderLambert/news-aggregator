# BYOK T01 · 第 5 批：统一 Worker 凭据撤销围栏

基线：`main@5a2f55e640469fab780c02b246b2ae86d4580323`。复用原 T01 合同，未建立新任务编号。T02/T03 模型和用途绑定尚未交付，个人调用保持 **fail-closed**。

## 审查证据与真实缺口

- `UserAIConnection` 已有 owner、endpoint 版本、credential_epoch/version、启停和墓碑，`ai_connection_views` 的增删改停均通过 owner 行写锁串行化。新建和换 Key 使用 v2 AES-GCM AAD；无旧运行时模型。
- `ai_credentials` 原先有仅包含 owner/UUID/epoch 的临时快照、无锁的请求前密钥读取与有锁的最终提交检查，但没有完整 Worker 队列记录格式和统一 claim/retry 入口。
- `ai_execution.personal_clients_for_user` 在 T02/T03 不存在时拒绝个人模型推理，`ai_gateway` 尚无真实接入者（已有的聊天、研究、翻译、推荐、分类代码只有现存合成测试注入客户端的路径）。**这些现存任务没有新 `UserAIConnection` 模型路由的真实工作链，不得把服务层测试冒充全部 Worker 业务集成。**
- 旧 ChatGPT Subscription 由 `chatgpt_subscription` / `chatgpt_subscription_jobs` 自行执行，不共享个人连接快照，因此不修改其授权链、OAuth、SSE 或账单路径。
- 旧 BYOK 堆叠 PR #33–#45 仅供审查，不直接合并或复活 `UserProviderCredential`。

## 实现合同

`api.services.ai_worker_fencing` 是唯一的未来个人 BYOK 后台消费入口：

1. **enqueue**: `capture_at_enqueue(owner=request.user, connection_id=explicit_id)`；短事务加 owner 锁，校验 active/endpoint/AAD，生成无 Key 的 JSON dict（`schema_version=1`）；不自动选择第一连接。
2. **claim 和 retry**: `check_at_claim(payload, task_owner_id=job.user_id)`；严格检查结构、owner、UUID、epoch、密文版本、provider、端点身份。旧任务不得改写 epoch 恢复。
3. **send**: `dispatch_once(payload, task_owner_id=job.user_id, send=callback)`；短事务内与撤销序列化 admission 和解密；事务释放后，callback 才发送单次请求，不隐式 retry/Key 回退。
4. **在途取消**: `is_revoked(...)` 可用于分块/流消费的尽力协作取消；已经 admission 的调用可能继续到达上游并计费。
5. **final persist**: `commit_result(payload, task_owner_id=job.user_id, persist=short_db_callback)`；owner 行锁+epoch/版本/连接验证与结果写入位于同一事务，撤销后不得出现正式成功结果。业务还需在该事务内检查自身 lease/generation/content version。
6. 个人连接的凭据不进入 SSE、队列载荷、日志、公开 API 或网页，`build_gateway_client` 不接受来自站点 Key 的隐式兜底。

所有工作只在 **T02/T03 能明确选择单个经过校验的 owner 模型连接后**才接入实际业务 Worker；在此之前不开放付费请求或无绑定消费者。不能通过以旧 `credential_fingerprint` 列表选择任意连接替代模型绑定。

## 执行与限制

- `backend/api/tests/test_ai_worker_fencing.py`：覆盖三类撤销、旧队列与重试、在途撤销前获准/提交后禁止、两 Worker 交错执行、跨用户/跨连接、无版本和字段篡改、AEAD 故障、账户停用、原子事务回滚及站点 Key 不回退。
- `backend/api/tests/test_ai_connections.py` 与 `test_chatgpt_subscription.py` 属回归范围；已有 T01 合成订阅测试不应被个人围栏更改。
- 代码路径检查 + Python 编译不能替代 pytest。远端 PR CI 仅在 workflow 实际成功后标 `TESTED`。
- 未创建新 Migration：Worker payload 将由 T02/T03 后续明确绑定任务时写入既有任务模型或经单独迁移审查，不提前加入第二套队列。
- **NOT_RUN**：真实 SDK/Proxy/厂商、真实多实例 PostgreSQL 压测、旧生产数据迁移、生产部署、真实浏览器人工验收。
- **保留边界**：网络层已经发出的请求无法物理撤回；任务结果正确性还依赖业务消费端在同一事务内验证自身 generation/lease/version。

结论：这一批提供可用且可测试的通用安全围栏模块，并保持未接线的个人模型调用 fail-closed。T01 的真实具体业务 Worker 完整接入将在 T02/T03 显式身份绑定后才能端到端验收，不能把本批服务函数存在宣称等于该项全部运行成功。
