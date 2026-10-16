# T14：让翻译、问答、研究和 TTS 只消费授权内容

状态：PLANNED / 等待规划审核；实现尚未开始。基线：`878b69081f8d5b3ae965bcf1c855390b059caa33`。

## 目标、范围和合同

落实ADR-002：文章翻译不抓中文外链；研究保持既有搜索工具但网页正文仅本地缓存，未收录明确返回摘要和链接。移除聊天/推荐问题/研究隐式排旧队列。保持历史译文hash与用户连接边界。

修改范围：views/translation/shared_translations/speech/research/read helpers。目标追踪：ARCHITECTURE.md 第 5 节；详细合同 [C04](../../INTERFACE-CONTRACTS.md#c04)、[C05](../../INTERFACE-CONTRACTS.md#c05)、[C10](../../INTERFACE-CONTRACTS.md#c10)；附加决议见 [ARCHITECTURE-DECISIONS.md](../../ARCHITECTURE-DECISIONS.md)。

## 依赖与阻塞

前置：[T10](../T10/task.md)、[T11](../T11/task.md)、[T13](../T13/task.md)。前置任务必须验收并合并，基线以主控记录的集成 SHA 为准，不能仅依赖未合并分支。RSSHub相关前置只适用于实际RSSHub来源，native路径按DEPENDENCIES中的条件门禁执行。

阻塞：规划未审核；对应 C04/C05/C10 未冻结；缺测试依赖/必要运行条件则 BLOCKED。发现新模型需求或合同冲突时，提交独立ADR并暂停依赖任务，不在本任务顺带改模型或增加服务。

## 实施与并发边界

从前置合并后的已验收 SHA 建立 `rss/t14` 分支，只包含本任务。互斥资源：`ai-readers`、`read-api`。schema/model/migration仅T05所有，后续新DDL先立独立合同变更任务；API全局路由/公共types由主控串行集成，不允许多任务同时修改。最多3项开发任务，同文件重叠即串行。

先确认 tests.md 的验收fixture和反例，再实现；不得新增爬虫/XML解析器/原网页提取器/通用任务平台。任务级专项通过后做独立审核；P0/P1修复后才提交合并。

## 独立验收

1. available携带scope/revision/hash/completeness进入模型，摘要不伪称全文。
2. 正文变化时旧异步结果CAS不能发布为当前，历史译文不物理抹除。
3. TTS/研究/推荐问题/问答全链路无旧Provider或抓取副作用。
4. 现有标题摘要向量索引策略保持，不为换RSS自动触发付费AI。

## 交付、审核和回滚

实现、测试及必要的实际运行证据归档于本目录的 report.md（大日志使用校验和及受控工件链接）。记录提交/PR/CI、基线与目标SHA、独立审核人和问题修复SHA。满足全部完成定义后才改DONE；缺真实条件不能PASS。

回滚：优先关闭本任务新增入口或回退本PR的应用行为，保留兼容字段、已接收数据和用户关系；不执行reverse migration/生产恢复。 通用审核、批次回归和生产闸门见 [TASKS.md](../../TASKS.md) 与 [ROLLBACK.md](../../ROLLBACK.md)。
