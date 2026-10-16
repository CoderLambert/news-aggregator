# T36：封存具备完整来源隔离的兼容回滚版本

状态：PLANNED / 等待规划审核；未实现。目标合同：[INTERFACE-CONTRACTS.md](../../INTERFACE-CONTRACTS.md) C02、C04、C05、C09、C11。架构目标：轻量运行及安全兼容回滚。

## 目标与技术方案

在T25完整旧入口fence实现、T13新状态阅读通过后，封存与目标schema相同、能读available/新ACL且保留owner epoch的过渡镜像。T03只提供工具；本任务才产生供T26/T28使用的真实兼容SHA/digest/manifest。不引入新DDL。

范围：兼容release manifest/镜像清单与fence演练证据。前置：[T03](../T03/task.md)、[T13](../T13/task.md)、[T25](../T25/task.md)。必须从已验收合并SHA建独立分支 `rss/t36`，不依未合并接口。资源锁：release-scripts、compatibility-seal；共同文件串行，最多3项开发，不修改T05所有的DDL。

## 验收与阻塞

1. 兼容镜像读取legacy/complete/available和个人源授权正确。
2. 真实旧任务开始于切换前、完成于回滚后时仍被fence拒绝。
3. manifest schema精确匹配、服务角色符合暂停owner，不能无条件启旧crawler。
4. 隔离应用回滚保留新News/译文历史/用户关系；记录SHA/digest/CI与恢复证据。

缺隔离镜像/实际运行证据即BLOCKED，不以单测或mock代替。先确认tests.md，独立审核无P0/P1、CI/PR/证据齐全再DONE。report.md填写真实SHA和输出；当前NOT_RUN。出现新合同问题先ADR审核。

回滚：停新增运行入口或使用已测兼容版本，保留数据；不reverse migration、不自动恢复生产库。详见[ROLLBACK.md](../../ROLLBACK.md)。
