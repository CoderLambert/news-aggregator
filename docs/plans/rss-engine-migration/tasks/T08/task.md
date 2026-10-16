# T08：执行持久控制意图与幂等引擎连接

状态：PLANNED / 等待规划审核；实现尚未开始。基线：`878b69081f8d5b3ae965bcf1c855390b059caa33`。

## 目标、范围和合同

短事务保存操作意图，事务外调用API。实现register/set_enabled/discover/refresh_feed/refetch_entry固定动作、租约/epoch、有限退避、超时核对；最后引用取消先暂停。不得保存任意代码或来源HTML。

修改范围：backend/api/rss/operations.py；rss_sync_worker初始壳。目标追踪：ARCHITECTURE.md 第 7 节；详细合同 [C02](../../INTERFACE-CONTRACTS.md#c02)、[C03](../../INTERFACE-CONTRACTS.md#c03)、[C05](../../INTERFACE-CONTRACTS.md#c05)；附加决议见 [ARCHITECTURE-DECISIONS.md](../../ARCHITECTURE-DECISIONS.md)。

## 依赖与阻塞

前置：[T04](../T04/task.md)、[T05](../T05/task.md)、[T35](../T35/task.md)。前置任务必须验收并合并，基线以主控记录的集成 SHA 为准，不能仅依赖未合并分支。RSSHub相关前置只适用于实际RSSHub来源，native路径按DEPENDENCIES中的条件门禁执行。

阻塞：规划未审核；对应 C02/C03/C05 未冻结；缺测试依赖/必要运行条件则 BLOCKED。发现新模型需求或合同冲突时，提交独立ADR并暂停依赖任务，不在本任务顺带改模型或增加服务。

## 实施与并发边界

从前置合并后的已验收 SHA 建立 `rss/t08` 分支，只包含本任务。互斥资源：`control-worker`、`worker-entrypoint`。schema/model/migration仅T05所有，后续新DDL先立独立合同变更任务；API全局路由/公共types由主控串行集成，不允许多任务同时修改。最多3项开发任务，同文件重叠即串行。

先确认 tests.md 的验收fixture和反例，再实现；不得新增爬虫/XML解析器/原网页提取器/通用任务平台。任务级专项通过后做独立审核；P0/P1修复后才提交合并。

## 独立验收

1. 20次同Feed并发注册只有一物理Feed/绑定。
2. 创建超时先枚举核对再重试；无法判断则unknown待核对。
3. 注册期间取消、A取消B仍引用、编辑固定引用都收敛正确。
4. 控制请求超时不持有SQLite写事务；最多2个在途任务且高优先短读不饿死。

## 交付、审核和回滚

实现、测试及必要的实际运行证据归档于本目录的 report.md（大日志使用校验和及受控工件链接）。记录提交/PR/CI、基线与目标SHA、独立审核人和问题修复SHA。满足全部完成定义后才改DONE；缺真实条件不能PASS。

回滚：优先关闭本任务新增入口或回退本PR的应用行为，保留兼容字段、已接收数据和用户关系；不执行reverse migration/生产恢复。 通用审核、批次回归和生产闸门见 [TASKS.md](../../TASKS.md) 与 [ROLLBACK.md](../../ROLLBACK.md)。
