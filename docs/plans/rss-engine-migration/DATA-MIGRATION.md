# 数据兼容、来源映射与迁移门禁

状态：规划修订，NOT_RUN。未读取真实业务库、执行回填或切换；真实数量、开关和动态来源仍 UNKNOWN。C02/C04/C11 是实现合同。

## 保留范围

保留 News/Source/NewsSourceItem/Category 原 PK/FK、News.url/Source.name 唯一和旧发布者 ID。保留 SourceConfig/Endpoint 的政策/停用/审批及历史 FeedState，不把旧 parser_config 变成可执行新配置。

保留用户身份/凭据/OAuth、ChannelSubscription/Group/Member、NewsPreference、智能分组配置/人工覆盖/提案、ReadingDay、Favorite/BlockedNews、Chat、Research 全部关联、私人/共享译文和任务。ReadingDay 不推断已读；新 NewsReadState 缺记录视未读，不修改原统计。

不批量重写旧 Markdown、正文精确 hash 或译文 source_hash；引擎清理不删除本地正文和用户记录。合法正文更新只失效当前译文命中；title+summary 索引仅在对应内容变化时失效，不借迁移重建全站 embedding。

## 兼容字段译文

News.full_content_zh、title_zh、content_zh 不能假定都有独立译文记录。T07 首次替换其对应源文本前，在同一事务写 C02 的 LegacyTranslationSnapshot（原文、译文、精确 hash、legacy/已知来源），再清当前兼容展示字段。归档幂等，不伪造 provider，不删除私人/共享记录。

T14 移除当前序列化的无条件兼容字段回退；匹配当前源 hash 才显示为当前译文。来源版本无法证明的旧译文保留历史，不标当前匹配。旧异步任务捕获开始时源 hash，完成 CAS；不得把旧结果写到新正文。迁移 fixture 必须包含“只有 full_content_zh、无独立记录”及标题/摘要译文、归档中断重放、旧任务晚完成，验证唯一副本不丢失。

## 来源、频道与权限

Source↔Feed 多对多；按 [C02](INTERFACE-CONTRACTS.md#c02) 分开关联、读取和写入权。同 URL 同政策可只加频道关联，不接管正文；冲突留 IdentityConflict。保留旧成员查询并增加 EngineEntryMap/SourceFeedLink 成员，列表、分类/地区、scope、计数使用相同授权关系。

publication 仅 public/personal。旧公开来源初始化 public，新用户源 personal。history_only 只是报告结果，实际 owner=paused、pause_reason=unsupported，保留 publication；分别验证公开停更历史可读和个人停更不公开。收藏不额外授予来源访问权。

source epoch、文章 body_owner_version、政策版本及操作 lease 含义分开。移交主写权不重写旧正文 provenance；任何新旧写入都重验令牌。共用物理 Feed 的旧来源形成最小切换组，避免一个来源切完而别名仍旧采集；Source 暂停不必停其他用户仍引用的物理 Feed。

## 阶段和交付

| 阶段 | 交付 | 条件 |
| --- | --- | --- |
| M0 盘点 | T24 静态来源与授权副本 manifest | 副本缺失仅阻塞真实计数和切换范围 |
| M1 核心兼容 | T05/T07/T11，T02 轻量运行时 | additive 迁移、旧身份/译文、available/ACL；领域 DDL 随 T13/T16/T21 交付 |
| M2 同步与隔离 | T08/T09/T14/T19/T25 | 幂等、元数据映射、对账、旧/新写入 fencing |
| M3 演练并封存 | T03 工具；T26 迁移/恢复/往返应用回滚 | 候选镜像先演练，成功再封存兼容 SHA，不要求预先封存 |
| M4 产品验收 | T27 | 阅读/AI/发现/OPML；真实样本和浏览器，RSSHub 条件依赖 T18 |
| M5 试点和批次 | T29（吸收 T28） | 明确批准、兼容基点、备份；一个来源/最小共享组试点后扩大 |
| M6 退出 | T30/T31 | 全部来源替代或停更；停入口、重启验证、删代码/依赖 |
| M7 最终发布 | T33（吸收 T34） | 最终单栈验证和发布授权；保留兼容镜像 |

T25 的合成切换/fence 开发不依赖生产副本、OPML 界面或已封存镜像。T26 负责实际数据与兼容演练；T27 负责产品联合验收，证据复用不重复执行相同恢复测试。

## 来源 manifest

T24 生成一份机器可读清单，字段：

- schema_version、baseline_sha、inventory_snapshot_id、环境/版本引用；
- 每 source_id 的旧 key/选择规则、Feed/标准路由、对象类型、模式/政策、publication、覆盖差异、支持/停更决定；
- source expected owner/epoch、binding、共享切换组、明确的正文主写接管；
- 原 PK/FK 和用户关系/正文/译文聚合 hash、采样证据、备份/兼容版本引用；
- 逐源 NOT_RUN/PASS/FAILED/BLOCKED、实际时间、失败原因及暂停/回滚结果。

来源/切换组数量据副本确定，不要求每个来源另建三文件或 PR。普通来源共用检查清单；特殊政策、异常路由或失败来源才开专项工单。覆盖比较包含 DEV.to 标签/热度、HN 混合外链、GitHub 仓库、arXiv 摘要、受限医疗和 HTML-only 动态来源；无替代则明确停更，不能保留旧 Spider。

## 实例恢复和验收

instance/account/feed/entry 不能跨重建实例复用；恢复校验配对快照、schema、身份和映射，数字碰撞不当同一条目。未知实例先停写；重建需要明确重绑定方案。

SQLite 使用唯一约束、短事务、CAS/lease 和有限 busy 重试，不依赖 select_for_update 行锁。网络不持写事务；元数据/正文/映射/拒收先于 cursor。引擎保留期外且无备份的缺口明确报告。

数据集：空库、0051 升级、同 URL 多 Feed/政策、同 Feed 多 Source 切换、同名来源、长 URL、missing/legacy/complete/available、公开/个人停更、注册中退订、A/B/匿名、兼容字段及私人/共享译文、全部用户 FK、旧后台任务晚写、实例数字 ID 复用。演练对比原 PK/FK、内容/译文 hash、用户可见性；业务更新产生的差异需解释，不能用“全部 hash 必须不变”阻止合法正文更新。证据仅保存脱敏聚合/hash和受控工件位置。
