# T17：通过引擎发现网址中的 Feed 候选

状态：PLANNED / 等待规划审核；实现尚未开始。基线：`878b69081f8d5b3ae965bcf1c855390b059caa33`。

## 目标、范围和合同

识别域名/网站/FeedURL，拒绝凭据私网危险参数；POST创建有配额的discover操作，缓存可200、执行中202。由引擎发现，返回0/1/多候选与过期的用户绑定token，不自行解析XML/HTML。

修改范围：backend/api/rss/discovery.py；resolve endpoint。目标追踪：ARCHITECTURE.md 第 7–8 节；详细合同 [C03](../../INTERFACE-CONTRACTS.md#c03)、[C05](../../INTERFACE-CONTRACTS.md#c05)、[C07](../../INTERFACE-CONTRACTS.md#c07)；附加决议见 [ARCHITECTURE-DECISIONS.md](../../ARCHITECTURE-DECISIONS.md)。

## 依赖与阻塞

前置：[T04](../T04/task.md)、[T08](../T08/task.md)、[T11](../T11/task.md)。前置任务必须验收并合并，基线以主控记录的集成 SHA 为准，不能仅依赖未合并分支。RSSHub相关前置只适用于实际RSSHub来源，native路径按DEPENDENCIES中的条件门禁执行。

阻塞：规划未审核；对应 C03/C05/C07 未冻结；缺测试依赖/必要运行条件则 BLOCKED。发现新模型需求或合同冲突时，提交独立ADR并暂停依赖任务，不在本任务顺带改模型或增加服务。

## 实施与并发边界

从前置合并后的已验收 SHA 建立 `rss/t17` 分支，只包含本任务。互斥资源：`discovery-api`。schema/model/migration仅T05所有，后续新DDL先立独立合同变更任务；API全局路由/公共types由主控串行集成，不允许多任务同时修改。最多3项开发任务，同文件重叠即串行。

先确认 tests.md 的验收fixture和反例，再实现；不得新增爬虫/XML解析器/原网页提取器/通用任务平台。任务级专项通过后做独立审核；P0/P1修复后才提交合并。

## 独立验收

1. HTTPS规范化保留业务query和大小写路径，重定向/DNS由引擎安全策略约束。
2. 0/1/多Feed、取消/超时/限额错误可操作，不虚构成功。
3. 无订阅时候选preview仅用已有缓存，不注册临时Feed采文章。
4. 200/202/404/413/429 DTO与前端契约一致。

## 交付、审核和回滚

实现、测试及必要的实际运行证据归档于本目录的 report.md（大日志使用校验和及受控工件链接）。记录提交/PR/CI、基线与目标SHA、独立审核人和问题修复SHA。满足全部完成定义后才改DONE；缺真实条件不能PASS。

回滚：优先关闭本任务新增入口或回退本PR的应用行为，保留兼容字段、已接收数据和用户关系；不执行reverse migration/生产恢复。 通用审核、批次回归和生产闸门见 [TASKS.md](../../TASKS.md) 与 [ROLLBACK.md](../../ROLLBACK.md)。
