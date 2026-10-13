# AI 频道智能分组：架构与交互契约（2026-10-13）

> 状态：**方案待研发验收**；当前分支仅包含设计/任务/验收文档，**未实现后端 API、AI 推理或界面控件**。基线：`main@4eea5814cef56e2f79f6d771fbd035e3424f0a53`。UI 改版见独立 Draft PR #53，本需求不得顺便混入该 PR。

## 1. 目标与不可更改的约束

1. 用户首次进入分组管理时可以选一个或多个内置主题预设，查看当前已订阅频道的分类建议，确认后批量创建分组与分组成员关系。
2. 未来新增“系统采集频道”时，系统为**全站 Source** 增量生成标准主题分类；未来用户新增“个人订阅”时，按用户已开启的分组模式应用或提示建议。
3. 全站主题标签与用户自己的分组完全解耦，既有自定义名称、手动归属/移除、订阅及账号数据不被覆盖。
4. 没有付费模型时仍可提供**明确标记为“规则推荐”**的标准主题建议；不得以规则冒充 AI。AI 失败时回退规则或“待分类”，不得默默把所有来源判为“科技”。
5. 不允许 AI 自动订阅、删除订阅或删除分组；不允许来源采集行为因本功能产生额外 HTTP GET；不允许直接根据名称猜测高置信度主题。
6. 保持现有一层、多归属的 `ChannelGroup`；不做层级嵌套和新闻逐篇 AI 分类。

## 2. 当前代码与未解决风险

- `Source`：`backend/api/models.py` 已有 `name,url,description,logo,country,language,region,source_type`，不含标准化来源主题。
- `SourcePolicy`：`backend/api/services/source_policy.py` 有可追溯官方来源键与部分 `default_category`，基础策略中 31 个来源均没有显式 `description` / `default_category`；`sector_feeds.py` 中 26 个专项来源有专题描述和默认“新能源”或“医疗健康”类别。
- `sync_channel_catalog()` 用 `get_or_create`，只补缺失来源，且 GET 目录只读。新分类不能破坏这条只读/不覆盖现有记录的契约。
- 新闻 `Category` 描述的是**单篇文章**，不应直接作为 `Source` 的主题字段。综合媒体可以有多个主题，一个文章来源与频道键不总是一对一。
- `ChannelGroup` 属于账号，`ChannelGroupMember` 关联用户自己的 `ChannelSubscription`，应继续用它们，不新增第二套分组真值表。
- `api.services.llm_translator.get_clients()` 当前恒为 `[]`；`personal_clients_for_user(user)` 走**用户个人 BYOK LiteLLM Proxy**。因此全站异步自动分类不能隐式使用任意用户 API Key。必须单独验收明确的站点可用模型/预算后才能开启无人值守 AI。

## 3. 产品结构与预设

- **全站主题表（topic taxonomy）**：稳定 `key`、中文名、英文名、说明、互斥/非互斥约束和版本，不以用户分组名称充当稳定标识。
- **内置主题包**：`基础科技`（人工智能、开发技术、科技产业、网络安全）、`开发者`（前端、后端与基础设施、开源工具、人工智能）、`行业洞察`（新能源、医疗健康、商业财经、科研前沿）。一个用户可以勾选主题、合并主题到已有分组或跳过主题。不要自动生成大量空分组。
- **用户绑定**：`topic_key -> group_id`，允许用户重命名组，绑定仍指向原组 ID；允许多主题映射同一自定义组；同一频道可以属于多个组。
- **模式**：`off` 关闭、`suggest` 推荐待确认（默认）、`auto` 仅对明确开启后的**新增个人订阅**自动加入已绑定分组；自动模式默认不创建新分组。
- **推荐范围**：只处理该用户已订阅的 Source；对所有来源允许多主题，最多 3 个主题并标注依据；低置信度先留在“待确认”，不硬分。
- **用户保护**：人工移出或人工指定归属优先级永远高于 AI；切换分类模型或更换来源元信息不覆盖人工归属。

### 交互（频道管理独立入口）

`频道管理 -> 分组管理 -> AI 智能整理`：
1. 选择主题预设和自动化模式，默认 `suggest`。
2. 生成预览：`新建分组` / `加入已有分组` / `待确认来源` / `跳过未订阅`，每条来源能查看主题、解释和“规则/人工/AI”依据。
3. 支持手动纠正、移除候选、将多个主题合并到自定义组；**提交前展示实际变更差异**。
4. 确认应用：原子创建预设绑定与多组成员，弹出结果。用户中途取消不修改任何关系。
5. 后续来源已分类时，通过小型非阻断提示“新订阅频道已建议加入 XX”，支持单击接受或忽略。

**重要：示意数据不得写死为真实系统频道数量，不能把“分类置信度”伪装为校准概率。**

## 4. 元数据与数据库设计

### 4.1 最小来源元信息

建议新建 `SourceEditorialMetadata`（Source 一对一，内容与抓取授权策略分离）：

| 字段 | 类型 / 规则 | 用途 |
| --- | --- | --- |
| `source_id` | FK unique | 主体 Source |
| `canonical_policy_key` | varchar64 nullable, 显式映射 | 稳定来源身份；不根据模糊网站名推断 |
| `about` | varchar(1000) nullable | 人工审过的来源/频道内容定位，不写通用占位描述 |
| `focus_terms` | 受控短文本数组，最多 12 | 来源主题线索，不是最终分类 |
| `metadata_origin` | curated / policy / observed | 来源可靠性 |
| `metadata_revision` | bigint 递增 | 乐观并发与重算触发 |
| `evidence_hash` | SHA256 | 对参与分类的信息做一致性比较 |
| `updated_at` | datetime | 审核周期 |

语言、地区、网站 URL、source_type 不重复存；feed URL 和 crawl 权限继续以 `SourcePolicy` 为权威来源，AI 不得修改策略。

建议先使用现有 `Source.description` 与 `SourcePolicy.description/default_category` 进行计算，**只为必要的审核内容增加 sidecar 数据**，不得用迁移直接覆盖旧 Source。

### 4.2 分类结果与用户绑定

- `TopicDefinition`：`key` 唯一、`label_zh`、`label_en`、`description`、`taxonomy_version`、`active`。
- `SourceTopicAssignment`：`source_id`, `topic_key`, `origin` = `curated|policy|rules|ai`, `evidence_hash`, `taxonomy_version`, `model_id`（可空）, `score`（仅排序分数，不对用户称为概率）, `review_state` = `accepted|needs_review`, `classified_at`；建议唯一约束 `(source, topic_key, taxonomy_version)`。
- `ChannelGroupTopicBinding`：`user_id`, `topic_key`, `group_id`，同一 topic 在一个用户下只能有一条绑定；外键用户与 group.owner 需要**事务内二次校验**。
- `ChannelAutoGroupPreference`：`user_id` 唯一，`mode`。
- `ChannelAutoGroupOverride`：`user_id`, `source_id`, `group_id`, `decision` = `suppress|manual_accept`。当用户手动移出组时记录 `suppress`，后续自动回填不得重加。
- `ChannelGroupProposal`：`uuid`, `user`, `input_revision_hash`, `proposed_changes` (仅 source IDs, group IDs, topic keys), `status`, `expires_at`, `idempotency_key`；失效/变更时拒绝旧建议、要求刷新。

涉及账号/分组/订阅的提交在 `transaction.atomic` 中沿用 `channel_views` 的用户行锁；涉及其他用户 group/source IDs 要返回 404，不可合并。

## 5. 分类计算路径

```text
Source 创建/政策目录变更
    -> 根据 metadata_rev / evidence_hash 判定是否有新证据
    -> 可信人工标签(最高优先级)
    -> SourcePolicy.default_category 专题映射
    -> 规则分类：元信息 + 按实际 source_key 归属的最近文章标题/类别分布
    -> 多主题不确定：入待审核队列
    -> [明确启用的模型配置 + 已批准预算] 异步 AI 补充
    -> 验证严格 JSON schema / topic allowlist / 有效 Source
    -> 更新全站来源主题标签（带版本和审计），不写用户分组
    -> 用户新订阅时按个人 mode + 主题绑定决定“建议”或“自动添加”
```

**取样**：优先官方元信息，必要时最多提取最近 12–20 个已入库文章标题、人工定义的内容分类及简短摘要；不请求文章正文、不爬来源首页、不调翻译。对跨频道去重新闻通过 `NewsSourceItem.source_key` 关联，不要简单只看 `News.source_id`。去除 HTML、控制字符，裁剪长度，不把来源提供的文字当成指令。

### AI 调用契约

- 站点级自动来源分类使用经过明确配置的**站点所有者模型凭据**，与用户 BYOK 分开；没有站点级授权时仅规则推荐 + `needs_review`，绝不私下借用户凭据。
- 用户显式点击“一次性 AI 完善”可经现有 `personal_clients_for_user` 使用自己的 BYOK；需单独限定模型调用次数，首次说明凭据与成本；不允许在页面 GET 或列表浏览时调用模型。
- Prompt 使用稳定版本与严格 JSON Schema：`{source_id, topics:[{key,reason,evidence_ids}], requires_review}`；topic key 必须来自允许列表，source_id 必须属于本次输入，最多 3 个主题，理由不能包含伪造证据。
- `temperature=0`（支持时），批量限制，响应上限；失败/乱码/输出超限保留原建议，不写变更。
- `(source_id, evidence_hash, taxonomy_version, prompt_version, model_id)` 唯一缓存，同一证据不能重复扣费；异常重试需同一去重键。
- 网关 429/5xx 必须有指数退避并遵守 Retry-After；断路/预算耗尽后保留 pending，不无限重试。站点级请求预算单独限额，例如每批最多 20 个、单次最多 2 次有界尝试，具体上限由验证决定。
- 后台任务使用持久化队列/续跑租约；超时、进程重启、取消和用户变更订阅必须 fail-closed；不得在 Django 请求主线程中同步执行大批分类。
- 不记录 API Key、可识别用户信息或全量 provider 请求正文；模型输入只有公开频道元信息和已发布文章线索。

## 6. API 契约草案

| 端点 | 方法 | 作用 |
| --- | --- | --- |
| `/api/channel-topics/` | GET | 全站主题字典与版本，公开只读 |
| `/api/sources/` | GET（扩展） | 返回 `topic_keys`, `classification_origin`, `review_state`，必须是已缓存、不能触发推理 |
| `/api/me/channel-auto-group-preferences/` | GET/PATCH | 用户模式 off/suggest/auto |
| `/api/me/channel-group-proposals/` | POST | 针对指定**本人已订阅**来源创建快照预览，不产生会员/分组写入 |
| `/api/me/channel-group-proposals/<uuid>/` | GET | 取本人预览、模型状态与差异 |
| `/api/me/channel-group-proposals/<uuid>/apply/` | POST | 提交经用户编辑过且仍有效的 diff，原子写入绑定与组成员 |
| `/api/me/channel-group-proposals/<uuid>/cancel/` | POST | 取消待处理建议 |
| `/api/admin/channel-topic-jobs/` | POST/GET | 站点级增量分类，严格超管+单 worker + 限额 |

建议不另建可能暴露 user grouping 信息的公开 API；预览/应用需要既有认证/CSRF/限速，`Cache-Control: private, no-store`。AI 推理发起要区别于纯规则预览，避免隐藏扣费。

## 7. 增量处理与正确性

- **新 Source**：`sync_channel_catalog` 仍无副作用地只增补目录；独立异步扫描任务寻找缺失/过期分类（首期手动/定时命令，无需立即修改 crawl）。任务以 `source_id+evidence_hash+taxonomy_version` 幂等。
- **新用户订阅**：`ChannelSubscriptionsView.post(action=subscribe)` 在事务完成后调度增量分组，不能在锁内调用模型；`off` 不做、`suggest` 建议、`auto` 仅向用户**预先绑定**的组加成员且跳过 suppress。
- **分类修订**：全站标签更新不能删除用户既有分组归属，不自动移动历史订阅；标为更新建议供用户确认。
- **已停用频道**：已有历史订阅可分类但不能被本功能重新启用/新订阅。
- **全站只读模式**：继续只读主题目录，拒绝任何个人数据写入或 AI 支付调用。
- **元信息缺失/低可信**：标注“信息不足”，先人工核验，不硬分；不根据地区/语言推导主题。

## 8. 不纳入本轮

- 不训练模型、不做用户行为画像、不导出个人收藏或私密对话作分类输入。
- 不增加新 RSS 源提交入口、不从 LLM 生成要采集的 RSS URL、不突破 robots/付费墙。
- 不变更站点文章原有分类、来源阅读策略或多频道归属结构。
- 不做定时 AI 重新分类每篇新闻，不允许无上限后台调用。

## 9. 与 UI PR #53 的集成

当前 `/channels` 分组页经 PR #53 已优化为侧栏导航/紧凑频道行。新增一个显眼但非强制的 `AI 智能整理` 入口，打开独立向导；现有创建分组、单频道编辑及批量管理继续保持手动可用。未来前端 PR 在 UI PR #53 合并后重置最新 main；本设计分支不修改该 PR，避免 UI 与元数据后端的验收耦合。
