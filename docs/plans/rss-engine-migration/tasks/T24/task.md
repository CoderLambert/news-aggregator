# T24：盘点来源覆盖差异并形成逐源迁移清单

状态：PLANNED / 等待规划审核；实现尚未开始。基线：`878b69081f8d5b3ae965bcf1c855390b059caa33`。

## 目标、范围和合同

先静态盘点POLICIES/sector/0051及endpoint，再在获授权的备份副本只读统计真实SourceConfig/用户/正文/关系。每源记录原选题规则、候选Feed、类型/政策、PK映射、差异和阻塞。禁止将候选当可迁移证明。

修改范围：迁移清单/来源fixture/选择规则对照；不改DB。目标追踪：ARCHITECTURE.md 第 7 节；详细合同 [C02](../../INTERFACE-CONTRACTS.md#c02)、[C05](../../INTERFACE-CONTRACTS.md#c05)、[C11](../../INTERFACE-CONTRACTS.md#c11)；附加决议见 [ARCHITECTURE-DECISIONS.md](../../ARCHITECTURE-DECISIONS.md)。

## 依赖与阻塞

前置：规划审核及接口冻结，无开发前置。前置任务必须验收并合并，基线以主控记录的集成 SHA 为准，不能仅依赖未合并分支。RSSHub相关前置只适用于实际RSSHub来源，native路径按DEPENDENCIES中的条件门禁执行。

阻塞：规划未审核；对应 C02/C05/C11 未冻结；缺测试依赖/必要运行条件则 BLOCKED。发现新模型需求或合同冲突时，提交独立ADR并暂停依赖任务，不在本任务顺带改模型或增加服务。

## 实施与并发边界

从前置合并后的已验收 SHA 建立 `rss/t24` 分支，只包含本任务。互斥资源：`source-inventory`。schema/model/migration仅T05所有，后续新DDL先立独立合同变更任务；API全局路由/公共types由主控串行集成，不允许多任务同时修改。最多3项开发任务，同文件重叠即串行。

先确认 tests.md 的验收fixture和反例，再实现；不得新增爬虫/XML解析器/原网页提取器/通用任务平台。任务级专项通过后做独立审核；P0/P1修复后才提交合并。

## 独立验收

1. DEV.to标签热度、HN排名与不同对象、医疗HTML-only逐项列差异。
2. 每个Source含source_id/旧owner/新模式或停更原因，不能按名字强配。
3. 原库计数与FK/hash不变量记录；无副本时明确BLOCKED。
4. 实例化T29-SOURCE-ID单源工单清单，动态源不得遗漏。

## 交付、审核和回滚

实现、测试及必要的实际运行证据归档于本目录的 report.md（大日志使用校验和及受控工件链接）。记录提交/PR/CI、基线与目标SHA、独立审核人和问题修复SHA。满足全部完成定义后才改DONE；缺真实条件不能PASS。

回滚：优先关闭本任务新增入口或回退本PR的应用行为，保留兼容字段、已接收数据和用户关系；不执行reverse migration/生产恢复。 通用审核、批次回归和生产闸门见 [TASKS.md](../../TASKS.md) 与 [ROLLBACK.md](../../ROLLBACK.md)。
