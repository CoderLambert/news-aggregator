# NewsHub main PR / Issue 去重审计（2026-10-17）

> **基线**：`main@bbd1be2ade62b4437e7f5d5647751c855fa3b717`（北京时间 2026-10-17）。本报告依据当时 GitHub OPEN PR 元数据、`main` 文件与已有验收记录；不是生产环境运行报告。**不把旧分支 CI 或合成测试替代当前 main 的验证。**

## 1. 仓库现状及判定

- 已核实开放 PR **15** 个，全部相对 `main` diverged。除 #54、#28 外，13 个属于 BYOK 旧任务链。大多数 BYOK 分支相对当前 main 落后约 216 个提交（#28 落后 367 个），**不能直接按旧 base 顺序合并**。
- PR #76（A09）、#77/#78（RSS，包含 #80 修复）及 CI #81–#86 的已合入成果不重新开发。
- 当前代码已有 `backend/api/services/news_ingestion.py` 的受控 `body_candidate` 写入机制、`structured_articles.py`、DEV.to/HN 对接、TechCrunch 专用 Provider（默认关闭），也已有 `channel_topics.py`、`channel_grouping.py`、`channel_ai.py`、`SmartGroupingWorkspace.tsx` 等智能分组代码。旧 Issue 文字中的“完全没有该能力”不再准确。
- 当前 `main` 也已有 `UserProviderCredential`、`provider_credential_views.py` 与加密服务；旧 T01 不能不加比较直接覆盖当前模型/迁移。旧 BYOK 实现与现有入口并不等价，不能据此宣称 T01–T09 全部完成。
- `main` 已有 `ops/ci/benchmark-xdist.sh`（7 个模块串行、其余 `-n 2 --dist=loadfile`）及 `xdist_summary.py` 计数校验。默认 CI 切换需同 SHA 的完整 CI 合格。

## 2. 15 个开放 PR 的处置矩阵

| PR | 内容与旧 base | 对照 main 的处置 | 依赖 / 后续动作 |
| --- | --- | --- | --- |
| [#54](https://github.com/CoderLambert/news-aggregator/pull/54) | 智能分组**设计文档**；base main 的旧版本 | **设计已部分过时；暂不合并旧任务清单**。A09 已有主要规则、UI 与后台路径 | 将 #55 只保留现有能力的差距、真实模型及验收；确认文档是否需迁移后可关闭旧 Draft |
| [#45](https://github.com/CoderLambert/news-aggregator/pull/45) | T00 SDK 协议/安全适配；base 旧 T01 | **保留为 T00 参考实现**；只选择性移植，与 #33 去重 | 对 `main` 的最新服务接口重审，离线协议测试必须过 |
| [#44](https://github.com/CoderLambert/news-aggregator/pull/44) | R0 SQLite 锁重试；base 旧 BYOK 根分支 | **条件保留**；主线已有不同的事务重试/租约机制，先重现缺陷再决定移植 | 单独 SQLite 高争用回归；不得重复重试模型请求 |
| [#43](https://github.com/CoderLambert/news-aggregator/pull/43) | T09 BYOK 研究任务 | **未直接合入**；不能拿旧分支绿灯替代 main | T03 + Gateway + 实际运行授权；不能绕过工具调用校验 |
| [#42](https://github.com/CoderLambert/news-aggregator/pull/42) | T08 翻译结果读取、聊天、TTS | **未直接合入**；增量移植 | 依赖 T07，跨用户隔离和旧翻译兼容 |
| [#41](https://github.com/CoderLambert/news-aggregator/pull/41) | T07 取消/重试/恢复合同 | **需对照 RSS 已有持久任务恢复去重** | 依赖 T06；检查代际 fencing、失败保持历史结果 |
| [#40](https://github.com/CoderLambert/news-aggregator/pull/40) | T06 长文章 BYOK 翻译 | **未直接合入** | 依赖 T05；上下文预算、分块、Markdown 完整性 |
| [#39](https://github.com/CoderLambert/news-aggregator/pull/39) | T05 私人全文翻译 | **未直接合入** | 依赖 T04；与现有 RSS 正文/翻译隔离 |
| [#38](https://github.com/CoderLambert/news-aggregator/pull/38) | T04 逐轮私有文章聊天 | **未直接合入** | 依赖 T03；不隐式回退站点密钥 |
| [#37](https://github.com/CoderLambert/news-aggregator/pull/37) | T03 分类任务的模型偏好 | **未直接合入** | 依赖 T02；配置和密钥版本快照 |
| [#36](https://github.com/CoderLambert/news-aggregator/pull/36) | T02 模型能力探针 | **未直接合入** | 依赖 T01 + 网关；完成能力与安全负向测试 |
| [#35](https://github.com/CoderLambert/news-aggregator/pull/35) | T00 共享 LiteLLM Proxy 运营配置 | **可作为独立网关参考**；没有线上部署证据 | 先验证隔离网关与当前生产 Compose 的边界 |
| [#34](https://github.com/CoderLambert/news-aggregator/pull/34) | T01 用户凭据 CRUD/加密 | **主要需要 API/迁移差异审计，不可直接合并**；主线已有不同的 provider credential 路径 | 识别主线缺少的多模型/撤销语义，禁止重放旧 `0033` 迁移 |
| [#33](https://github.com/CoderLambert/news-aggregator/pull/33) | T00 LiteLLM DeepSeek 门控实验 | **与 #45 部分重叠**；保留真实 gateway smoke 合同/负向测试作参考 | 挑选必要测试移植到当前 T00；原 PR 不直接合并 |
| [#28](https://github.com/CoderLambert/news-aggregator/pull/28) | Hosted SIWC OAuth/订阅推理 | **外部审批阻塞；保持 Draft，不合并、不发布** | 必须有覆盖 hosted inference、token 存储/使用范围的书面许可，不能以普通登录批准替代 |

**重要**：上表“未直接合入”指旧 PR 的代码分支，**不是**断言 `main` 中完全不存在相同业务能力；迁移决策以当前源码和新增回归为准。

### BYOK 最小可执行依赖

```text
T00 SDK 协议（优先参考 #45；去重 #33）
          |
T01 当前凭据语义差异审计（#34） -- T00 网关/项目隔离（#35）
          |                                 |
          +--------------+------------------+
                         |
                   T02 模型验证（#36）
                         |
                   T03 偏好快照（#37）
                    /              \
        T04 文章聊天（#38）    T09 研究（#43）
                |
        T05 私人翻译（#39）
                |
        T06 长文翻译（#40）
                |
        T07 生命周期（#41）
                |
        T08 统一读取（#42）

R0 SQLite（#44）：独立缺陷重现关卡；确认 main 仍有相同缺陷才移植。
SIWC（#28）：外部书面授权关卡；与纯 BYOK 独立。
```

**禁止**直接 cherry-pick 旧父分支的所有迁移；最新主线已经演进到 RSS/频道迁移后期，必须为差异创建当前的向前迁移，验证 fresh/upgrade/rollback。每一个新 PR 应基于**合并时的最新 main**，不再依赖旧堆叠 PR 的 base。

## 3. Issue 精确裁剪

### [#52 可信正文入库](https://github.com/CoderLambert/news-aggregator/issues/52)

**静态实现已具备（不得重写）**：
- `NewsItem.body_candidate` 与 `news_ingestion.ingest_item` 校验/原子保存；
- `dev_candidate`（DEV.to Markdown/HTML）及 `hn_candidate`（HN 无外链自帖）；
- TechCrunch WordPress 专用 Provider，包含身份、状态码、正文负向测试；
- `STRUCTURED_BODY_INGEST_ENABLED`、来源 allowlist、`TECHCRUNCH_WP_ENABLED` 均**默认关闭**；完整正文补抓也有独立开关/来源限定。

**仍需验证，不是已完成**：
1. **F52-R1** 按来源审核版权、可信身份、正文大小、完整性及源码端点；建立有权限的 DEV.to/HN/TechCrunch/Feed 真样本集。
2. **F52-R2** 核对旧数据/已存在有效正文保护、刷新时译文失效、失败事件、RSS 正文主写和可恢复回退；在当前 main 上补缺失回归（不能将摘要当全文）。
3. **F52-R3** 先隔离环境启用单来源 allowlist，小批量受控采集；对失败率、429、身份误配、正文完整率给出明确 PASS/FAIL 与回滚。
4. **F52-R4** 生产功能启用和定时全文 worker 属运维审批。全局 scheduler / 自动补抓不得随代码变更开启。

### [#55 智能分组](https://github.com/CoderLambert/news-aggregator/issues/55)

**静态实现已具备（不得重写）**：
- `channel_topics.py` 稳定 Topic、3 个 Preset、已知来源人工映射、证据哈希；
- `SourceTopicProfile`、`ChannelGroupingProposal`、用户私有设置与人工 suppress；
- `make_proposal/apply_proposal/undo_proposal`，`off/suggest/auto` 增量订阅；
- `channel_ai.py` 可选模型、严格结构化输出、授权限制、错误/429 退避；
- `frontend/src/pages/SmartGroupingWorkspace.tsx` 和 `test_smart_channel_workspace.py` 覆盖主要路径。

**剩余差距与验收**：
1. **F55-R1** 将旧 AG-00~07 与当前 main 逐项映射，不新建同义表、不照抄 PR #54 设计；检查 UI 键盘/移动端、人工优先权、重复/并发/租约等边界。
2. **F55-R2** 在明确有效的个人模型授权下，运行一次受限真实 DeepSeek 结构化分类，评估未知/低证据源；没授权则标记 NOT_RUN，不冒充通过。
3. **F55-R3** 在真实来源新增、订阅变更与异常 429 环境验证队列限额/恢复及发布禁用策略；真实来源与在线模型均不是现有 mock 测试的替代品。

## 4. 余量任务排序与交付门槛

| 顺序 | 工作单元 | 可并行 | 最低交付及门禁 |
| --- | --- | --- | --- |
| P0-A | 15 PR 去重/Issue #52、#55 裁剪 | 已执行静态审计 | 本文档；不把未运行列为已通过 |
| P0-B | 默认 CI 启用单轮混合并行 | 与 A 并行 | 7 串行、其余 2 worker、2410/16 精确计数、全量 frontend/backend/image/G1 的**对应提交** CI 成功 |
| P1-C1 | RSS T24 真实 SQLite 副本盘点 | 可独立 | 真实副本只读盘点与敏感数据脱敏证据 |
| P1-C2 | RSS T26 真实配对恢复/回滚 | 依赖 C1 | 独立测试库双向恢复、故障回滚，无生产破坏 |
| P1-C3 | RSS T18 公网 DNS/TLS/token/publisher | 与 C1 并行 | 实际外网身份、redirect 和 token 测试报告 |
| P1-C4 | RSS T27 正文完整性 | 与 C1 并行 | 重新核验 Fowler、Uber、其他问题源与真实样本；失败不计通过 |
| P1-F52 | 可信正文的来源专项收口 | 与 C/D 文档并行 | 受控正文样本质量及采集策略准入证据 |
| P1-F55 | 频道智能分组差距专项收口 | 与 F52 并行 | 规则/AI/人工/恢复/UAT 分项证据 |
| P2-BYOK | 新 main 上按最小依赖重建 T00–T09 | P1 审计后渐进实施 | 迁移隔离、模型授权、可靠性及实际运行验收 |
| P2-D | NH-28–NH-31 生产发行验收 | 独立环境/授权 | 用户 BYOK 模式、异机密钥恢复、来源许可与质量、独立 2C4GB 容量降级全通过 |
| P3-DEPLOY | 发布前审批与实际部署 | C/D PASS 后 | **独立人工放行**；本次不动生产 |

## 5. 本次变更范围与未触及项目

- 此审计仅基于 GitHub 当前源码/文档。**未访问生产数据库、密钥、用户账号、公网鉴权或已部署站点**。
- CI 的混合并行提案仅改变测试调度，不跳过模块，不改变合成 G1、权限、部署参数或测试数。实验的约 127 秒不是本 PR 的默认 CI 实测。
- 不执行生产切换、真实新闻爬取、付费模型调用、外部 OAuth 授权、实际数据库恢复，也不宣称这些已通过。
- CI/PR 提交 SHA 后仍需重新查看其**完整** GitHub Actions 结果并把 PASS、FAIL、SKIP、NOT_RUN 分别记账。
