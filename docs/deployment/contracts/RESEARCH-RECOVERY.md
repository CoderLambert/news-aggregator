# Research 研究任务恢复与 SSE 资源合同

## Task ID / Depends on / Base HEAD / Goal

- Task ID：`G3-RESEARCH-RECOVERY`。
- Depends on：NH-PUB-08 安全骨架；G2 业务源码；翻译任务 `0030`；ADR-025/027。翻译功能实现已完成，隔离验证与 High 审核因用户要求先开发功能而延后；研究迁移必须串行依赖 `0030`。
- Base HEAD：`9a48385 docs: record verified progress and next-window handoff` 加当前工作树已完成的翻译恢复源码。不得重置、覆盖或提交任何现有改动。
- Goal：把现有 ResearchSession 的研究执行改为 owner 私有、可持久重连和取消的 ResearchRun；在下一模型/工具网络及持久化动作前执行取消/租约/owner/session fence；断开 SSE 只停止接收、不取消 worker。生产网站研究在授权/协议缺失时 fail-closed。复用现有研究循环与现有双线程执行器；为所有 AI SSE 连接提供有界 Waitress 资源保护，保证前台新闻请求不被 SSE 占满。不得开发收费、日额度、Token预算或站点付费 Provider。

## Owned files / Read-only references

实施只可改动：

- `backend/api/models.py`：仅新增 `ResearchRun`、`ResearchRunEvent`。
- 新 `backend/api/migrations/0031_research_run_recovery.py`：只建研究运行/事件表，依赖 `0030_subscription_translation_task`。
- `backend/api/services/chatgpt_subscription_jobs.py`：仅暴露复用其既有双线程 executor 的窄 `submit_background_task` 入口，不创建第二个 executor、不改变翻译任务生命周期。
- `backend/api/services/research/job_manager.py`、`backend/api/services/research/agent_loop.py`、`backend/api/services/research/tools.py`、`backend/api/research_views.py`、`backend/api/urls.py`。
- `backend/api/services/research/__init__.py`：只更新公开导出以匹配新的 durable `job_manager` API。
- 新 `backend/api/sse_resources.py`；必要的 `backend/api/middleware.py`；`backend/api/public_policy.py`；`backend/newsaggregator/settings.py` 仅为注册资源中间件。
- 新 `backend/api/tests/test_research_recovery.py`；必要的兼容更新仅限 `backend/api/tests/test_research_csrf.py`、`backend/api/tests/test_chatgpt_subscription.py`、`backend/api/tests/test_subscription_recovery.py`。
- 前端：`frontend/src/services/api.ts`、`frontend/src/services/researchApi.ts`、`frontend/src/services/newsWorkflowApi.ts`、`frontend/src/types/research.ts`、`frontend/src/hooks/useResearch.ts`、`frontend/src/hooks/useTranslation.ts`、`frontend/src/utils/sse.ts`、`frontend/src/pages/NewsDetail.tsx`、`frontend/src/components/research/ResearchPanel.tsx`、`frontend/src/components/research/ResearchInput.tsx`、`frontend/src/components/news-detail/FullContentSection.tsx`；现有相关 `frontend/tests/hooks/useResearch.test.jsx`、`useTranslation.test.jsx`、`frontend/tests/services/api.test.js`。
- 新 `docs/deployment/research-recovery.md`；必要时更新 `docs/deployment/ARCHITECTURE.md`、`docs/deployment/TASKS.md`、`docs/deployment/PROGRESS.md`，并保持 R5 实际 FAIL 和翻译测试/审核未运行的证据准确。

只读参考：ADR-025/027、完整 `SUBSCRIPTION-TRANSLATION-RECOVERY.md`、`backend/api/services/shared_translations.py`、现有 research views/job_manager/agent_loop/tools、`llm_translator.get_clients`、`public_policy.py`、`start_waitress.py`/Waitress 配置、前端 `useResearch`/`useTranslation`/SSE parser 与 G2 owner isolation。禁止扩大拥有文件。

## Decision frozen

1. **持久模型**：`ResearchRun` UUID 主键，user 与 ResearchSession 外键级联；`idempotency_key`、请求摘要 SHA-256、状态 `queued|running|succeeded|failed|cancelled|interrupted`、随机 `run_token`、心跳/租约、最近事件序号/累计 wire bytes、安全 `error_code`/`error_message`、排队/开始/结束/更新时间。请求摘要覆盖 query、local_only、session（新建会话时使用稳定的 create 身份），不得保存 API key 或 raw exception。`(user,idempotency_key)` 唯一；每个 session 至多一个 queued/running run（条件唯一约束）。`ResearchRunEvent` 外键级联，保存 sequence、原有 SSE type/data、wire byte 数及时间，`(run,sequence)` 唯一。DTO/SSE 不返回 `run_token`、凭据或内部路径。
2. **Migration**：0031 依赖 0030，只建新表/索引/约束，不重写或搬迁旧 ResearchSession/ResearchSearchResult，不迁移真实数据库、不提供逆迁 0027；用户删 session 时通过同事务先 fence/cancel 当前 run，再由既有级联删除任务与事件。
3. **幂等/状态**：POST create/chat 携带 `Idempotency-Key`（1–64 个可打印 ASCII 字符；旧客户端缺省时服务端生成 UUID）。同用户 key + 相同请求摘要返回原 run/session 并重连；同 key 不同摘要为 409 `idempotency_key_reused`；同 session 另一 key 有 active run 时 409 `research_run_active`，不静默把不同请求附到旧任务。failed/interrupted/cancelled 不自动重试；用户明确 POST 新 key 才能新建下一轮。GET 只读状态/持久事件，不创建或调度研究。
4. **执行与租约**：worker 复用 `chatgpt_subscription_jobs` 的同一个 `ThreadPoolExecutor(max_workers=2)`；不另建 pool、任务平台或通用队列。单进程最多两个已接纳的研究 run（运行/已提交等待槽位合计），满时在创建 session/run 前返回 503 `research_capacity_reached` + `Retry-After: 1`。DB worker 开始时条件 CAS `queued -> running`，生成 run_token，60 秒租约、20 秒心跳；心跳只可在 token/status/租约仍有效时延长。跨进程唯一约束/CAS保证同一 idempotency 不重复执行。租约失效的 running 一律转 `interrupted`，不自动回放已开始的模型/工具操作；queued 仅由相同 key 的显式 POST 再次 claim。进程内事件/任务注册表仅为唤醒优化，数据库为唯一事实源。
5. **SQLite 与取消 fence**：所有 provider/tool 调用之前、每次 provider retry 之前、tool 执行之前/完成后以及每次 session/search-result/event 保存之前检查 owner.is_active、session仍存在且归属相同、run状态/token/租约。cancel/session delete/inactive owner/租约失效后下一次网络与写入必须被拒绝；正在进行的单次 HTTP 只能等现有 timeout，之后不得重试/调用下一工具/保存。所有完成/错误/取消状态和完整 `ResearchSession.messages` 最终写入使用同事务，首个 DB 写是对 run 的条件 UPDATE CAS，之后再保存 session/messages；不得持 SQLite 写锁跨网络 I/O。事件 append 同样先条件 CAS 获取写锁，再写序号/事件。
6. **运行循环**：`run_agent_loop` 保持原工具、prompt、开发 Provider 顺序和响应兼容；增加可选 execution guard 与受控完成持久化回调。worker 调用前后及每个模型重试、每个工具调用前后做 guard；tools 保存 ResearchSearchResult 前也必须 fence。最终成功时原有完整历史与 run `succeeded` 同事务提交后才发 complete；迟到 worker不得覆盖 cancelled/interrupted/新 run。异常只映射固定安全码/消息，不把 provider 原始异常放入 API、事件或新日志。
7. **事件/SSE 上限**：复用原 `data: JSON\n\n` schema。按完整 UTF-8 wire record（含 `data:`、换行）严格限制 16 KiB；累计持久事件 wire bytes 最大 2 MiB；research `text_delta` 按 Unicode 边界分片，每片正文最多 2048 UTF-8 bytes。超限安全结束为 failed，不截断成功的完整 ResearchSession 结果；完整回答仍从 owner session GET 读取。SSE 前端解析 buffer 最大 32 KiB。持久 sequence 用于稳定回放；GET 重连从 sequence 1 回放同一 run，前端重置本地 task 后重建进度，避免重复追加。
8. **API**：保留 `POST /api/research/`、`POST /api/research/<session>/chat/`、`GET /api/research/<session>/stream/` 路径。create/chat 必须先运行 production policy，用户归属/幂等校验后才创建数据。SSE 响应返回 `Session-ID`（create）和 `Run-ID`，每个 SSE 与 owner response 固定 `Cache-Control: no-store`、`X-Accel-Buffering: no`。GET stream owner-only；active run 返回完整持久事件 SSE，非 active 返回 session DTO 加 safe latest-run state。新增 `POST /api/research/<session>/cancel/`，body `{run_id}`；仅取消该用户/该 session 的精确当前 run，queued/running -> cancelled，重复终态幂等，过期/不匹配 run_id 为 409 `research_run_changed`，跨用户仍404，标准 SessionAuthentication/CSRF。
9. **生产 fail-closed**：保留现有 `PUBLIC_AI_ENABLED=0` 在 view 前返回的 403。若 `DJANGO_ENV=production` 且开关显式启用，create/chat/worker 仍须在任何 session/run 写入、模型/工具网络前返回 503 `hosted_integration_unapproved`；不得读取 Site API key 作为替代，不加 fake approval env。开发模式保留原 provider 行为。所有验收 Fake；真实 OAuth/模型调用 `NOT_RUN` / `EXTERNAL_BLOCKED`。
10. **SSE 线程资源**：通过小型全局 middleware/lease，只针对 `news-chat`、`news-translate`、`research-create`、`research-chat`、`research-stream` 的 event-stream 行为，限制同一 app process 同时最多 2 个 SSE request threads。要在 view 执行前取得 slot，满时返回 503 `sse_capacity_reached`、`Retry-After: 1`，不得因此创建 session/task；stream close/异常/非 SSE response 必须释放 slot，包括未开始迭代的 response。SSE disconnect 只释放连接 slot，不取消后台任务。TTS `audio/mpeg` 不在此 SSE gate。默认 Waitress 4 threads 时两条 SSE 仍至少留两条请求线程供新闻浏览。该连接并发限制仅用于运行资源安全，不是用户用量/任务/Token额度。
11. **前端**：研究每次用户明确 create/chat 生成 UUID 幂等 key，重复连接复用 key；保存安全、按 viewer/session 隔离的恢复指针；POST response header 取 Session-ID/Run-ID；显式 Cancel 调新 cancel API，再 abort SSE；导航/关闭/网络断开只 abort stream，不取消后台任务；刷新/重选 session GET stream 后重放同 run 事件，只有用户明确 retry 才 POST 新 key。全文翻译解析 `Job-ID` 并持久记录 `(viewer,news,job_id)`；owner GET 恢复进度/结果，active refresh 用现有 POST 同 key attach；显式 Stop 先 GET generation 再 POST cancel，取消与断线分离，页面切换不隐式取消。身份切换必须按现有 owner key 隔离恢复信息并清除旧用户指针。不可泄露 token。

## Implementation steps

1. 新增 run/event schema 与 forward-only 0031 migration；复用已冻结 0030。
2. 将既有双线程 executor 暴露为窄提交 helper；实现唯一 idempotency、CAS claim、租约/heartbeat、事件持久化与只读跨进程 attach。
3. 给 research loop/tools 加 guard 与同事务最终保存；实现过期/取消/owner/session fence 与安全状态。
4. 保留原 research URL，增加精确 cancel 路由、生产拒绝、owner CSRF/no-store；SSE重连回放持久事件。
5. 增加全局限定路由 SSE 两槽 middleware，覆盖 translation/chat/research，确保异常/关闭/非stream响应释放；不触碰真实服务器。
6. 更新 research/translation API client 与 hooks：幂等、显式服务端取消、断开不取消、刷新/重选重连；按viewer隔离恢复状态。
7. 新增Fake-only回归与文档；本批只完成开发，不运行任何测试/migration check/build/lint/formatter，待所有功能开发后统一隔离验证。

## Acceptance tests（当前用户要求暂缓运行）

- `PYTHONPATH=backend:crawler RUN_MAIN=true backend/venv/bin/python -m pytest backend/api/tests/test_research_recovery.py backend/api/tests/test_research_csrf.py backend/api/tests/test_public_policy.py -q`：单key并发最多一个Fake loop；新进程/清空注册表后owner GET可回放事件；完成后messages与run成功原子；断开SSE不cancel；queued显式attach仅跑一次；running过期 -> interrupted不自动重跑；新key明确retry才执行；cancel/inactive/delete/source session失效后无下一模型/工具I/O与存储；owner/匿名/跨用户/CSRF；production enable时503且session/run/provider计数皆0，AI开关0仍先403。
- 同批：同命令附加 `backend/api/tests/test_subscription_recovery.py backend/api/tests/test_chatgpt_subscription.py backend/api/tests/test_shared_translations.py` 保证翻译切片未回归。
- 前端：`cd frontend && npm run test:run -- tests/hooks/useResearch.test.jsx tests/hooks/useTranslation.test.jsx tests/services/api.test.js`，验证明确cancel发API、navigation/disconnect仅断流、刷新/切换按owner恢复、terminal结果落入session/文章、错用户缓存隔离、重复请求幂等key一致、SSE parser 32KiB边界。
- 隔离 migration：从排除 `backend/db.sqlite3*` 与所有 `.env*` 的固定源 archive + owned overlay，用 env-i/独立0700 HOME/TMPDIR/绝对临时 SQLite/绝对venv Python 运行 fresh forward `migrate`、`makemigrations --check --dry-run`；不可操作真实 DB、不得逆迁。
- SSE 资源：Fake/isolated client同时占用2个被限流SSE时第三个在 view/job创建前503；关闭/异常/未迭代/JSON response释放slot；两条SSE期间匿名新闻GET仍有可用Waitress线程。不得用运行真实 Provider 代替。

## Negative tests

无 Idempotency-Key旧客户端兼容；重复 key 不同内容；同 session 不同 key 并发；匿名/跨用户 GET/cancel；无CSRF cancel；cancel/删除/owner失活发生在模型返回、工具网络、工具存储、final CAS各间隙；进程在run claim前后中断；迟到老 run token；expired lease；SSE事件大小/累计大小上界；满SSE容量不得创建run；伪造 production approval env 无效；production不能调用 `get_clients`、tool、也不创建记录；event/DTO/log不含token/raw provider error。所有上游均Fake。

## Forbidden / Return format

禁止：运行测试/migration/build/lint/formatter直到用户再次允许并且功能开发完成；访问真实 Provider/OAuth/网站；部署/push/merge/commit；读取、hash、复制、迁移、暂存或删除 `backend/db.sqlite3*`、WAL/SHM、任何 `.env*`/真实key；触碰 `127.0.0.1:9527`、系统CA/hosts；宽泛Docker清理；新增费用/预算/日额度/Token额度/次数限制、站点收费fallback、新通用队列、真实网站授权或虚假批准配置；改动Owned之外文件；把已有中断重试自动化。

Return：修改路径、状态机/路由/资源限制摘要、迁移依赖及用户DB未操作证明、Fake-only coverage 新增范围（不运行）、未运行验证、真实网站外部阻塞。不得提交代码。
