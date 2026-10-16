# ADR-004：统一采集模式与政策收敛

状态：修订提案，等待规划审核；用户已确认的产品语义保持。本文件不授权生产切换、恢复或删除数据。

用户已确认：一个物理 Feed 的模式由管理员/站点政策决定，V1 没有个人模式开关。取消个人订阅不能停止其他有效引用或 editorial_pin 的采集。

C03 补齐已有 Feed 的 update_feed_policy，复用官方 SDK update_feed，GET 核对 applied_policy_version。政策收紧先限制本地读取/操作并暂停绑定，旧版本修复取消、在途结果提交重验；不能声称禁用能撤回已发网络请求。按统一批准模式恢复，冲突未解决不启用。

T08 测政策变更中旧操作和响应丢失；T11 测即时授权；跨来源共享绑定的暂停/切换由 T25 验证。普通用户的 read/star/group 不写共享采集账号。

事实依据：[BASELINE-AUDIT.md](../BASELINE-AUDIT.md)、[OPERATIONS-AUDIT.md](../OPERATIONS-AUDIT.md)、[UPSTREAM-VERIFICATION.md](../UPSTREAM-VERIFICATION.md)。实施入口：[接口合同](../INTERFACE-CONTRACTS.md)、[任务清单](../TASKS.md)、[验收矩阵](../ACCEPTANCE-MATRIX.md)。
