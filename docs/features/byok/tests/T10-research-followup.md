# T10 研究续问与安全恢复实施记录

基线：main `988c4c4`；本次使用当前 T09 API、持久 run/event、owner/model/credential 围栏。

- 会话持久化 `native_continuation`（schema 1 / openai-chat-completions-v1），保留同模型 reasoning_content 与完整工具轮次。前端仅接收 user/assistant 可见文本和无密钥模型标识。
- 每次续问要求显式 model_config_id + consent:true；只能使用会话原模型，重新检查 owner、模型能力、凭据 epoch/version 与所有来源证据。
- 完成消息、native 状态和终态在现有 run-token/lease CAS 事务中写入；旧 Worker 不能覆盖新运行。断线 GET/SSE 不创建或重新派发任务；不重试结果未知的上游请求。
- 老会话无安全 native 状态时继续可读；不会猜测/跨供应商移植原生续接，可新建研究。

验证：typecheck PASS；原前端 ResearchPanel/API 30 项 PASS；Python 变更 AST 语法与 diff 空白检查 PASS。新增纯 continuation/owner/model 负例保留在 test_research_byok.py；本地后端 pytest 依赖缺失，数据库回归 NOT_RUN。新增 UI 续问场景 1 PASS / 17 未选择；生产前端 build PASS。原生 helper 的实际函数隔离执行确认可见/私有分离、模型与协议变化拒绝通过；不代表 Django/数据库验证。生产迁移、真实供应商、浏览器人工 UAT NOT_RUN。

回滚：回退本次业务代码即可停止续问入口；0068 为增加 JSON 字段，无须删除数据字段。没有执行生产迁移。
