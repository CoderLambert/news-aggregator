# T00：验证 Miniflux 原生引擎合同并锁定版本

状态：PLANNED / 等待规划审核；实现尚未开始。基线：`878b69081f8d5b3ae965bcf1c855390b059caa33`。

## 目标、范围和合同

在一次隔离容器实验中验证候选 Miniflux 2.3.3、兼容 PG、官方 SDK；锁定可重现版本/digest、响应限制及超时。留存原生全文、摘要提取、失败回退、受限源、分页、清理、凭据与重定向证据。不得用本文源码核验代替运行。

修改范围：tests/rss_engine_contract/；版本证据；不改产品实现。目标追踪：ARCHITECTURE.md 第 10 节；详细合同 [C01](../../INTERFACE-CONTRACTS.md#c01)、[C03](../../INTERFACE-CONTRACTS.md#c03)、[C06](../../INTERFACE-CONTRACTS.md#c06)；附加决议见 [ARCHITECTURE-DECISIONS.md](../../ARCHITECTURE-DECISIONS.md)。

## 依赖与阻塞

前置：规划审核及接口冻结，无开发前置。前置任务必须验收并合并，基线以主控记录的集成 SHA 为准，不能仅依赖未合并分支。RSSHub相关前置只适用于实际RSSHub来源，native路径按DEPENDENCIES中的条件门禁执行。

阻塞：规划未审核；对应 C01/C03/C06 未冻结；缺隔离运行环境/来源样本/服务端凭据则实际验收 BLOCKED。发现新模型需求或合同冲突时，提交独立ADR并暂停依赖任务，不在本任务顺带改模型或增加服务。

## 实施与并发边界

从前置合并后的已验收 SHA 建立 `rss/t00` 分支，只包含本任务。互斥资源：`engine-probe`、`test-harness`。schema/model/migration仅T05所有，后续新DDL先立独立合同变更任务；API全局路由/公共types由主控串行集成，不允许多任务同时修改。最多3项开发任务，同文件重叠即串行。

先确认 tests.md 的验收fixture和反例，再实现；不得新增爬虫/XML解析器/原网页提取器/通用任务平台。任务级专项通过后做独立审核；P0/P1修复后才提交合并。

## 独立验收

1. 证明 read/unread 都按显式90天配置且按created_at清理；实际保留记录仍全部可枚举。
2. 证明普通refresh与单篇fetch-content差异、SDK持久化扩展可行。
3. 受控原生全文/提取失败样本各5–10篇，记录分母、原文/Feed/采集时刻及人工判断。
4. SSRF IPv4/IPv6/DNS/重定向和响应大小边界通过；digest通过实际拉取核实。

5. SDK最小受限transport通过slow-drip/巨大JSON/压缩膨胀；不能只让future超时而底层仍占槽。

## 交付、审核和回滚

实现、测试及必要的实际运行证据归档于本目录的 report.md（大日志使用校验和及受控工件链接）。记录提交/PR/CI、基线与目标SHA、独立审核人和问题修复SHA。满足全部完成定义后才改DONE；缺真实条件不能PASS。

回滚：优先关闭本任务新增入口或回退本PR的应用行为，保留兼容字段、已接收数据和用户关系；不执行reverse migration/生产恢复。 通用审核、批次回归和生产闸门见 [TASKS.md](../../TASKS.md) 与 [ROLLBACK.md](../../ROLLBACK.md)。
