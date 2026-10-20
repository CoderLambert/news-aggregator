# RSS 自助订阅与公共频道审核实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用户自行添加 RSS 后即可个人使用，能提交公开推荐；获授权的审核员可审核，超级管理员可直接新增公共频道。

**Architecture:** 复用 Miniflux 物理连接、FeedOperation、ControlWorker 和现有订阅服务。新增版本化业务授权、公共候选/审核事件和显式公共文章成员；个人添加记录从现有用户操作派生。所有网络请求仍通过现有引擎适配器，所有发布和后台提交重查权限及版本。

**Tech Stack:** Django/DRF、SQLite WAL、Miniflux、React/TypeScript、TanStack Query；Python 3.12、Node 22，沿用现有锁文件。

**Spec:** [已确认设计](../specs/2026-10-21-rss-self-service-and-review-design.md)，设计提交 `887194ab1ad4bd2421e824045f5885a90622b73d`；本计划待审阅和选择执行方式。

## Global Constraints

- 在现有隔离目录 `news-aggregator-channel-recovery-20261021` 顺序实现；当前 HEAD 为 `887194ab1ad4bd2421e824045f5885a90622b73d`，产品基线还包含上一轮未提交的核验恢复改动，不能重置、遗漏或拿 HEAD 代替候选摘要。
- 个人可见性不因连接成功而改变；公开频道需要人工授权与技术核验同时满足。
- 超级管理员直接新增公共频道时，登记行为本身构成人工授权，技术核验成功后自动开放订阅。
- 相同 URL 的物理 FeedBinding 继续复用。GET 只读本地状态，不触发采集或审核。
- 所有端点同域 `/api/`，继续 Session、CSRF、read_only 禁写及 `private, no-store`。
- 不设置审核员 `is_staff/is_superuser`；审核员不可审核自己的推荐。撤权、重新授权或版本变化使旧任务失效。
- 公共文章首轮为发布时最近七天内的可验证文章，同时不得早于 binding 原有 `published_since`。
- 不额外抓取正文、不重置全局 cursor、不重新初始化引擎；不清空错误、尝试次数或审计。
- 新增个人连接每账号每小时 20 个不同新增目标、同时最多 5 个未终结目标；个人推荐同时最多 10 条未决定提交、每小时最多 20 次新提交；复用现有订阅和网站发现限额。
- 公共列表每页 25，可选 50；连接批次最多 50；移动浏览器验收宽度为 412 CSS px。
- 本轮交付本地版本，不部署生产，不推送或合并代码，不接入付费服务。原工作目录、实时数据库、凭据、其他服务不作为测试资源。
- schema、迁移、路由和共享 ACL 为单写者；本计划建议当前会话顺序执行，末尾一次独立只读审查。每任务留下审查点；只有检查过精确暂存范围才能提交，禁止 `git add .` 把既有工作一起提交。

## Review Focus

1. 共享 Feed 已有私人历史：公共链接不得绕过成员授权，列表计数、摘要、正文、搜索及 AI/TTS 均守边界；由任务 4 的跨消费者负例固定。
2. 两位用户推荐同一 Feed，其中一位撤回或审核员本人也是提交者：保留另一位有效提交，审核员不得借合并规避自审；由任务 3 固定。
3. 撤权后重新授权，旧请求随后返回：即使当前又有权限，旧授权版本也不能提交；由任务 1、5 固定。
4. 关闭弹窗后取消，迟到连接响应到达，或另一用户仍订阅同一 Feed：不能恢复已取消个人订阅，也不能停掉他人的连接；由任务 2、6 固定。
5. Feed 返回无法确认时间、换 URL 或已有更严格来源合同：不得补入公开历史或以推荐绕过限制；由任务 3、4、8 固定。

## 文件和接口分工

新增后端文件位于 `backend/api/rss/`：`review_models.py` 存储授权/推荐/公开成员，`review_permissions.py` 提供当前业务授权，`additions.py` 处理个人添加记录，`recommendations.py` 处理版本化候选和决定，`public_membership.py` 处理公开文章授权，`review_views.py` 为薄 HTTP 层。现有 subscriptions、operations、admin_verification、control_worker、sync、runtime、access 保持各自职责；不得把所有逻辑塞进一个新视图文件。

新增前端 `rssReviewApi.ts` 为严格 DTO 与请求入口，`RssAdditionsPage`、`RssRecommendationsPage`、`RssReviewersPage` 分别承担个人进度、公开审核和授权管理；复用现有频道核验、modal/drawer 和私有查询清理机制。

后端公共类型放 `review_permissions.py`：不可变 `ReviewAuthority(user_id, instance_uuid, version, superuser)`；业务请求 DTO 为经校验字典，UUID/日期使用既有 API 格式。所有版本均为正整数，历史缺少字段不推断新授权。

## 验证运行器

执行前确认隔离 worktree 无 `.env`；不打印宿主凭据。已只读确认下列 Python 3.12 基础镜像和 Node 22 可用。后端挂载当前隔离源码，SQLite 为容器内合成临时文件，禁止挂载运行站点的数据卷：

```bash
rss_pytest() {
  docker run --rm --network none --entrypoint python \
    -e PYTHONPATH=backend:crawler -e DJANGO_ENV=development \
    -e DJANGO_DB_PATH=/tmp/rss-review-tests.sqlite3 -e RUN_MAIN=true \
    -v "$PWD:/work" -w /work \
    sha256:94620afc312146291920f8e5929b99d3c08638aa075fa575a9aa371d8add84c5 \
    -m pytest -p no:cacheprovider -q "$@"
}
```

前端在 `frontend/` 用 `PATH=/home/lambert/.local/share/mise/installs/node/22.23.3/bin:$PATH npm run ...` 执行；不重新安装共享依赖。已有测试使用 `conftest.py` 合成迁移 DB；新增测试沿用这些 fixture。

---

### Task 1: 持久授权、候选和成员 schema，以及能力返回

**Files:** 新增 `backend/api/rss/review_models.py`、`review_permissions.py`、`backend/api/migrations/0077_rss_self_service_review.py`、`backend/api/tests/rss/test_review_permissions.py`；修改 `backend/api/models.py` 的模块导出、`rss/models.py` 的 SourcePublication 和 `backend/api/views.py` 的认证响应。实际 migration graph 若已有 0077，则使用当前叶节点之后的新编号，不修改已应用迁移。

**Interfaces:** 产出 `review_authority(user) -> ReviewAuthority | None`、`assert_review_authority(user, expected: ReviewAuthority) -> None`、`rss_capabilities(user) -> dict`、`change_reviewer(actor, username: str, active: bool, expected_version: int | None, key: str) -> dict`。Model 为 `RssReviewerGrant`、`RssReviewerEvent`、`PublicFeedCandidate`、`PublicFeedSubmission`、`PublicFeedReviewEvent`、`PublicFeedEntry`；publication 增加默认 False 的 `requires_public_membership`，FeedOperation 增加默认 1 的 `user_intent_version`，候选保存独立的成员同步进度及首轮范围填充状态。

- [ ] **Step 1: 写失败测试。** `test_grant_does_not_change_staff_flags` 断言授予后业务能力为 True 且 staff/superuser 不变；`test_regrant_invalidates_captured_authority` 捕获 A、撤权、重授后断言版本递增，A 校验抛出 PermissionDenied；`test_inactive_and_other_instance_fail_closed` 覆盖禁用账号、实例错配及未知能力；schema 测试断言 binding 唯一候选、成员(source, entry)唯一，已有 publication 新字段为 False。
- [ ] **Step 2: 运行红例。** `rss_pytest backend/api/tests/rss/test_review_permissions.py`；预期新模块/字段缺失导致 FAIL，记录原始失败。
- [ ] **Step 3: 实现 schema 和授权函数。** 授权修改先取得 SQLite 写入预留并校验超级管理员；权限标识用 Django `review_public_rss`，当前有效授权记录及版本为额外必要条件；授予/撤销同步更新权限与只追加审计。候选保存 binding、版本、scope_since、元信息、状态、当前决定及公开 source；事件保存 actor/key/hash/版本，唯一约束防幂等冲突。认证接口统一追加 `rss_capabilities={review_public_rss, manage_rss_reviewers, reviewer_version}`，不破坏原字段。
- [ ] **Step 4: 运行绿例与迁移兼容。** `rss_pytest backend/api/tests/rss/test_review_permissions.py backend/api/tests/rss/test_schema_compatibility.py`；预期全部 PASS。合成 DB 从 0076 正向迁移，验证旧操作、正文与订阅值未变。
- [ ] **Step 5: 留下审查点。** 检查精确 diff；仅可提交此任务新增文件及可独立分离的 hunks，提交信息 `feat: add versioned RSS reviewer authority`。既有核验产品改动不混入本提交。

### Task 2: 个人添加记录、明确失败重试、未知对账与取消

**Files:** 新增 `backend/api/rss/additions.py`、`backend/api/tests/rss/test_additions.py`；修改 `rss/subscriptions.py`、`rss/operations.py`、`rss/subscription_views.py`、`backend/api/urls.py`，按需提取现有核验服务的纯恢复决策，不复制恢复逻辑。

**Interfaces:** 产出 `list_additions(user, *, status: str, page: int, page_size: int) -> dict`、`addition_action(user, operation_id: UUID, *, action: str, expected_version: int, key: str) -> dict`，action 为 `retry/reconcile/cancel`；请求和响应中的 `version` 对应 `user_intent_version`，每次个人动作递增，提交动作时还重查当前状态、原 intent_version、租约及取消标记；动作返回 operation_id/state/version/actions/cooldown_until。

- [ ] **Step 1: 写失败测试。** `test_pending_addition_survives_without_subscription` 断言未成功请求可分页查询且无文章 ACL；`test_cancel_then_late_success_does_not_subscribe` 断言无关系、另一用户关系及有效采集引用不变；`test_unknown_only_reconciles_without_create` 断言 create 调用为 0；`test_subscription_intent_survives_recovery` 断言恢复服务不会覆盖 subscription_request；`test_addition_limits_and_idempotent_replay` 断言第 6 个并行目标/第 21 个每小时目标 429，重放不计额。
- [ ] **Step 2: 运行红例。** `rss_pytest backend/api/tests/rss/test_additions.py`；预期新增接口和服务缺失 FAIL。
- [ ] **Step 3: 实现 owner-scoped 派生记录及动作。** GET 合并保留的订阅请求与成功操作，屏蔽其他 actor/实例；确认失败才创建有关联的新恢复操作，未知只对账，完整保留原审计与个人意图。取消始终通过现有 cancel/reconcile 路径，不能改变别人的任务或共享策略。原子检查新增限额，失败响应含 Retry-After。
- [ ] **Step 4: 运行绿例和订阅恢复回归。** `rss_pytest backend/api/tests/rss/test_additions.py backend/api/tests/rss/test_subscriptions.py backend/api/tests/rss/test_admin_recovery.py backend/api/tests/rss/test_opml_import.py`；预期 PASS，旧空核验请求仍不能创建。
- [ ] **Step 5: 精确 diff/审查点。** 提交范围检查通过后，信息 `feat: persist personal RSS addition progress and recovery`；无法安全拆开的旧 hunks 保留在工作区并在候选清单注明。

### Task 3: 推荐、审核决定及管理员直接登记

**Files:** 新增 `backend/api/rss/recommendations.py`、`review_views.py`、`backend/api/tests/rss/test_recommendations.py`；修改 `rss/admin_verification.py`、`rss/operations.py` 与 `backend/api/urls.py`。

**Interfaces:** 消费任务 1 授权；产出 `submit_recommendation(user, data: dict, key: str) -> dict`、`change_submission(user, submission_id: UUID, data: dict, key: str) -> dict`、`decide_candidate(actor, candidate_id: UUID, data: dict, key: str) -> dict`、`register_public_candidate(actor, data: dict, key: str) -> dict`、`candidate_data(candidate, *, viewer) -> dict`。data 包含 spec 表单字段，写动作包含 expected_version。此任务最多变为 approved，不直接授予文章权限；注册仅接入核验任务，发布由任务 4/5 完成。

- [ ] **Step 1: 写失败测试。** `test_shared_candidate_with_one_withdrawn_submission` 断言只剩另一用户有效提交，且彼此看不到身份；`test_reviewer_cannot_review_any_candidate_they_submitted` 断言合并/撤回不能绕过自审；`test_changed_url_invalidates_approval` 断言新版本须重审且不影响其他用户已提交 URL；`test_restricted_source_and_token_feed_are_rejected` 断言无引擎创建；`test_registration_replay_reuses_candidate_or_existing_public_source` 断言物理 binding 数为 1；驳回必须有原因，旧 key 不同内容 409。
- [ ] **Step 2: 运行红例。** `rss_pytest backend/api/tests/rss/test_recommendations.py`；预期新服务/端点缺失 FAIL。
- [ ] **Step 3: 实现候选和薄视图。** 规范化 URL 后按当前实例/账号/binding 合并；改变 Feed 意味着撤回该用户旧提交并对新 binding 提交，不能修改其他人的共享目标。候选元信息变更递增版本；仅有有效提交才可审核，审核员曾提交过当前候选即不可自审，超级管理员按 spec 特例处理直接登记。推荐限额 10/20、来源策略、owned subscription 和幂等检查在短事务内完成。接入 spec 第 7 节全部推荐和授权 API，按 viewer 安全序列化，不返回完整 private operation。
- [ ] **Step 4: 运行绿例和权限负例。** `rss_pytest backend/api/tests/rss/test_recommendations.py backend/api/tests/rss/test_review_permissions.py backend/api/tests/rss/test_feed_policy.py`；预期 PASS，staff 账号无新权限，跨实例 404，CSRF/read_only 403，GET adapter/publisher 调用为 0。
- [ ] **Step 5: 精确 diff/审查点。** 信息 `feat: add public RSS recommendations and review decisions`；尚未完成发布闭环前保持新入口关闭，不改现场服务。

### Task 4: 显式公共成员与所有阅读消费者的访问边界

**Files:** 新增 `backend/api/rss/public_membership.py`、`backend/api/tests/rss/test_public_membership.py`；修改 `rss/access.py`、`rss/sync.py`、`rss/subscriptions.py`、`services/channel_catalog.py`、`services/stored_readers.py` 及实际依赖者；扩充 `rss/test_access_contract.py`、`rss/test_ai_readers.py`、`rss/test_unified_channels.py`。

**Interfaces:** 产出 `publish_candidate(candidate_id: UUID, expected_version: int) -> dict`、`record_public_entry(candidate_id: UUID, entry_id: int, *, expected_version: int, evidence: dict) -> bool`、`public_entries_for_sources(sources) -> QuerySet`；evidence 必须来自当前引擎 DTO 的身份、可靠发布时间、sanitized 内容摘要和版本，不能由浏览器提供。任务 5 使用前两者，所有查询消费者消费最后一个成员子查询。

- [ ] **Step 1: 写失败测试。** `test_public_link_does_not_grant_unlisted_history` 断言匿名列表/详情/计数/搜索均无未列成员文章；`test_public_member_keeps_private_body_and_ai_history_private` 断言公共端只有已授权摘要，用户私人翻译/研究/TTS正文不可用；`test_unknown_date_and_before_bound_never_become_public` 断言无成员；`test_existing_public_channels_keep_legacy_access` 断言原有 public 行为一致；`test_personal_subscription_prefers_personal_source_after_publication` 断言共用 binding 时不误改个人分组与 ACL。
- [ ] **Step 2: 运行红例。** `rss_pytest backend/api/tests/rss/test_public_membership.py`；预期共享链接现状不能满足显式成员断言，记录 FAIL。
- [ ] **Step 3: 实现公共发布与成员边界。** 发布重查有效批准/授权版本、引擎身份、当前策略及未解决操作；创建独立 source，设置 requires_public_membership=True、scope_since=max(原始采集下界, 发布时刻减七天)。仅已验证 DTO 可生成成员；未知时间不推断公开资格。修改所有基于主 source、binding 或 legacy key 的快捷授权路径，显式公共 source 必须先通过成员查询；成员撤销后列表与正文同步失权。正文默认保持现有 provenance 判定，独立公开来源证据不成立则只摘要，不能改写私人正文来源。初次成员填充失败不扩大 ACL，公共频道显示同步待完成。
- [ ] **Step 4: 运行跨消费者绿例。** `rss_pytest backend/api/tests/rss/test_public_membership.py backend/api/tests/rss/test_access_contract.py backend/api/tests/rss/test_ai_readers.py backend/api/tests/rss/test_unified_channels.py backend/api/tests/test_tts_endpoint.py`；沿调用链补充实际的搜索/向量/导出负例，相关入口不存在则记录已搜索文件与 NOT_APPLICABLE，不新建无关功能；预期所有授权负例 PASS。
- [ ] **Step 5: 精确 diff/审查点。** 信息 `feat: fence public RSS articles with explicit membership`；这是必须审阅的安全边界，不以 UI 测试替代。

### Task 5: 后台核验权限、候选引用与自动发布闭环

**Files:** 修改 `rss/control_worker.py`、`rss/admin_verification.py`、`rss/operations.py`、`rss/runtime.py`、`rss/reconciliation.py`，扩充 `rss/test_control_worker.py`、`rss/test_admin_recovery.py`；新增 `backend/api/tests/rss/test_review_worker.py`。

**Interfaces:** 从现有 `_request_binding` 提取 `request_verification(binding, *, actor, key: str, recover: bool, target: dict) -> FeedOperation`；target 为不可混淆的 `{kind: public_source|public_candidate|personal_addition, id, version}`，个人任务必须保留 subscription_request。公开管理任务捕获任务 1 ReviewAuthority；产出 `process_approved_candidates(*, limit: int = 25) -> dict`，由现有 RSS Worker 有界执行，调用任务 4 发布和成员生成。

- [ ] **Step 1: 写失败测试。** `test_revoked_regranted_authority_cannot_commit_old_response`、`test_both_orders_of_approval_and_connection_publish_once`、`test_candidate_change_or_cancel_during_network_fences_publish`；断言 stale 任务无新 public source/member，超时仍 unknown，远端仅创建一次；`test_bounded_initial_members_read_uses_engine_storage_only` 断言不调用 publisher/body_refetch/init，scope 与 cursor 不变；`test_unapproved_candidate_is_not_a_collection_reference` 断言仅推荐不会启动采集。
- [ ] **Step 2: 运行红例。** `rss_pytest backend/api/tests/rss/test_review_worker.py`；预期现有 superuser-only 检查或候选引用缺失导致 FAIL。
- [ ] **Step 3: 实现统一权限及生命周期。** claim/send/commit 重查 actor、授权版本、目标版本和原有 lease/identity/policy/cancel fences；不同 target 的权限不能互换，个人操作不能提交 public 发布。已批准候选构成有效采集引用，撤回/撤权后按剩余订阅引用重新计算，不盲停共享 Feed。引擎成功后尝试发布，人工通过时也尝试发布；初次范围填充从引擎已存 entries 有界读取并带独立进度，避免重置同步 cursor。未批准、权限撤销和 published 状态不再重复推进；429/超时沿用现有恢复规则。
- [ ] **Step 4: 运行绿例。** `rss_pytest backend/api/tests/rss/test_review_worker.py backend/api/tests/rss/test_control_worker.py backend/api/tests/rss/test_admin_recovery.py backend/api/tests/rss/test_sync_reconciliation.py backend/api/tests/rss/test_owner_fencing.py`；预期 PASS。原有 admin 空请求只对账、已有七天边界及迟到正文围栏均保持。
- [ ] **Step 5: 精确 diff/审查点。** 信息 `feat: execute RSS reviews with current authority and safe publication`；迁移和新 Worker 未安装前不得打开新动作。

### Task 6: 用户添加记录与推荐的完整界面

**Files:** 新增 `frontend/src/services/rssReviewApi.ts`、`frontend/src/pages/RssAdditionsPage.tsx`、`frontend/src/features/rss/RecommendFeedDialog.tsx`、对应 `frontend/tests/services/rssReviewApi.test.ts`、`tests/pages/RssAdditionsPage.test.tsx`；修改 `DiscoverDialog.tsx`、`ChannelWorkspace.tsx`、`ChannelDetailWorkspace.tsx`、`App.tsx` 及导航。

**Interfaces:** rssReviewApi 导出 `fetchAdditions(search, signal?)`、`actOnAddition(viewer, id, action, version, key)`、`fetchMyRecommendations(search, signal?)`、`submitRecommendation(viewer, data, key)`、`changeRecommendation(viewer, id, data, key)`；都经 workspaceRequest 和严格 parser。统一 query key 前缀为 `['private','rss-review',viewer]`；状态类型使用任务 2/3 的 DTO，不复制 server state 到 Zustand。

- [ ] **Step 1: 写失败测试。** 添加未成功操作在关闭/刷新后仍显示；明确失败提供 retry、unknown 只提供 reconcile；取消后迟到 mutation 不恢复 UI；切换账号不显示上一用户 Feed；推荐对话框明确个人与公共范围；解析缺失能力/非法版本 fail-closed；分页和筛选经 URL 返回保留。
- [ ] **Step 2: 运行红例。** `npm run test:run -- tests/pages/RssAdditionsPage.test.tsx tests/services/rssReviewApi.test.ts`；预期新模块缺失 FAIL。
- [ ] **Step 3: 实现个人界面。** 路由 `/channels/additions` 提供“添加记录/我的推荐”，原“添加订阅”成功提交后可跳往记录。已有个人频道详情增加推荐入口；对话框包含表单、公开范围确认和可访问错误。冷却直接倒计时，连接状态与文章同步分开显示；查询和动作响应均绑定 viewer，移动布局复用现有 modal。
- [ ] **Step 4: 运行绿例。** `npm run test:run -- tests/pages/RssAdditionsPage.test.tsx tests/services/rssReviewApi.test.ts tests/features/rss/DiscoverDialog.test.tsx tests/context/AuthContext.races.test.tsx`；预期 PASS。
- [ ] **Step 5: 精确 diff/审查点。** 信息 `feat: make personal RSS progress and recommendations accessible`；不引入新 UI 框架或依赖。

### Task 7: 公开审核、管理员新增与审核员授权界面

**Files:** 新增 `frontend/src/components/admin/RssReviewerRoute.tsx`、`pages/admin/RssRecommendationsPage.tsx`、`pages/admin/RssReviewersPage.tsx`、对应页面测试；修改 `AuthContext.tsx`、`services/api.ts` 的 auth DTO、`rssReviewApi.ts`、`App.tsx`、`Header.tsx`、`AdminLayout.tsx`、`RssChannelsPage.tsx`。

**Interfaces:** AuthUser 增加 `rssCapabilities: {reviewPublicRss:boolean; manageReviewers:boolean; reviewerVersion:number|null}`，老响应缺失时均无新增权限。服务导出 `fetchRecommendations(search, signal?)`、`fetchRecommendation(id, signal?)`、`decideRecommendation(viewer,id,data,key)`、`registerPublicSource(viewer,data,key)`、`fetchReviewers(signal?)`、`setReviewer(viewer,data,key)`、`revokeReviewer(viewer,id,version,key)`；审核 key 在任务 6 前缀后增加 reviewerVersion。

- [ ] **Step 1: 写失败测试。** 普通用户不能进审核页，审核员可进入但看不到运行概览/索引/授权入口，superuser 可授权；全局 admin 能力关闭但 accounts 可用时审核员仍能进入合法审核入口；本人推荐不能通过；权限刷新清除已选对象和旧结果；直接新增重复提交复用任务；API 未知能力不赋权；抽屉 Escape 恢复焦点且 412px 无溢出。
- [ ] **Step 2: 运行红例。** `npm run test:run -- tests/pages/RssRecommendationsPage.test.tsx tests/pages/RssReviewersPage.test.tsx tests/pages/RssChannelsPage.test.tsx`；预期新增页面和能力缺失 FAIL。
- [ ] **Step 3: 实现三个入口。** `/admin/rss/recommendations` 走账号功能和业务审核权限，`/admin/rss/channels` 复用审核员门禁；运行概览与授权管理保持 superuser。AdminLayout 根据业务能力过滤导航和说明。核验页新增管理员表单，审核页展示人工与技术两个状态；授权页精确用户名查找、确认、授予和撤销，不暴露邮箱。列表25/50、URL条件、安全预览、错误恢复、加载/空状态和全屏移动详情沿既有模式。
- [ ] **Step 4: 运行绿例与静态检查。** 执行上述页面测试及 AuthContext、Header、FeatureRoute 受影响测试，再 `npm run typecheck`、`npm run lint`；预期无新错误。既有 warning 单独记录，不能当作本次已修复。
- [ ] **Step 5: 精确 diff/审查点。** 信息 `feat: add RSS reviewer workspace and public channel intake`；后端授权为实际权限边界，前端隐藏不能替代负例。

### Task 8: 整体回归、隔离真实引擎、三角色浏览器与本地交付

**Files:** 新增 `tests/rss_engine_contract/live_self_service_review.py`、`docs/verification/rss-self-service-review-2026-10-21.md` 及其证据目录；按需复用 `tests/rss_engine_contract/recovery_lab/`，遵守 `scripts/deploy/AGENTS.md` 后才修改运行包装器。不得覆盖上一轮证据。

**Interfaces:** 消费前七任务全部 HTTP/DTO/权限和 Worker；输出带 head/base/dirty-digest、镜像摘要、测试日志、逐角色实际结果、未运行项和回退步骤的交付记录。

- [ ] **Step 1: 写集成红例。** 普通用户 A 添加合成 RSS 得到个人文章；B/匿名不可读；A 推荐，独立审核员通过，复用一个 engine Feed；公共仅有范围内成员且无私人 AI 结果。另测 parser failure、未知/取消、撤权迟到响应、旧时间和受限来源。显式 opt-in，专用 Compose project/端口/合成数据库，初始运行记录未实现路径的 FAIL。
- [ ] **Step 2: 执行整体离线门禁。** `rss_pytest backend/api/tests/rss backend/api/tests/test_channels.py backend/api/tests/test_smart_channel_workspace.py backend/api/tests/test_tts_endpoint.py scripts/deploy/tests/test_rss_channel_recovery.py`；根据实际存储阅读消费者添加定向门禁。前端 `npm run test:run`、`npm run typecheck`、`npm run lint`、`npm run build`；全部记录实际 exit/status，不预设通过数量。出现新失败先定位再修改，不削弱原断言。
- [ ] **Step 3: 执行真实隔离引擎与浏览器。** 复用真实 Miniflux lab 的 TLS 合成 Feed，先通过上述三角色集成场景；再在隔离应用浏览器验证桌面和412 CSS px、键盘/焦点、搜索分页返回、账号切换、限额和冷却。合成账号之间切换，不登出用户正在使用的会话；截图及引擎调用计数保存到证据目录。
- [ ] **Step 4: 独立只读审查与受影响复验。** 使用 executing-plans 要求的最终 reviewer，提供整个候选 diff（含上一轮未提交改动）和 spec/plan，重点检查公共成员绕过、Worker撤权、自审/重复提交和恢复授权。修复必要问题后仅重跑受影响测试，再构建最终镜像并核对候选摘要；没有独立审查工具则准确记录 NOT_RUN。
- [ ] **Step 5: 安装本地候选并记录交付。** 在当前用户授权的本地环境范围内，先明确数据备份及迁移边界；不复制真数据库进测试。先迁移、再部署同版本 app/Worker，最后启用入口；核对原账号、订阅、旧正文、Feed身份和初始化下界未变。不额外重启 Miniflux，不把测试审核员授予真实账号。运行用户可见最小健康检查，保留实际逐来源结果；CI/生产不运行分别写 NOT_RUN。若迁移或本地资源范围无法安全确认，只完成可审阅候选并明确该项 BLOCKED，不擅用其他实例。

## 实施结果

已于本地完成任务1–8。详见 [候选与验收记录](../../verification/rss-self-service-review-2026-10-21.md)。上述步骤保留原计划勾选状态作为原始任务说明；实际执行与未运行项以验收记录和执行台账为准。产品提交因保留上一轮重叠改动而延后；首次 live RED 未运行，离线 RED 与最终真实引擎通过分别记录。

## 自查与执行交接

- spec 第 1–3 节映射任务 2、3、5、6、7；第 4–5 节映射任务 1、3、5；第 6 节映射任务 4、5、8；第 7–8 节映射任务 1–3、6、7；第 9–10 节映射任务 8 和全局约束。
- 五项 Review Focus 均有对应失败测试；服务签名、DTO 版本和页面消费在任务间一致。新增授权类型不取代原 session，成员授权不替代原正文来源围栏。
- 只新增本计划、记录设计已确认；本步不运行产品测试，不修改产品代码或现场服务。实施方法和计划审阅确认后才开始 Task 1。
