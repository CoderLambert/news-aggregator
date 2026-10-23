# 新订阅自动整理与分组操作改进实施计划

> 执行：superpowers:subagent-driven-development；两条独立写入目标（后端 / 前端），共享契约由主 Agent 固定。用户已批准设计并要求开始开发。

Goal: 新订阅可靠匹配自动加入已有个人分组，模糊结果待确认；简化首页范围选择与批量调整。
Architecture: 复用 ChannelGroupingConfig / Proposal / SubscriptionGroupingState / channel_worker、现有 owner 锁和 BYOK 模型 fencing。保留 topics 模式兼容，新增 groups 目标；DB 为任务事实源，RSS 导入不等待分类。
Tech stack: Django / SQLite WAL / React / TanStack Query / shadcn/ui；Python 3.12、Node 22。
Spec: 本文中的已批准行为与接口契约。
Base: f97c34e305522446efc4f53645c5d4dfb4f1f444（原开发基线；2026-10-23 恢复仍使用此精确基线，非最新远程声明）。

2026-10-23：临时 worktree 丢失后，源码按成功操作记录恢复到持久 worktree；以下勾选仅代表实现和本地合成验证，用户对当前本地预览的明确接受另记于[本地交付记录](local-acceptance-20261023.md)，仍不代表真实 Provider、生产、CI 或部署验收。完整恢复边界、命令、结果与回退亦见该记录。

## 约束与评审重点

- 不自动创建/改名/合并分组；多个分组成员关系保留。已有订阅仅显式“整理未分组”处理。
- 人工操作优先；自动撤销只删除本批新增且之后未被手动触碰的成员关系。
- 不新增爬虫/模型客户端/队列；只使用已有保存的简介与最多 12 条标题。私有分组及结果不写入公共 SourceTopicProfile。
- AI 建议默认人工确认；不采信模型自报置信度。后台 AI 独立显式授权，模型/凭据/模式撤销须阻断派发和最终写入。
- 组/订阅/标题证据变化使旧预览不可应用；未知已派发调用不可盲目重发。
- 必测：跨 owner ID、手动移出后 worker 重跑、首次无标题后补齐、关闭配置时在途 AI、批量移动原子性、URL 搜索范围保留。
- 只运行相关测试/类型检查、前端 lint/build；本地交付。用户已接受当前本地预览，但未请求 push、PR 或 CI；仍不运行全量测试或真实 provider 调用。

## AG-05.1 / AG-06.1 后端契约

- [x] 原开发批次先补失败测试（历史 RED，不算本次重跑），本次重跑覆盖无绑定时匹配既有“前端开发”、资料补齐后续跑、自定义组建议、owner/撤销/手动保护。
- [x] 扩展配置（默认保持旧行为）：`match_existing: boolean`、`ai_enabled: boolean`、`ai_model_id: string|null`、`daily_limit: integer 1..20`（每用户 AI 任务/日，上限兼容既有 20）。内部保存后台 AI immutable model snapshot。
- [x] PATCH `/api/me/smart-channels/settings/`：mode/off|suggest|auto、match_existing、ai_enabled、daily_limit；开启后台 AI 必须 consent:true + 明确 model_config_id。GET 附 `summary: {pending:number,suggested:number,applied:number}`。重复保存不得重置 active_since 漏掉积压，首次开通只处理之后新增。
- [x] POST 原 proposals URL 新增 `target:'groups'`；rules <=200、ai <=40；source_ids 显式本人订阅。目标为当前已有个人分组，response 新增 target，result 可含 group_ids，topic_keys 保留 []；reason/origin/needs_review 继续保留。
- [x] GET proposals 列表为显式分页契约：`?target=groups|topics&page=N`（N 为 1–10000 整数），每页固定 30 条，返回 `{results,page,page_size,count,has_more}`；按 `-created_at,-id` 稳定排序，不接受 page_size 覆盖，更早的 pending/ready 记录靠翻页到达；不能用“满页”推断还有下一页。
- [x] group proposals apply payload `assignments:[{source_id:number,group_ids:number[]}]`，拒绝源/组越权、重复/过量/陈旧，返回原 proposal DTO；不创建组。现有 topics apply 不变。
- [x] 后台先可信绑定/无歧义可信主题名称匹配（只有可信 profile 才自动加入），其余生成待确认或按已授权模型批处理。只有低信任标题/名称匹配时不能自动应用。去重签名包含实际标题/分组定义/配置版本；已应用与人工分组优先。额度恢复后自动续跑，可安全拒绝的请求有限重试；未知派发维持 barrier。
- [x] 扩展 `/api/me/channel-subscriptions/` bulk action `add_to_group|move_to_group|remove_from_group` + `group_id:number` + `source_ids:number[]`；事务处理并记录人工 override，原响应 subscriptions[]。
- [x] 正向迁移、保留旧记录；相关 smart channel/model/evidence/RSS 订阅回归通过。

## AG-04.1 / AG-07.1 前端契约

- [x] 原开发批次先补失败测试（历史 RED），本次重跑：分组搜索选择、当前范围提示/全订阅搜索、批量移动、自动模式/建议确认/撤销与失败重试。
- [x] NewsScopeBar 只展示三个固定范围 + 搜索分组 Popover/Command；完整名称、键盘与窄屏可用；URL/返回与已有过滤器保持。
- [x] NewsList 显示实际搜索范围；分组无结果可仅切为全部订阅，保留搜索词及其他筛选。
- [x] GroupWorkspace 批量加入/移动/移出，选择清晰、受影响数量；复用 shadcn wrappers，保留重命名/删除/提交期间防重入。
- [x] 默认智能整理界面围绕已有分组：一次“整理未分组”、后台模式设置、后台 AI 明确授权、可见状态与建议/历史（可取消/应用/撤销）。保留 legacy topics Organizer 的导出/功能作为高级入口兼容。
- [x] workspaceApi 扩展 DTO；所有新私有异步写入沿用 viewer/AbortSignal/CSRF guards。
- [x] 定向 Vitest、typecheck、受影响 ESLint、build；本地浏览器验证使用 synthetic data，不能声称真实 provider 或用户 UAT 通过。

## 当前实现边界

| 状态 | 内容 |
|---|---|
| 已实现 | AG-04.1 / AG-05.1 / AG-06.1 / AG-07.1；B1–B3；F1–F6；个人已有分组规则整理、建议确认/撤销、批量分组、显式分页、owner 隔离及 worker fencing |
| 保留兼容 | 旧 topics 主题预设整理作为高级入口；没有删除其导出与历史能力 |
| 未实现 / 后续改进 | 用户指出高级 topics 编辑器观感与旧版接近，且其“放入分组”仍使用原生 `<select>`；当前验收明确接受该状态，但它尚未改成项目 shadcn 搜索选择器 |
| NOT_RUN | 完整后端/前端套件、CI、真实 Provider/Miniflux、生产迁移/部署、真实手机硬件、线上回滚 |

## 交付记录

- 本地实现与恢复验证完成；用户于 2026-10-23 明确接受当前本地预览。提交是否成功以实际 Git SHA 为准，不预先填写；本地验收不等于授权 push、PR、CI 或部署。
- B1 独立个人激活边界、B2 owner 失败隔离/轮转、B3 显式分页，以及 F1–F6 前端修复均已恢复并通过对应定向回归。
- 后端频道定向 135 项及证据/RSS 合同定向 15 项、前端 8 文件 91 项、typecheck、迁移一致性检查与 Chromium 合成站点 33 项检查通过。看板 #7 又在相同候选上重跑频道 135 项、typecheck、全前端 lint 和 build：均通过；lint 为 0 errors、1 个候选未修改文件中的既存 warning。看板 #14 再以当前清单哈希运行 B1–B3 后端 43 项、F1–F6 前端 41 项，并重建独立 9531 合成库和 Chromium 证据：33/33、11 张截图。没有重跑全量套件或 CI。
- 预览：`http://localhost:9531/channels/smart`；持久源码与证据入口见[交付记录](local-acceptance-20261023.md)。用户当前本地预览验收为 PASS；真实模型/引擎、完整套件、CI、生产、部署与线上回滚仍为 NOT_RUN。
- 历史失败保留：原两个 `/tmp` worktree 丢失；第一次及看板 #9 的指定 Luna/xhigh 本地提交均因共享 Git `index.lock` 在委托沙箱中只读而 BLOCKED。源码、测试和证据未丢失，当前仍不得写成“已提交”。
