# AG-00 静态代码可行性核查记录

- 日期：2026-10-13
- 精确基线：`main@4eea5814cef56e2f79f6d771fbd035e3424f0a53`
- 结论：**规则+人工审核的来源主题分类可直接进入开发；全站后台 AI 自动推理尚不能宣布可用。**

## 已核实（来自 main 当前代码，不是数据库实测）

| 维度 | 代码证据 | 状态 |
| --- | --- | --- |
| 基础源政策 | `backend/api/services/source_policy.py` 原始 `POLICIES` 含 31 个 `SourcePolicy` 定义；没有传 `description=` 或 `default_category=`，dataclass 默认两字段均为空 | 来源主题资料不足 |
| 行业专题政策 | `backend/api/services/sector_feeds.py`：12 个能源 + 14 个医疗，总计 26 个；都有领域描述与对应默认类别 | 可以先做确定性主题映射 |
| 目录同步方式 | `channel_catalog.sync_channel_catalog()` 当前以 `Source.objects.get_or_create` 补缺，不覆盖已存在 Source | 可保持旧数据不变 |
| 文章分类 | `News.category` 与 `Source` 是不同概念；`NewsSourceItem.source_key` 可按采集频道归属识别一篇跨频道文章 | 可用公开已入库文章作为补充证据，不应只看 News.source_id |
| 个人分组 | `ChannelGroup` 与 `ChannelGroupMember` 已支持一用户一层多组、同来源多组，受 `ChannelSubscription` 保护 | 不需重建用户分组模型 |
| 站点共享 LLM | `api.services.llm_translator.get_clients()` 当前直接返回 `[]` | 不具备后台无人值守 AI 前提 |
| 用户 BYOK | `provider_credentials.personal_clients_for_user(user)` 可由用户自己授权的 provider/model 进入 LiteLLM Proxy | 可供用户主动 AI 补充分组使用，不能隐式借给全站后台 |
| 公共能力开关 | `capabilities_views` 在 read_only 拒绝账号类能力，前端 `parseCapabilities` 严格验证完整 feature 字段集合 | 新功能开关须同步后端与前端；只读必须 fail-closed |

> 31 + 26 是静态注册策略数 **57**，不是运行中订阅频道的精确数量。部分政策不可用，实际已注册、已停用和历史数据库差异须独立统计。

## 暂未验证，不得写成通过

1. 本机数据库/生产库中 57 个策略对应多少实际 Source、每个 Source 是否已有经审核简介；用户未提供数据库访问。
2. 12 个及以上不同性质频道的带人审标签的真实样本集、文章标题证据完整性与误分率。
3. 真实 DeepSeek/LiteLLM 结构化 JSON 请求、429/超时、费用和额度；本轮没有凭据，也**没有进行外部模型调用**。
4. `NewsSourceItem.source_key` 与 Source 映射在所有旧数据中的覆盖率、同一文章多归属的比例。
5. 个人分组页面 UI PR #53 的真实浏览器验收与 AI 向导交互，尚未开始。

## 研发下一步（不需等待模型密钥）

- AG-01：建设稳定主题字典与元信息 sidecar，只从可信 policy/专项描述回填，保障历史 Source 不改写。
- AG-02：对 26 个专项源做可验证的确定性初始标签；为基础源增加待审核状态和文章证据提取路径。
- AG-03：实现用户可编辑差异预览/幂等提交，确保手动移出不会被自动补回。
- 在真实模型调用验证并拿到明确的站点模型预算后，AG-05 才能启动全站无人值守 AI 分类；此前 UI 应标识为“基于来源资料的推荐”，不能错误显示“AI 已分析”。

## 高风险回归测试清单

- 模型无凭据或抛错：不得返回伪造分类；不得改写已有手动分组。
- 相同来源同时有两组与两个账号：分类可共享，分组写入必须严格账号隔离。
- 来源缺少简介且文章为零：保留待分类，不能凭地域/语言断言主题。
- 上一次预览后订阅数或目标分组变化：应用必须冲突拒绝，不按过期数据写入。
- 同一用户“新订阅”事件被重复投递：仅增加一次组成员，不新增订阅。
