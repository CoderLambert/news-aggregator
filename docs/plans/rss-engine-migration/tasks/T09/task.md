# T09：同步新条目并持久化每页检查点

状态：PLANNED / 等待规划审核；实现尚未开始。基线：`878b69081f8d5b3ae965bcf1c855390b059caa33`。

## 目标、范围和合同

新ID按asc分页、固定上界、回读窗口。每条先提交映射/正文/拒绝记录，每页完成后再提交cursor；临时DB故障不永久拒收。与控制循环共享单进程，SQLite短写。

修改范围：backend/api/rss/sync.py；rss_sync_worker。目标追踪：ARCHITECTURE.md 第 7 节；详细合同 [C02](../../INTERFACE-CONTRACTS.md#c02)、[C06](../../INTERFACE-CONTRACTS.md#c06)；附加决议见 [ARCHITECTURE-DECISIONS.md](../../ARCHITECTURE-DECISIONS.md)。

## 依赖与阻塞

前置：[T07](../T07/task.md)、[T08](../T08/task.md)。前置任务必须验收并合并，基线以主控记录的集成 SHA 为准，不能仅依赖未合并分支。RSSHub相关前置只适用于实际RSSHub来源，native路径按DEPENDENCIES中的条件门禁执行。

阻塞：规划未审核；对应 C02/C06 未冻结；缺测试依赖/必要运行条件则 BLOCKED。发现新模型需求或合同冲突时，提交独立ADR并暂停依赖任务，不在本任务顺带改模型或增加服务。

## 实施与并发边界

从前置合并后的已验收 SHA 建立 `rss/t09` 分支，只包含本任务。互斥资源：`sync-worker`、`worker-entrypoint`。schema/model/migration仅T05所有，后续新DDL先立独立合同变更任务；API全局路由/公共types由主控串行集成，不允许多任务同时修改。最多3项开发任务，同文件重叠即串行。

先确认 tests.md 的验收fixture和反例，再实现；不得新增爬虫/XML解析器/原网页提取器/通用任务平台。任务级专项通过后做独立审核；P0/P1修复后才提交合并。

## 独立验收

1. 写入后丢响应、进程kill、CAS失败、数据库busy都可重放且不漏记。
2. 旧发布日期的新ID正常导入；不依赖read/star或changed_at。
3. 超长URL/标题等不兼容值记录拒绝而非静默截断。
4. 运行无发布者HTTP/Feed网络；实例身份不匹配即停止。

## 交付、审核和回滚

实现、测试及必要的实际运行证据归档于本目录的 report.md（大日志使用校验和及受控工件链接）。记录提交/PR/CI、基线与目标SHA、独立审核人和问题修复SHA。满足全部完成定义后才改DONE；缺真实条件不能PASS。

回滚：优先关闭本任务新增入口或回退本PR的应用行为，保留兼容字段、已接收数据和用户关系；不执行reverse migration/生产恢复。 通用审核、批次回归和生产闸门见 [TASKS.md](../../TASKS.md) 与 [ROLLBACK.md](../../ROLLBACK.md)。
