# Test T08 · 译文详情、问答与朗读同源

> **EXECUTED · DRAFT PR #42**。代码提交 `e9e96444488c75b3dbd550ab51ff7d04370bfc03`，base 为未合并的 T07 PR #41 head `b0139e42291bc83c701a04f73f1f7fdcbf16b0a0`。所有 provider/Proxy 请求均为模拟；真实 DeepSeek 和手动浏览器 UAT 未执行。

对应：[T08 Task](../tasks/T08-translation-readers.md)。

| 用例 | 场景 / 失败注入 | 正确性约束 | 状态 |
| --- | --- | --- | --- |
| T08-01 | 详情、聊天和 TTS 读取同一个明确私有结果 | 详情 ID 与 Chat/TTS 请求 ID 相同；无翻译 Provider dispatch | PASS · Django API/service |
| T08-02 | 同篇文章用户 A/B 各自私有结果 | 只能读本人结果；TTS cache namespace 包含 owner 和 result ID | PASS · Django DB/service/API |
| T08-03 | 更新文章原文后读取旧结果 | 详情不把旧译文当当前内容；历史 GET 返回原文 hash 和 `current_match=false` | PASS · Django DB/API |
| T08-04 | 私人结果缺失但已有公共或订阅结果 | 当前个人结果优先；否则延续公共、订阅和 legacy 回退 | PASS · Django serializer/service regression |
| T08-05 | 软删除个人连接后读取历史 | 不需要有效 Key；跨用户读取返回 404；GET 不触发翻译 | PASS · Django API |

## 执行证据

| 项目 | 结果 |
| --- | --- |
| 精确基线 / 代码 HEAD | `b0139e42291bc83c701a04f73f1f7fdcbf16b0a0` / `e9e96444488c75b3dbd550ab51ff7d04370bfc03` |
| 环境 | Linux x86_64；Python 3.14.8、Django 6.1.2、pytest 9.1.1、SQLite；Node v24.21.0、npm 11.19.0、React 19.2.6、Vitest 4.1.7 |
| 修改前 T08 相关基线 | 后端 `62 passed in 9.47s`；前端 `3 files, 24 tests passed`。使用同一临时 Python/SQLite 环境和 worktree 前端依赖。 |
| 后端定向 + 旧功能回归 | `68 passed in 9.50s`：新读取测试、订阅共享译文、BYOK 任务、聊天上下文及聊天回归。 |
| 前端定向回归 | `4 files, 44 tests passed`：播放器、私有翻译 hook、聊天 hook、API 请求体。 |
| 前端全量回归 | `71 files, 499 tests passed`。 |
| 前端类型、lint、构建 | `npx tsc --noEmit` 通过；改动文件 ESLint 通过；`npm run build` 通过。 |
| Django / migrations / diff | `manage.py check` 无问题；`makemigrations --check --dry-run` 输出 `No changes detected`；`git diff --check` 通过。 |
| 全后端与部署回归 | 最终代码的两次完整运行均为 `905 passed, 2 skipped, 1 failed`；失败均是既有 `test_sse_disconnect_does_not_cancel_background_worker` 在 SQLite 并发写入时抛 `OperationalError`。该测试单独重跑 `1 passed in 1.84s`。相同用例也出现在此前 T00/T01 CI 的间歇失败记录中；没有修改该旧测试或其断言。 |
| 全后端临时依赖 | 临时 venv 补入 `waitress==3.0.2`。`chromadb` 未安装，因此迁移包装测试的子进程使用现有测试 stub；其 `PersistentClient` 会立即失败，验证迁移路径没有调用向量服务。该 stub 不在仓库中。 |
| 旧断言 diff | `NewsChatAssistant.test.jsx` 把 `useChat` 调用断言从 3 个参数更新为 4 个（新增显式翻译 ID，未放宽产品行为）；其余新增了 6 个 Django 与 4 个 Vitest 测试。 |
| SDK_LOCAL / PROXY_LOCAL / PROVIDER_REAL / UAT | 全部 **NOT_RUN**。结果读取、聊天和 TTS 使用合成 task、mock chat stream 和 mock Edge TTS；本次没有任何真实 Provider 请求。 |
| GitHub CI | PR #42 head `c8e63da` 的 push 与 pull_request 两次 CI 均通过：backend-and-release-gates、frontend；包括全后端测试、前端类型/lint/499 项测试/构建、生产镜像构建及 G1 本地域名 smoke。 |
| 未验证项 | 手动浏览器验收、真实 DeepSeek 请求和生产部署均未执行。 |

## 可复现命令

后端定向测试：

```sh
env -i PATH=/tmp/byok-t01-verify-20261012/bin:/usr/bin:/bin HOME=/tmp/byok-t01-empty-home PYTHONPATH="/tmp/byok-t02-test-stubs:$PWD/backend" DJANGO_ENV=development DJANGO_SECRET_KEY=t08-synthetic-only-not-a-secret DJANGO_DB_PATH=/tmp/byok-t08-readers-final-20261012.sqlite3 /tmp/byok-t01-verify-20261012/bin/python -m pytest backend/api/tests/test_article_translation_readers.py backend/api/tests/test_shared_translations.py backend/api/tests/test_ai_translation_jobs.py backend/api/tests/test_chat_context.py backend/api/tests/test_ai_chat.py -q
```

同一套后端旧测试在修改前的基线命令：

```sh
env -i PATH=/tmp/byok-t01-verify-20261012/bin:/usr/bin:/bin HOME=/tmp/byok-t01-empty-home PYTHONPATH="/tmp/byok-t02-test-stubs:$PWD/backend" DJANGO_ENV=development DJANGO_SECRET_KEY=t08-synthetic-only-not-a-secret DJANGO_DB_PATH=/tmp/byok-t08-before-20261012.sqlite3 /tmp/byok-t01-verify-20261012/bin/python -m pytest backend/api/tests/test_shared_translations.py backend/api/tests/test_ai_translation_jobs.py backend/api/tests/test_chat_context.py backend/api/tests/test_ai_chat.py -q
```

前端全量测试与构建：

```sh
cd frontend && npm test -- --run
cd frontend && npm run build
```

前端 T08 定向测试与修改前基线分别为：

```sh
cd frontend && npm test -- --run tests/context/speechPlayer.test.jsx tests/hooks/usePrivateTranslation.test.jsx tests/hooks/useChat.test.js tests/services/api.test.js
cd frontend && npm test -- --run tests/components/news-detail/news-detail.test.jsx tests/context/speechPlayer.test.jsx tests/hooks/usePrivateTranslation.test.jsx
```

完整后端测试集合：

```sh
env -i PATH=/tmp/byok-t01-verify-20261012/bin:/usr/bin:/bin HOME=/tmp/byok-t01-empty-home PYTHONPATH="/tmp/byok-t02-test-stubs:$PWD/backend:$PWD/crawler" DJANGO_ENV=development DJANGO_SECRET_KEY=t08-synthetic-only-not-a-secret DJANGO_DB_PATH=/tmp/byok-t08-final-backend-rerun-20261012.sqlite3 RUN_MAIN=true /tmp/byok-t01-verify-20261012/bin/python -m pytest -q tests/ backend/api/tests/ scripts/deploy/tests/
```

SQLite SSE 并发测试在完整套件中具有既有间歇锁冲突。最终代码的完整套件结果保留为失败，单测通过也单独记录；没有隐藏失败或改动该旧用例。
