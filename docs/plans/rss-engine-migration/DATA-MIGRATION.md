# 数据兼容、来源映射与迁移门禁

状态：规划合同；没有运行数据库迁移、读取真实库业务行、执行回填或修改生产。当前数据库规模、来源数、开关、动态配置及版本是UNKNOWN，必须在授权的一致性副本核验。

## 保留清单与明确差异

News/Source/NewsSourceItem/Category的PK和所有现有FK保持；News.url全局唯一和Source.name唯一保持。保留SourceConfig/Endpoint已审政策/审批/停用信息及旧FeedState历史，不能把parser_config变成新引擎可执行配置。

保留ChannelSubscription/Group/Member、NewsPreference、ChannelGroupingConfig/Override/Proposal/SubscriptionGroupingState、ReadingDay、Favorite/BlockedNews、ChatSession、ResearchSession/SearchResult/Run/Event、用户身份/凭据/OAuth连接/选择、私人和共享译文及任务。迁移fixture按实际模型清单完整列出，不因名称未写在这里而允许删除。

ReadingDay是按日遥测，非可切换已读；新增NewsReadState不推断、不回填旧已读，不重写统计。原标题/摘要/正文、精确正文hash、译文源hash/revision、收藏/研究关联均在旧→过渡→新→回滚比较。

新增内容不重写历史全文格式，避免全量译文hash失效。合法正文更新按C04 CAS和当前译文展示校验，历史译文记录不物理删除；新引擎保留期清理不删除NewsHub文章/用户记录。向量索引当前只用标题+摘要，不借迁移重建全站embedding。

## 唯一来源身份与可见性

Source与Feed多对多，旧别名、一个来源多个端点、同Feed多个逻辑频道均保留映射。复用News只允许身份及来源政策兼容；其他URL碰撞写IdentityConflict（不新建相同URL News、不覆写旧正文、不放宽权限）。

旧站点已公开来源显式publication=public，不从订阅数推断。用户新增默认personal，只允许当前有权订阅关系用户读取。published行为是独立审核动作；共享物理Feed不意味着全站发布。body_source_binding和policy_version参与正文授权。已有正文政策不明时禁止随新映射提升公开范围；等待审查而非默认public。

## 迁移阶段与可逆性

| 阶段 | 任务 | 允许的动作 | 放行证据 / 回滚 |
| --- | --- | --- | --- |
| M0 盘点 | T24 | 仓库静态清单；授权副本只读统计 | 来源规则、FK/计数/hash、动态源；UNKNOWN不能PASS |
| M1 兼容扩展 | T05/T07/T11/T03/T35 | 隔离库验证additive DDL与新状态读取 | 固定兼容schema/manifest/镜像；可读available；原PK/FK不变 |
| M2 可靠同步 | T08–T14/T19/T25 | 隔离新引擎、正文接收、ACL、ownership fence | 幂等、晚写拒绝、对账、旧内容不退化 |
| M3 副本演练 | T36/T26/T27 | 先封存完整fence兼容基点，再故障注入、真实来源/浏览器、回滚/恢复 | 双库匹配、人工内容验收、用户数据校验 |
| M4 单源试点 | T28 | 仅精确批准source_id/窗口/SHA的切换 | 先paused、排空、fence再miniflux；失败保持paused |
| M5 逐源执行 | T29-SOURCE-ID / T29 | 每源独立批准切换或明确history_only | 选择规则差异/模式/停更获审核，不留隐藏Spider |
| M6 退出旧栈 | T30–T32 | 真实验收后停进程、删代码/依赖 | 宿主cron/systemd/重启证据；兼容版本留存 |
| M7 最终放行 | T33/T34 | 最终回归/资源/独立审核；获批发布 | 无未完成来源/副作用，证据封存 |

本轮只写M0静态计划；没有上述任何产品变更。部署工具目前不支持完整RSS角色及跨schema回滚，T03必须先修合同和实测，不能在M4临时改生产脚本。

## 来源清单格式

T24必须产出受审机器可读manifest（不含secret值）：

```json
{
  "schema_version": 1,
  "baseline_sha": "878b69081f8d5b3ae965bcf1c855390b059caa33",
  "inventory_snapshot_id": "REQUIRED_FROM_AUTHORIZED_COPY",
  "sources": [
    {
      "source_id": "REQUIRED_ACTUAL_PK",
      "legacy_key": "REQUIRED",
      "old_selection_rule": "REQUIRED",
      "candidate_feed_or_route": null,
      "candidate_verified_at": null,
      "target_mode": "UNDECIDED",
      "reading_policy": "REQUIRED",
      "coverage_difference": "REQUIRED",
      "decision": "BLOCKED",
      "owner_epoch": "REQUIRED",
      "task_id": "T29-SOURCE-ID",
      "rollback_manifest": null
    }
  ]
}
```

以上为占位格式，不是实际来源行。原生全文、摘要、HN混合外链、DEV.to按标签热度、GitHub仓库简介、arXiv摘要/无PDF、受限医疗以及0051中HTML-only来源分别比较对象与覆盖，不能按同名宣布无损。现有关键词选题只能做元数据过滤，不可保留自研抓取/XML；引擎不能表达的过滤差异需逐源确认。

## 实例恢复、约束与故障

引擎instance/account/feed/entry不可跨实例直接复用。恢复先校验两库版本/实例/映射hash；重新建引擎需单独再绑定ADR/恢复流程，不把数字碰撞当同一条目。物理Feed取消最后引用仅暂停；取消注册中操作按最终引用数收敛。

SQLite不具备可依赖的行级select_for_update语义：唯一约束+短事务+CAS/lease epoch实现并发，busy有限重试；网络不持写事务。正文、映射及拒收持久化先于cursor；DB失败不可推进。引擎历史删掉、本地停机超保留期且无备份时标不可恢复缺口，不能承诺RSS补齐所有历史。

## 副本验收数据集

空库、0051旧库、相同URL不同Feed/政策、同名不同Feed、长URL/缺正文/legacy/complete/available、暂停和注册中退订、A/B/匿名、私人共享译文、已运行后台任务、全部上述用户FK、ReadingDay、动态SourceConfig、owner晚写、实例重建数字复用均需fixture。

逐表计数、原PK/FK集合、正文和译文hash、阅读/收藏/组/研究可见性、源选择覆盖分别校验。真实数据证据只保存聚合/不可逆hash和受控工件位置，不把用户正文/Token/活动库提交Git。
