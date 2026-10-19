# T12 个人 AI 使用记录实施记录

基线 main `f5a1b4b`。

- 新业务 AICallAttempt 仅记录 owner、用途、模型、时间、状态、延迟和可知输入/输出 Token，无新闻全文、原始 prompt/response、API Key 或原始错误。
- 共用 complete_with_usage 在文章问答、全文翻译各分段、深研每一模型轮次、问题推荐的实际 SDK create 边界创建一次记录。任何失败均不因统计重发；完成统计写入失败仅留下未知记录，不丢弃成功模型输出。
- 流式请求显式 include_usage，沿用已有 Proxy 的原生 usage/stop guard。无 usage、断线或未知结果保留 NULL；真实 0 保留 0。未完成记录只读展示为未知，不在 GET 中修复或重派发。
- 新 owner-only GET /api/me/ai/usage/ 结合现有 T02 探针记录与新业务账目，not_sent 不计调用；累计已知 token/未知次数 + 最近 50/最多 100 条，无虚构历史回填或费用/余额估算。
- 设置页使用 viewer-scoped Query key，切换用户立即移除旧数据，刷新仅 GET。

验证：typecheck、相关前端 16 项和生产 build PASS。实际统计函数隔离执行确认一次发送/一次账目、未知与真实 0、流中断、关闭不重复记录及用途不匹配拒绝 PASS；不是 Django/数据库验证。后端回归 NOT_RUN（pytest/PyYAML 缺失），真实供应商/生产迁移/部署/浏览器 UAT NOT_RUN。本批集中 CI，不重复启动全量门禁。

0070 增加账目表，未执行生产迁移。回退代码可撤销入口与统计接线，保留新增表，不改变既有 T02 探针数据。
