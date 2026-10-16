# T32：瘦身依赖并完成唯一部署入口

状态：PLANNED / 等待规划审核；实现尚未开始。基线：`878b69081f8d5b3ae965bcf1c855390b059caa33`。

## 目标、范围和合同

T35已交付轻量rss-sync运行时，本任务验证删除旧栈后的最终镜像并整合唯一部署入口；移除Scrapy/scrapy-playwright/feedparser和浏览器采集依赖，保留AI模型/Chroma。更新本机/容器/override/CI/README全部入口，不把首次轻量构建拖到本阶段。

修改范围：Dockerfile/requirements/rss-sync轻量target/Compose/CI/README。目标追踪：ARCHITECTURE.md 第 10 节；详细合同 [C01](../../INTERFACE-CONTRACTS.md#c01)、[C10](../../INTERFACE-CONTRACTS.md#c10)、[C11](../../INTERFACE-CONTRACTS.md#c11)；附加决议见 [ARCHITECTURE-DECISIONS.md](../../ARCHITECTURE-DECISIONS.md)。

## 依赖与阻塞

前置：[T31](../T31/task.md)。前置任务必须验收并合并，基线以主控记录的集成 SHA 为准，不能仅依赖未合并分支。RSSHub相关前置只适用于实际RSSHub来源，native路径按DEPENDENCIES中的条件门禁执行。

阻塞：规划未审核；对应 C01/C10/C11 未冻结；缺测试依赖/必要运行条件则 BLOCKED。发现新模型需求或合同冲突时，提交独立ADR并暂停依赖任务，不在本任务顺带改模型或增加服务。

## 实施与并发边界

从前置合并后的已验收 SHA 建立 `rss/t32` 分支，只包含本任务。互斥资源：`compose`、`release-scripts`、`runtime-config`、`dependency-manifest`。schema/model/migration仅T05所有，后续新DDL先立独立合同变更任务；API全局路由/公共types由主控串行集成，不允许多任务同时修改。最多3项开发任务，同文件重叠即串行。

先确认 tests.md 的验收fixture和反例，再实现；不得新增爬虫/XML解析器/原网页提取器/通用任务平台。任务级专项通过后做独立审核；P0/P1修复后才提交合并。

## 独立验收

1. sync导入和镜像中无torch/embedding/browser，app AI仍运行。
2. 所有支持Compose/本机入口重启均不启动旧角色。
3. manifest新旧解析和CI测试根匹配，镜像digest可追溯。
4. license/SBOM/依赖扫描与文档一致，无额外服务。

## 交付、审核和回滚

实现、测试及必要的实际运行证据归档于本目录的 report.md（大日志使用校验和及受控工件链接）。记录提交/PR/CI、基线与目标SHA、独立审核人和问题修复SHA。满足全部完成定义后才改DONE；缺真实条件不能PASS。

回滚：优先关闭本任务新增入口或回退本PR的应用行为，保留兼容字段、已接收数据和用户关系；不执行reverse migration/生产恢复。 通用审核、批次回归和生产闸门见 [TASKS.md](../../TASKS.md) 与 [ROLLBACK.md](../../ROLLBACK.md)。
