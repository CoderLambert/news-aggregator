# T04：封装官方 Miniflux SDK 与受控单篇修复

状态：PLANNED / 等待规划审核；实现尚未开始。基线：`878b69081f8d5b3ae965bcf1c855390b059caa33`。

## 目标、范围和合同

实现EngineAdapter协议与白名单DTO。固定API地址/Token；官方SDK优先，单篇修复只做最小API参数扩展 update_content=true 并重新GET，不重写Feed解析。统一超时、429、未知结果和脱敏异常。

修改范围：backend/api/rss/engine.py；专属依赖声明。目标追踪：ARCHITECTURE.md 第 7–8 节；详细合同 [C03](../../INTERFACE-CONTRACTS.md#c03)；附加决议见 [ARCHITECTURE-DECISIONS.md](../../ARCHITECTURE-DECISIONS.md)。

## 依赖与阻塞

前置：[T00](../T00/task.md)。前置任务必须验收并合并，基线以主控记录的集成 SHA 为准，不能仅依赖未合并分支。RSSHub相关前置只适用于实际RSSHub来源，native路径按DEPENDENCIES中的条件门禁执行。

阻塞：规划未审核；对应 C03 未冻结；缺测试依赖/必要运行条件则 BLOCKED。发现新模型需求或合同冲突时，提交独立ADR并暂停依赖任务，不在本任务顺带改模型或增加服务。

## 实施与并发边界

从前置合并后的已验收 SHA 建立 `rss/t04` 分支，只包含本任务。互斥资源：`engine-client`。schema/model/migration仅T05所有，后续新DDL先立独立合同变更任务；API全局路由/公共types由主控串行集成，不允许多任务同时修改。最多3项开发任务，同文件重叠即串行。

先确认 tests.md 的验收fixture和反例，再实现；不得新增爬虫/XML解析器/原网页提取器/通用任务平台。任务级专项通过后做独立审核；P0/P1修复后才提交合并。

## 独立验收

1. 发现/创建/枚举/暂停/刷新/条目读取全有契约fixture。
2. 刷新不伪称重新提取；fetch-content结果确实持久化且随后重新GET。
3. 恶意上游字段/凭据/媒体内部地址不透传。
4. 受限transport落实绝对deadline与整响应/解压后字节预算；slow-drip、巨大JSON、压缩膨胀被中止，远端未知结果进入核对。

## 交付、审核和回滚

实现、测试及必要的实际运行证据归档于本目录的 report.md（大日志使用校验和及受控工件链接）。记录提交/PR/CI、基线与目标SHA、独立审核人和问题修复SHA。满足全部完成定义后才改DONE；缺真实条件不能PASS。

回滚：优先关闭本任务新增入口或回退本PR的应用行为，保留兼容字段、已接收数据和用户关系；不执行reverse migration/生产恢复。 通用审核、批次回归和生产闸门见 [TASKS.md](../../TASKS.md) 与 [ROLLBACK.md](../../ROLLBACK.md)。
