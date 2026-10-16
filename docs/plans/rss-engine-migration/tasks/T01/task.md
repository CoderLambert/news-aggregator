# T01：验证 RSSHub HTTPS 网关与受支持路由

状态：PLANNED / 等待规划审核；实现尚未开始。基线：`878b69081f8d5b3ae965bcf1c855390b059caa33`。

## 目标、范围和合同

验证受保护公网HTTPS回流、证书、BasicAuth、路由前缀及无浏览器/Redis的标准RSSHub。GitHub Trending所需服务端Token由部署方提供；缺失即BLOCKED，不以模板HTTP200替代有效Feed。

修改范围：tests/rss_engine_contract/test_rsshub_gateway.py；网关证据。目标追踪：ARCHITECTURE.md 第 10 节；详细合同 [C01](../../INTERFACE-CONTRACTS.md#c01)、[C03](../../INTERFACE-CONTRACTS.md#c03)、[C07](../../INTERFACE-CONTRACTS.md#c07)；附加决议见 [ARCHITECTURE-DECISIONS.md](../../ARCHITECTURE-DECISIONS.md)。

## 依赖与阻塞

前置：[T00](../T00/task.md)。前置任务必须验收并合并，基线以主控记录的集成 SHA 为准，不能仅依赖未合并分支。RSSHub相关前置只适用于实际RSSHub来源，native路径按DEPENDENCIES中的条件门禁执行。

阻塞：规划未审核；对应 C01/C03/C07 未冻结；缺隔离运行环境/来源样本/服务端凭据则实际验收 BLOCKED。发现新模型需求或合同冲突时，提交独立ADR并暂停依赖任务，不在本任务顺带改模型或增加服务。

## 实施与并发边界

从前置合并后的已验收 SHA 建立 `rss/t01` 分支，只包含本任务。互斥资源：`gateway-probe`。schema/model/migration仅T05所有，后续新DDL先立独立合同变更任务；API全局路由/公共types由主控串行集成，不允许多任务同时修改。最多3项开发任务，同文件重叠即串行。

先确认 tests.md 的验收fixture和反例，再实现；不得新增爬虫/XML解析器/原网页提取器/通用任务平台。任务级专项通过后做独立审核；P0/P1修复后才提交合并。

## 独立验收

1. FETCHER_ALLOW_PRIVATE_NETWORKS=0，私网访问禁用且防护保持启用且直接私网Feed被拒。
2. 凭据不发给正文目标、不出现在DTO/OPML/日志。
3. 真实Trending参数实例返回有效条目且对象被标readme/repository，不声称新闻全文。
4. 失败只阻塞RSSHub来源，原生RSS可独立验收。

5. 网关认证只绑定精确HTTPS origin+批准route；相似域名/userinfo/端口/编码路径/跨源跳转均失败关闭。

## 交付、审核和回滚

实现、测试及必要的实际运行证据归档于本目录的 report.md（大日志使用校验和及受控工件链接）。记录提交/PR/CI、基线与目标SHA、独立审核人和问题修复SHA。满足全部完成定义后才改DONE；缺真实条件不能PASS。

回滚：优先关闭本任务新增入口或回退本PR的应用行为，保留兼容字段、已接收数据和用户关系；不执行reverse migration/生产恢复。 通用审核、批次回归和生产闸门见 [TASKS.md](../../TASKS.md) 与 [ROLLBACK.md](../../ROLLBACK.md)。
