# 新订阅自动整理与分组操作改进实施计划

> 执行：superpowers:subagent-driven-development；两条独立写入目标（后端 / 前端），共享契约由主 Agent 固定。用户已批准设计并要求开始开发。

Goal: 以严格两级“根分类 → 子分组 → 频道”整理个人订阅；可靠规则可复用已有子分组，AI 层级变更和新路径必须人工确认。
Architecture: 复用 `ChannelGroupingConfig` / `ChannelGroupingProposal` / `SubscriptionGroupingState` / `channel_worker`、现有 owner 锁和 BYOK fencing。`ChannelGroupRoot` 只承载结构，成员、读取偏好、RSS 操作和覆盖规则继续引用 `ChannelGroup` 子分组 ID。
Tech stack: Django / SQLite WAL / React / TanStack Query / shadcn/ui；Python 3.12、Node 22。
Spec: 原 AG 合同保留为历史基线；本文后述两级扩展是当前接口合同。
Base: f97c34e305522446efc4f53645c5d4dfb4f1f444（原开发基线；2026-10-23 恢复仍使用此精确基线，非最新远程声明）。

2026-10-23：历史平面分组实现及 `d93beac`、#21/#22 的验收边界保留；随后主工作树新增两级层级候选。旧候选的 PASS 不覆盖新层级行为，真实 Provider、生产、CI 和部署仍未授权。

## 约束与评审重点

- 层级固定为两级。根分类没有频道成员或阅读范围；所有成员、偏好、RSS、绑定和覆盖操作继续使用子分组 ID。
- 迁移保留已有子分组 ID 及其成员、偏好、绑定、覆盖和历史；旧组归入各 owner 的 `已有分组` 根分类。
- 人工操作优先；自动撤销只删除本批新增且之后未被手动触碰的成员关系。AI 创建的根分类和子分组不因撤销删除。
- AI 建议默认人工确认，不采信模型自报置信度。后台 AI 独立显式授权；模型、凭据、结构或模式撤销须阻断派发和最终写入。
- 层级、订阅或标题证据变化使对应旧预览不可应用；未知已派发调用不可盲目重发。
- 必测：跨 owner ID、根删除保护、子组改挂不改成员、首个根/子路径、OPML 完整路径、RSS 完成时二次校验、手动优先和 URL 深链回退。
- 只运行相关测试/类型检查、前端 lint/build；本地交付。用户已接受 `d93beac` 对应预览，当前交互修正候选重新验收仍为 PENDING；未请求 push、PR 或 CI，仍不运行全量测试或真实 provider 调用。

## AG-05.1 / AG-06.1 后端契约

- [x] 原开发批次先补失败测试（历史 RED，不算本次重跑），本次重跑覆盖无绑定时匹配既有“前端开发”、资料补齐后续跑、自定义组建议、owner/撤销/手动保护。
- [x] 扩展配置（默认保持旧行为）：`match_existing: boolean`、`ai_enabled: boolean`、`ai_model_id: string|null`、`daily_limit: integer 1..20`（每用户 AI 任务/日，上限兼容既有 20）。内部保存后台 AI immutable model snapshot。
- [x] PATCH `/api/me/smart-channels/settings/`：mode/off|suggest|auto、match_existing、ai_enabled、daily_limit；开启后台 AI 必须 consent:true + 明确 model_config_id。GET 附 `summary: {pending:number,suggested:number,applied:number}`。重复保存不得重置 active_since 漏掉积压，首次开通只处理之后新增。
- [x] POST 原 proposals URL 支持 `target:'groups'|'hierarchy'`。groups 结果使用子分组 `group_ids` 和完整 `new_group_paths`；hierarchy 结果只建议现有子分组改挂到现有或新根分类。
- [x] GET proposals 列表为显式分页契约：`?target=groups|hierarchy|topics&page=N`（N 为 1–10000 整数），每页固定 30 条，返回 `{results,page,page_size,count,has_more}`；按 `-created_at,-id` 稳定排序。
- [x] groups apply payload 为 `assignments:[{source_id,group_ids,new_group_paths}]`，其中 `new_group_paths` 项为 `{root_id:number|null,root_name:string|null,name:string}`；只能提交持久预览中的精确路径。hierarchy apply 只接受持久预览行的子集。
- [x] 后台先可信绑定/无歧义可信主题名称匹配（只有可信 profile 才自动加入），其余生成待确认或按已授权模型批处理。只有低信任标题/名称匹配时不能自动应用。去重签名包含实际标题/分组定义/配置版本；已应用与人工分组优先。额度恢复后自动续跑，可安全拒绝的请求有限重试；未知派发维持 barrier。
- [x] 扩展 `/api/me/channel-subscriptions/` bulk action `add_to_group|move_to_group|remove_from_group` + `group_id:number` + `source_ids:number[]`；事务处理并记录人工 override，原响应 subscriptions[]。
- [x] 正向迁移、保留旧记录；相关 smart channel/model/evidence/RSS 订阅回归通过。

## 两级层级前端合同

- [x] `ChannelGroupRoot` 与子分组结构字段严格解析；拓扑、ID、版本和名称不一致时失败关闭。
- [x] `/channels/groups?root=<id>&group=<id>` 为唯一层级管理入口：根分类用于展开与子组管理，子分组用于成员管理；无效深链安全回退。
- [x] 根分类支持创建、重命名和仅空时删除；子分组支持创建、重命名、改挂和删除。所有结构写入使用预期版本。
- [x] 侧栏、频道卡片/详情、发现订阅、阅读范围、OPML 和建议编辑器统一显示“根分类 / 子分组”；可选成员和阅读范围只列子分组。
- [x] `/channels/smart` 分为“整理层级”和“整理频道”。层级建议显示当前路径、目标根分类和原因；频道建议显示现有或新根/子路径，确认前不写数据。
- [x] OPML 导入精确匹配嵌套路径；创建新子分组必须发送 `{create,root_id}`，不隐式创建根分类。
- [x] `/channels/manual` 重定向到 `/channels`，旧 `ChannelsPage.tsx` 和重复平面管理测试已删除，有效目录/订阅断言迁入 `ChannelWorkspace` 测试。
- [x] 所有新私有异步写入沿用 viewer、AbortSignal、CSRF 和未知结果屏障。
- [x] 定向 Vitest、typecheck、lint、build 和合成浏览器检查构成当前本地证据；不能声称真实 Provider 或用户 UAT 通过。

## 当前实现边界

| 状态 | 内容 |
|---|---|
| 已实现 | 严格两级模型与迁移；owner-safe 根/子 CRUD；层级与频道两种审核式 AI 提案；首个分组路径；共享路径标签；RSS/OPML 层级合同；统一频道入口 |
| 保留兼容 | 旧 topics 主题预设整理仍是明确标记的次要入口；历史成员、偏好、绑定、覆盖与提案继续使用稳定的子分组 ID |
| 待用户确认 | 当前两级 UI 候选的桌面和移动体验；历史 `d93beac` 与 #21/#22 的验收不自动覆盖本次行为变更 |
| NOT_RUN | 完整后端/前端套件、CI、真实 Provider/Miniflux、生产迁移/部署、真实手机硬件、线上回滚 |

## 交付记录

- 恢复实现已本地提交为 `d93beac118be31767097e251f6447edcc59be87c`；用户于 2026-10-23 接受该提交对应预览，原生下拉与新旧流程反馈不阻塞当次验收。按队列先由 #19 解决提交阻塞，#20 完成只读诊断，#21/#22 分别提交为 `91e1afde966237145c62278d8943aae27fa620ff` 与 `c76038268d7fe66971bed31271c74915bd9cb6c4`。后两项改变 UI，需重新体验确认。本地验收不等于授权 push、PR、CI 或部署。
- B1 独立个人激活边界、B2 owner 失败隔离/轮转、B3 显式分页，以及 F1–F6 前端修复均已恢复并通过对应定向回归。
- 后端频道定向 135 项及证据/RSS 合同定向 15 项、前端 8 文件 91 项、typecheck、迁移一致性检查与 Chromium 合成站点 33 项检查通过。看板 #7 又在相同候选上重跑频道 135 项、typecheck、全前端 lint 和 build：均通过；lint 为 0 errors、1 个候选未修改文件中的既存 warning。看板 #14 再以当前清单哈希运行 B1–B3 后端 43 项、F1–F6 前端 41 项，并重建独立 9531 合成库和 Chromium 证据：33/33、11 张截图。没有重跑全量套件或 CI。
- 预览：`http://localhost:9531/channels/smart`；持久源码与证据入口见[交付记录](local-acceptance-20261023.md)。当前看板 #22 bundle 指纹为 `804a1c3e2da48694e3ed2ea17fa297051b59cae527be8d12c150a503f5c63419`，看板 #21 指纹 `54a97bb2…` 与更早指纹均已失效；用户重新验收为 PENDING。真实模型/引擎、完整套件、CI、生产、部署与线上回滚仍为 NOT_RUN。
- 历史失败保留：原两个 `/tmp` worktree 丢失；第一次及看板 #9 的指定 Luna/xhigh 提交曾因共享 Git `index.lock` 在委托沙箱中只读而 BLOCKED。看板 #19 随后使用受支持的最小 Git 元数据授权完成提交阻塞处理，没有关闭沙箱、重置或改写历史；之后才执行 #20–#22。
