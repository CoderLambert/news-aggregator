# T27：完成预生产真实来源与浏览器联合验收

状态：PLANNED / 等待规划审核；实现尚未开始。基线：`878b69081f8d5b3ae965bcf1c855390b059caa33`。

## 目标、范围和合同

选择架构13.1各类真实样本，不改生产；核对DEV.to8555来源须授权只读副本识别URL，不能猜。按类别分别统计完整性/可读性/格式/时延，无浏览器访问时先后台采集再首访。

修改范围：隔离预生产的真实来源和浏览器证据。目标追踪：ARCHITECTURE.md 第 5 节；详细合同 [C04](../../INTERFACE-CONTRACTS.md#c04)、[C05](../../INTERFACE-CONTRACTS.md#c05)、[C06](../../INTERFACE-CONTRACTS.md#c06)、[C07](../../INTERFACE-CONTRACTS.md#c07)、[C11](../../INTERFACE-CONTRACTS.md#c11)；附加决议见 [ARCHITECTURE-DECISIONS.md](../../ARCHITECTURE-DECISIONS.md)。

## 依赖与阻塞

前置：[T26](../T26/task.md)。前置任务必须验收并合并，基线以主控记录的集成 SHA 为准，不能仅依赖未合并分支。RSSHub相关前置只适用于实际RSSHub来源，native路径按DEPENDENCIES中的条件门禁执行。

阻塞：规划未审核；对应 C04/C05/C06/C07/C11 未冻结；缺隔离运行环境/来源样本/服务端凭据则实际验收 BLOCKED。发现新模型需求或合同冲突时，提交独立ADR并暂停依赖任务，不在本任务顺带改模型或增加服务。

## 实施与并发边界

从前置合并后的已验收 SHA 建立 `rss/t27` 分支，只包含本任务。互斥资源：`staging-acceptance`。schema/model/migration仅T05所有，后续新DDL先立独立合同变更任务；API全局路由/公共types由主控串行集成，不允许多任务同时修改。最多3项开发任务，同文件重叠即串行。

先确认 tests.md 的验收fixture和反例，再实现；不得新增爬虫/XML解析器/原网页提取器/通用任务平台。任务级专项通过后做独立审核；P0/P1修复后才提交合并。

## 独立验收

1. 发布者/Feed/条目/News四身份可追溯；缺来源明确BLOCKED。
2. 安全/串用户/错误覆盖/代码改写均0；经确认原生全文样本完整保留。
3. 目录p95≤500ms、引擎落库到可见p95≤60秒受控负载实测。
4. 普通准入文章90%作为待审核产品目标，分母固定且失败不移除。

## 交付、审核和回滚

实现、测试及必要的实际运行证据归档于本目录的 report.md（大日志使用校验和及受控工件链接）。记录提交/PR/CI、基线与目标SHA、独立审核人和问题修复SHA。满足全部完成定义后才改DONE；缺真实条件不能PASS。

回滚：优先关闭本任务新增入口或回退本PR的应用行为，保留兼容字段、已接收数据和用户关系；不执行reverse migration/生产恢复。 通用审核、批次回归和生产闸门见 [TASKS.md](../../TASKS.md) 与 [ROLLBACK.md](../../ROLLBACK.md)。
