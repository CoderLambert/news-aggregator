# T30：退出旧进程并验证重启不会复活

状态：PLANNED / 等待规划审核；实现尚未开始。基线：`878b69081f8d5b3ae965bcf1c855390b059caa33`。

## 目标、范围和合同

按清单停止crawler/full-content及宿主机cron/systemd，禁用不仅是功能flag。保留兼容镜像/manifest/备份；所有legacy源先迁移或批准停更。仓库入口清理与实际机器停运分别留证。

修改范围：Compose/cron/systemd/脚本的旧角色停运方案与获批执行。目标追踪：ARCHITECTURE.md 第 11 节；详细合同 [C11](../../INTERFACE-CONTRACTS.md#c11)、[C09](../../INTERFACE-CONTRACTS.md#c09)；附加决议见 [ARCHITECTURE-DECISIONS.md](../../ARCHITECTURE-DECISIONS.md)。

## 依赖与阻塞

前置：[T29](../T29/task.md)。前置任务必须验收并合并，基线以主控记录的集成 SHA 为准，不能仅依赖未合并分支。RSSHub相关前置只适用于实际RSSHub来源，native路径按DEPENDENCIES中的条件门禁执行。

阻塞：规划未审核；对应 C11/C09 未冻结；缺隔离运行环境/来源样本/服务端凭据则实际验收 BLOCKED。发现新模型需求或合同冲突时，提交独立ADR并暂停依赖任务，不在本任务顺带改模型或增加服务。

## 实施与并发边界

从前置合并后的已验收 SHA 建立 `rss/t30` 分支，只包含本任务。互斥资源：`production-writer`、`compose`、`release-scripts`。schema/model/migration仅T05所有，后续新DDL先立独立合同变更任务；API全局路由/公共types由主控串行集成，不允许多任务同时修改。最多3项开发任务，同文件重叠即串行。

先确认 tests.md 的验收fixture和反例，再实现；不得新增爬虫/XML解析器/原网页提取器/通用任务平台。任务级专项通过后做独立审核；P0/P1修复后才提交合并。

## 独立验收

1. 进程/定时器/容器清单旧角色为0，重启后仍0。
2. indexer/channel-worker/BYOK和新sync继续工作。
3. rollback不无条件启动旧crawler，停更源不会悄悄回退Spider。
4. 实际宿主操作逐项获批；无权限不能标PASS。

## 交付、审核和回滚

实现、测试及必要的实际运行证据归档于本目录的 report.md（大日志使用校验和及受控工件链接）。记录提交/PR/CI、基线与目标SHA、独立审核人和问题修复SHA。满足全部完成定义后才改DONE；缺真实条件不能PASS。

回滚：按 ROLLBACK.md，先暂停目标来源/全部写入，使用获批兼容版本；恢复旧调度另需授权，新Feed仅暂停。 通用审核、批次回归和生产闸门见 [TASKS.md](../../TASKS.md) 与 [ROLLBACK.md](../../ROLLBACK.md)。
