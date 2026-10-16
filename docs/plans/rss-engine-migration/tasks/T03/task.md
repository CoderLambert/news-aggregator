# T03：交付两库备份恢复工具与严格发布协议

状态：PLANNED / 等待规划审核；实现尚未开始。基线：`878b69081f8d5b3ae965bcf1c855390b059caa33`。

## 目标、范围和合同

扩展严格版本化manifest表示RSS角色、两库身份及schema拒绝规则；把rss-sync等全部writer纳入停写。实现C09已定义的CLI，使用SQLite online backup和PG原生dump/restore。此任务仅交付工具与隔离恢复证据，不封存生产回滚基点；带完整fence的兼容基点必须等T25后由T36封存。

修改范围：scripts/deploy/；ops/rss/恢复合同；release manifest。目标追踪：ARCHITECTURE.md 第 10 节；详细合同 [C01](../../INTERFACE-CONTRACTS.md#c01)、[C02](../../INTERFACE-CONTRACTS.md#c02)、[C09](../../INTERFACE-CONTRACTS.md#c09)；附加决议见 [ARCHITECTURE-DECISIONS.md](../../ARCHITECTURE-DECISIONS.md)。

## 依赖与阻塞

前置：[T02](../T02/task.md)、[T05](../T05/task.md)、[T11](../T11/task.md)。前置任务必须验收并合并，基线以主控记录的集成 SHA 为准，不能仅依赖未合并分支。RSSHub相关前置只适用于实际RSSHub来源，native路径按DEPENDENCIES中的条件门禁执行。

阻塞：规划未审核；对应 C01/C02/C09 未冻结；缺测试依赖/必要运行条件则 BLOCKED。发现新模型需求或合同冲突时，提交独立ADR并暂停依赖任务，不在本任务顺带改模型或增加服务。

## 实施与并发边界

从前置合并后的已验收 SHA 建立 `rss/t03` 分支，只包含本任务。互斥资源：`compose`、`release-scripts`、`runtime-config`。schema/model/migration仅T05所有，后续新DDL先立独立合同变更任务；API全局路由/公共types由主控串行集成，不允许多任务同时修改。最多3项开发任务，同文件重叠即串行。

先确认 tests.md 的验收fixture和反例，再实现；不得新增爬虫/XML解析器/原网页提取器/通用任务平台。任务级专项通过后做独立审核；P0/P1修复后才提交合并。

## 独立验收

1. 隔离真实备份/恢复两库、凭据引用和绑定校验，对账后身份一致；生产回滚基点尚不存在。
2. 更新/回滚失败关闭writer，未批准schema拒绝，不做静默reverse migration。
3. 恢复点及之后写入损失被量化，普通回滚不恢复数据库。
4. 旧manifest仍验证；删除阶段不再强制启动crawler。

## 交付、审核和回滚

实现、测试及必要的实际运行证据归档于本目录的 report.md（大日志使用校验和及受控工件链接）。记录提交/PR/CI、基线与目标SHA、独立审核人和问题修复SHA。满足全部完成定义后才改DONE；缺真实条件不能PASS。

回滚：优先关闭本任务新增入口或回退本PR的应用行为，保留兼容字段、已接收数据和用户关系；不执行reverse migration/生产恢复。 通用审核、批次回归和生产闸门见 [TASKS.md](../../TASKS.md) 与 [ROLLBACK.md](../../ROLLBACK.md)。
