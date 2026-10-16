# T29 来源结果清单与例外工单

普通来源使用同一份 manifest 和下表；不要求每个 source_id 创建 task/tests/report 或 PR。共用物理 Feed 的旧来源按最小切换组执行，仍逐来源记录。

| 字段 | 必需内容 |
| --- | --- |
| 身份与分组 | source_id、旧 key、binding/instance/account、共享切换组及关联来源集合 |
| 产品差异 | 旧选择规则、新 Feed/标准路由、对象类型、覆盖差异、模式/reading_policy |
| 数据与访问 | 原 PK/FK/正文/译文及用户关系聚合 hash、publication、主写接管清单 |
| 执行目标 | expected owner/epoch、目标 SHA/digest、窗口、批准的来源集合、备份/已封存兼容版本 |
| 逐源结果 | 实际开始结束、owner/epoch/绑定核对、后台新条目/历史数据/覆盖结果、失败与暂停/恢复 |
| 复用证据 | 同版本 ACL、fencing、恢复和产品验收链接；相关代码/配置变化时重测影响项 |

试点可以是一个来源或最小共享组；先通过才扩大批准批次。source-cutover 执行串行，plan/verify 只读，apply 需显式执行和目标检查。停更保持原 public/personal，使用 owner=paused/pause_reason=unsupported。

特殊政策、路由配置差异或迁移失败才另开例外工单，记录具体风险、处理和复验；普通来源不重复完整两库 restore/公共权限测试。所有实际来源替代或明确停更后 T29 才完成，解除 T30 的停止旧栈前置。
