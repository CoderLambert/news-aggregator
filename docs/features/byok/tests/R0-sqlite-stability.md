# Test R0 · SQLite 后台翻译锁争用稳定性

对应：[R0 Task](../tasks/R0-sqlite-stability.md)。

> **READY FOR REVIEW。** 修复捕获了 Django 包装在异常因果链中的 SQLite 锁码；原断连测试在共享缓存测试库和文件型 WAL SQLite 测试库各连续 20 次通过。全量离线回归 845 项通过。

实现提交：`e7026e092b680e9bf32049859d638f590edf5009`。

## 诊断证据

| 项目 | 结果 |
| --- | --- |
| 原失败 | `test_sse_disconnect_does_not_cancel_background_worker` 断言 `succeeded`，worker 因 `OperationalError` 进入 `failed` |
| SQLite 错误 | `SQLITE_LOCKED_SHAREDCACHE`，扩展错误码 262（基础码 `SQLITE_LOCKED`） |
| 捕获到的失败 SQL | `api_chatgpttranslationtask` 的 queued→running 条件更新、最终提交前的 running/provider_started 条件 CAS 更新 |
| 异常包装 | Django 外层 `OperationalError` 未携带错误码；SQLite 驱动异常在 `__cause__` 中 |
| 生产数据库语义 | 项目生产配置为文件型 SQLite，连接初始化启用 WAL、`synchronous=NORMAL`、30 秒 busy timeout |

锁重试只读取异常因果链中的 SQLite 数字错误码，并按低位基础码识别 `SQLITE_BUSY` / `SQLITE_LOCKED`。`SQLITE_CANTOPEN`、`SQLITE_IOERR`、无错误码的锁消息、`IntegrityError` 和非 SQLite backend 均由单次负例确认不会重试。

## 实际验证

| 验证 | 结果 |
| --- | --- |
| 原 SSE 断连测试，共享缓存 pytest 数据库，带 SQL trace | 20/20 通过；保留原终态和译文断言，并断言 Provider fake 只调用一次 |
| 同一测试，文件型 SQLite 临时测试库 | 20/20 通过；检查 `PRAGMA database_list` 为文件路径，`PRAGMA journal_mode` 为 `wal` |
| R0 定向锁分类与文件 WAL 写锁释放测试 | 8 passed；含共享缓存锁码、文件写锁释放、`SQLITE_CANTOPEN`、I/O、约束和非 SQLite backend 负例 |
| `backend/api/tests/test_subscription_recovery.py` | 34 passed |
| CI 三个测试根目录 | 845 passed，3 warnings，18.51 秒 |
| Provider / 生产数据 / 发布 | NOT_RUN；全程使用临时 SQLite 与本地 fake |

全量回归命令（仓库根目录；数据库、缓存、HOME 均在 `/tmp`）：

```sh
env -i \
  HOME=/tmp/byok-r0-home \
  PATH=/home/lambert/githubRepos/lambert/news-aggregator/backend/venv/bin:/usr/bin:/bin \
  PYTHONPATH=backend:crawler \
  RUN_MAIN=true \
  DJANGO_ENV=development \
  DJANGO_DB_PATH=/tmp/newsagg-byok-r0-ci-final-20261012.sqlite3 \
  CHROMA_DATA_DIR=/tmp/byok-r0-chroma \
  TTS_CACHE_DIR=/tmp/byok-r0-tts \
  /home/lambert/githubRepos/lambert/news-aggregator/backend/venv/bin/python \
  -m pytest -q tests/ backend/api/tests/ scripts/deploy/tests/
```

文件型 worker 回归通过仅位于 `/tmp` 的 pytest settings overlay 将 `TEST['NAME']` 指向专用 SQLite 文件；该库启用了项目同款 WAL 初始化配置。它验证生产数据库类型和锁语义，不连接、复制或改写任何运行数据库。

CI 工作流使用 Python 3.12；本机验证使用共享只读 venv 的 Python 3.14.8。GitHub CI 尚待 PR 运行。首次全量测试命令遗漏 CI 的 `PYTHONPATH=backend:crawler`，在收集阶段因 `news_crawler` 不可导入而停止；修正环境后，全量结果如上。

## 结论边界

没有删除、跳过或放宽原测试；没有重放任何真实订阅 Provider 请求。文件型 WAL 测试库是隔离测试数据库，不代表已访问生产数据库。CI 结果和本地回归均不能替代生产运维验收。
