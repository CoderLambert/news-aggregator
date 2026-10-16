# ADR-007：以最小扩展持久修复单篇正文

状态：修订提案，等待规划审核；用户已确认的产品语义保持。本文件不授权生产切换、恢复或删除数据。

普通 Feed refresh 不承诺修复旧正文。官方 SDK 未暴露 update_content 时，允许仅扩展固定引擎 fetch-content?update_content=true 并重新 GET 核对；不请求发布者或自建抓取器。

修复是显式 POST 入队的独立动作，与刷新分开；页面 GET/首访/预览不调用副作用引擎 GET。执行前及提交时检查用户访问和最新政策，未知结果先核对。

删除旧提案强制的 TransportRequest/TransportResult、绝对 deadline/可取消 I/O 框架。采用成熟 HTTP timeout、分页、有限重试、资源限制和必要的小型响应边界封装；不将 socket timeout/future 超时称作总期限/真实取消，卡死进程通过监督终止并按租约恢复。T04 证明所选边界实际有效；未解决运行风险阻塞相关上线，不冻结纯转换/目录开发。

T00/T04/T08 验证真正持久化、未知结果核对、限额/脱敏及授权。单篇修复失败不改变架构方向。

事实依据：[BASELINE-AUDIT.md](../BASELINE-AUDIT.md)、[OPERATIONS-AUDIT.md](../OPERATIONS-AUDIT.md)、[UPSTREAM-VERIFICATION.md](../UPSTREAM-VERIFICATION.md)。实施入口：[接口合同](../INTERFACE-CONTRACTS.md)、[任务清单](../TASKS.md)、[验收矩阵](../ACCEPTANCE-MATRIX.md)。
