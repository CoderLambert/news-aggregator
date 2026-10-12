# R0 · SQLite 后台翻译锁争用稳定性

> **READY FOR REVIEW（2026-10-12）**：定位并修复后台 worker 状态写入和并发任务创建两类 SQLite 共享缓存锁竞争。最新代码头 `64f9d10` 的本地完整回归及两次 GitHub Actions 全绿；证据见 [Test R0](../tests/R0-sqlite-stability.md)。独立 Draft PR 为 [#44](https://github.com/CoderLambert/news-aggregator/pull/44)。

| 属性 | 内容 |
| --- | --- |
| 前置任务 | 无；独立可靠性门槛 |
| 对应测试 | [Test R0](../tests/R0-sqlite-stability.md) |
| 影响范围 | ChatGPT 订阅翻译的提交校验、任务创建/附加、claim、进度、完成和失败状态数据库操作 |
| 真实 Provider | 不调用；测试 Provider 为本地 fake |

## 问题与修复

失败运行捕获到 SQLite 扩展错误码 `SQLITE_LOCKED_SHAREDCACHE`（262），具体 SQL 包括后台 worker 对 `api_chatgpttranslationtask` 的 queued→running 条件更新、最终保存前的任务 CAS 更新，以及 `start_or_get_job` 创建唯一任务时的 `INSERT`。Django 的 `OperationalError` 将 SQLite 原始异常放在 `__cause__`，只检查外层异常会漏掉锁码。并发创建的受控 SQL trace 曾在第 6 次重复中复现该 `INSERT` 失败。

现在只沿数据库异常的 cause/context 链识别明确的 SQLite `BUSY` 或 `LOCKED` 错误码，并对 DB-only 操作有限重试。任务创建/附加会在锁冲突后先回滚完整 `atomic()` 事务，再重试整笔事务，并用随机退避错开并发写入；Provider 请求不重试。没有 SQLite 锁错误码的数据库不可用/I/O 错误、约束错误及非 SQLite 数据库错误均直接失败，不进入锁重试路径。

## 验收约束

- 保留 `test_sse_disconnect_does_not_cancel_background_worker` 对终态 `succeeded` 和完整翻译结果的原断言。
- 在失败 SQL 的高风险窗口执行重复回归；确认数据库重试不会重复 Provider 请求。
- 用文件型 WAL SQLite 验证竞争写锁释放后 DB 操作可继续；生产配置也是文件型 SQLite/WAL。
- 本卡不把 CI 偶发通过、真实 Provider、生产数据库或生产发布作为证据。
