# AI 频道智能分组：可交付任务与验收（2026-10-13）

> 先执行 **AG-00** 消除模型授权/元信息的不确定性，再进入功能开发。每一个任务都能独立测试和单独开 PR。不要一次性改动全部模块。功能规格见同目录 [DESIGN.md](DESIGN.md)。

## 已知事实与核心门槛

- 基线 `main@4eea581`，UI PR #53 仍为独立 Draft，不把 AI 功能塞入它。
- `Source` 缺少来源主题，31 个基础 `SourcePolicy` 没有显式主题和简介；26 个专项来源有文本描述及明确领域。
- `llm_translator.get_clients()` 恒为空；用户 BYOK 只在有用户许可/个人凭据时可调用。后台站点级推理必须验证独立合法配置，否则不启用。
- 不得在 `sync_channel_catalog` 只读查询、新闻详情获取或爬虫热路径直接访问 LLM。

## AG-00 / 元信息与 AI 接口验证

**目标**：小样本确认可分类证据质量和模型调用合同。**这是唯一外部模型技术门槛。**

1. 枚举现有可见来源，输出来源名称、政策 key、现有 description、默认 category、最近已入库文章数、可取标题数及缺口清单。不把 0 篇来源直接视为无效。
2. 从已知专项源、AI、前端、综合媒体、讨论社区中至少选 12 个样例建立预期标签；同一频道允许多标签。
3. **仅当配置好合法授权的 DeepSeek 等实际模型时**，通过个人 BYOK 专用请求或独立明确批准的站点模型做一次结构化输出试验；不要求立即提供生产站点共享 Key；未配置则将 AI 阶段明确标为 `blocked_by_model_configuration`，后续规则阶段仍可推进。
4. 确认 LiteLLM Proxy 对 JSON Schema、超时、429、非 JSON 输出的实际行为；只记安全的模型、耗时、是否有效和错误码，不记录密钥。
5. 交付 `docs/features/ai-channel-grouping/VALIDATION.md`：通过/失败、证据样本、需人工补充的基础源字段；如模型试验失败不得宣称“AI 分类已可用”。

**验收**：样本标签为人工可核验真值；至少覆盖 26 个现有专题来源、综合媒体与基础源的对比；不存在无凭据自动调用。

## AG-01 / 来源元信息与主题字典（无 LLM）

实现范围：
- 后端新增稳定 TopicDefinition 与 SourceEditorialMetadata；最小迁移；从明确的来源政策/专题描述回填可验证主题。
- 可信元信息保留来源、revision、证据 hash，不覆盖自定义来源描述。
- 扩展来源序列化只读缓存 topic 字段，增加 `/api/channel-topics/`。

**验收**：迁移前后 Source/News/Subscription/Group 数量与关系不变；官方明确主题可读；一般媒体未知主题可空；GET 没有写库/联网；无跨频道误标注。

## AG-02 / 来源主题归类引擎（可离线运行）

实现范围：
- 规则判定优先处理经审核的 publisher/channel contract + `SourcePolicy.default_category`。
- 基于已存在且正确归属的最多 20 篇文章证据进行弱规则补充，`source_key` 优先，不能只用 News.primary source。
- `SourceTopicAssignment` 保存版本、origin、score、审核状态；对于低证据强制 `needs_review`。
- 测试改名、重复 Source URL、多频道收录、无新闻、类别漂移及重新分类幂等。

**验收**：每个来源最多 3 个主题；确定主题可以离线复现；相同 evidence_hash 不重复创建；不要求 AI Key；不碰既有来源政策/新闻分类。

## AG-03 / 个人预设、预览与安全应用（仍无 LLM）

实现范围：
- `ChannelGroupTopicBinding`、`ChannelAutoGroupPreference`、`ChannelAutoGroupOverride`、`ChannelGroupProposal`；迁移与路由。
- 用户指定几个模板主题，获得本人订阅集合中的 candidate diff；预览不改变群组归属；提交严格检查 user、source、group、revision、idempotency；提交采用已有行锁。
- 同名自定义组默认不直接认领：UI 要求“使用已有”或“创建不同名称”；按 group_id 绑定而不是名称。
- 用户手动移出频道后写 suppress（或补充等价同事务逻辑）阻止后续自动回填。

**验收**：双账户隔离、跨账号 ID 为 404、过期预览冲突为 409、重复 apply 结果不变、取消不写库、读-only/匿名不允许个人写入、删除组保留订阅。

## AG-04 / 管理页 AI 整理向导（依赖 AG-03）

实现范围：
- 基于 #53 合并后的 `/channels` 分组页新建向导：选择预设 → 预览 diff → 可编辑候选 → 确认应用。
- 初版实际只展示“基于来源资料的规则推荐”，暂不出现无效的 AI loading。
- 展示理由和人工/规则/AI 的来源，不显示未经校准的“98% 准确率”。
- 移动端 390px 和桌面 1440px，可键盘全流程执行；确认/取消返回触发控件。

**验收**：零订阅、新用户、全被分组、已有同名组、分组被他处删除、无已知主题、错误/重试都有明确体验；Tab/Escape/焦点恢复无回归。

## AG-05 / 可选 AI 精分（依赖 AG-00 和 AG-02；无合法模型时允许独立延期）

实现范围：
- 仅使用已授权的模型执行结构化内容分析；系统 prompt + 输入/输出 JSON Schema 版本固定，topic allowlist 强校验。
- 用户显式启动可走其 BYOK（成本/失败明确）；无人值守**全站**分类必须另有站点所有者模型配置和使用预算，不得用用户 Key。
- 去重、预算、429 Retry-After、有界重试、异常熔断、时间限制、审计，失败不修改已有标签。
- 不把 prompt 中从网页得到的正文/文本当作指令，绝不泄露私密数据。

**验收**：mock 测 200/429/503/超时/无效 JSON/不存在的 topic/跨来源输出；有效样例完整通过，真实 DeepSeek 单次调用由用户验收；模型不合法或预算缺失时安全降级。

## AG-06 / 新来源增量分类与新增订阅自动归组

实现范围：
- 独立后台扫描新 Source 与 evidence_hash 变化；使用持久化任务、lease、重启恢复、并发保护；不在爬虫或 HTTP GET 里推理。
- `subscribe` 增量处理仅作用于新建立订阅与已有用户 topic-group binding。
- mode=`off` 不做、`suggest` 提示、`auto` 对满足**人工审核或已验收规则置信门槛**且无 suppress 的源添加已绑定分组成员；新增来源时只分类全站 Source，绝不替用户订阅。
- 人工纠正、停用来源、旧分类变更不得触发 destructive write。

**验收**：同时订阅、双用户、重复提交/任务抢占、worker 提前重启、Source 目录刷新、订阅取消再订阅、手动移出再运行、失效/429 等矩阵覆盖；低置信度只待确认。

## AG-07 / 发布与运维

- 功能开关：`channel_topic_catalog`、`channel_group_suggestions`、`channel_auto_group`；全站 read_only 只保留公共目录；不要破坏原 `capabilities` 严格字段数契约（前后端配套迁移）。
- 安全监控：缓存命中率、分类待审核数量、每模型调用次数/平均成本、429、去重、任务队列、失败码；不记录 API Key。
- 数据升级/回退：迁移前备份，新增表可回滚，回退功能开关后保留用户分组，不触碰已有订阅。

## 最低验证命令

```bash
PYTHONPATH=backend:crawler pytest backend/api/tests/test_channels.py -q
PYTHONPATH=backend:crawler pytest backend/api/tests/test_channel_ai_grouping.py -q
npm --prefix frontend run typecheck
npm --prefix frontend run lint
npm --prefix frontend run test:run
npm --prefix frontend run build
```

其中 `test_channel_ai_grouping.py` 是 AG-01 起逐步新增的测试文件，不是现有代码中的文件。真实浏览器和实际模型调用另行验收，不能由单元测试替代。

## 开发纪律

- 只在任务最小范围内修改代码，不顺带重写新闻列表、爬虫、OAuth、正文队列。
- 每个任务独立分支 + Draft PR + 恰当测试和文档；完成后审核，再决定合并。
- AG-00 外部模型未通过不阻塞 AG-01~04 的无模型功能；禁止为了测试临时关闭 SSRF/凭据安全/账号隔离。
