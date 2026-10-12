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

## 2026-10-12 T08 并发与当前译文修正

本次修正从 PR #42 当时 head `5efbf33326f63f4c5ee4aa8d5c27fa0f87c0e2a6` 建立独立分支 `task/byok-T08-reader-fixes`，代码提交为 `f2b0a9c0b658efc4552e93d6e5fd315fcc860dd6`。没有进入 T09、没有推送或合并。原有 T08 证据仍指向其先前实现 `e9e9644`；本节记录这次 follow-up，不覆盖此前结果。

| 项目 | 结果 |
| --- | --- |
| 修正验证环境 | Linux x86_64；Python 3.14.8、Django 6.1.2、pytest 9.1.1、SQLite；Node 24.21.0、React 19.2.6、Vitest 4.1.7。使用已有临时 venv、测试 stubs 与隔离 worktree 前端依赖。 |
| 修正前同环境基线 | 后端 5 个相关文件 `68 passed in 9.64s`；前端 4 个相关文件 `51 passed`（播放器测试有 2 条既有 React `act(...)` 警告）。基线 HEAD 为 `5efbf33326f63f4c5ee4aa8d5c27fa0f87c0e2a6`。 |
| 修正后后端回归 | `71 passed in 10.29s`；包含 T08 读取/共享译文/任务/聊天上下文/聊天，以及连接撤销、Key 轮换和 Chat 清空发生在模型流完成后、最终 history commit 前的回归。 |
| 修正后前端回归 | 97 个受影响用例分组通过：私有翻译 8、全文抓取 23、详情组件 17、聊天 25、播放器 5、API 10、页面导航 9。页面导航用例分三组运行；其中新增用例验证当前个人译文 B 同时用于正文、Chat result ID 和 TTS result ID。 |
| TypeScript / ESLint / build | `tsc --noEmit`、全前端 `eslint .`、Vite production build 均通过。 |
| diff 与断言 | `git diff --check` 通过。未改写或删除旧测试断言；新增 3 个后端参数化/场景用例和前端并发、源变更与页面消费者回归。 |
| 外部验证 | 无厂商调用；`PROVIDER_REAL`、浏览器手动 UAT、全后端套件和 PostgreSQL 并发测试均为 **NOT_RUN**。本次 SQLite 回归不代表 PostgreSQL 并发验证。 |
| 整组 Vitest 命令 | 一次包含 7 个文件的并行 Vitest 命令打印出 6 个文件共 88 个 PASS 后，在页面导航文件没有输出；约 60 秒后手动停止（exit 130）。随后页面文件按非助手导航 7 项、助手导航 1 项、新增消费者一致性 1 项分组运行，9 项均 PASS。没有将中断命令标为整组通过。 |

修正重点：最终 Chat turn 在同一短事务里按 connection → model config → ChatSession 锁顺序重新校验执行快照并保存 history CAS；无法确认取消状态时保留 job recovery 并阻止新 create；详情、Chat 和 TTS 共享同一当前译文选择；全文变更清除当前/过期结果指针、刷新详情，并丢弃旧 source 的晚到结果。

### 本次可复现命令

后端相关回归：

```sh
env -i PATH=/tmp/byok-t01-verify-20261012/bin:/usr/bin:/bin HOME=/tmp/byok-t01-empty-home PYTHONPATH="/tmp/byok-t02-test-stubs:$PWD/backend" DJANGO_ENV=development DJANGO_SECRET_KEY=pr42-fixes-synthetic-only DJANGO_DB_PATH=/tmp/byok-pr42-fixes-backend-final-relevant-20261012.sqlite3 /tmp/byok-t01-verify-20261012/bin/python -m pytest backend/api/tests/test_article_translation_readers.py backend/api/tests/test_shared_translations.py backend/api/tests/test_ai_translation_jobs.py backend/api/tests/test_chat_context.py backend/api/tests/test_ai_chat.py -q
```

前端 hook、详情组件和页面回归使用隔离 worktree 的依赖：

```sh
cd frontend
env -i PATH=/home/lambert/.local/share/vite-plus/js_runtime/node/24.21.0/bin:/usr/bin:/bin HOME=/tmp/byok-pr42-fixes-home XDG_CACHE_HOME=/tmp/byok-pr42-fixes-xdg node_modules/.bin/vitest run tests/context/speechPlayer.test.jsx tests/hooks/usePrivateTranslation.test.jsx tests/hooks/useChat.test.js tests/services/api.test.js tests/components/news-detail/news-detail.test.jsx tests/pages/NewsDetail.navigation.test.jsx tests/hooks/useFullArticle.test.jsx
env -i PATH=/home/lambert/.local/share/vite-plus/js_runtime/node/24.21.0/bin:/usr/bin:/bin HOME=/tmp/byok-pr42-fixes-home XDG_CACHE_HOME=/tmp/byok-pr42-fixes-xdg node_modules/.bin/vitest run tests/hooks/useFullArticle.test.jsx tests/hooks/usePrivateTranslation.test.jsx
env -i PATH=/home/lambert/.local/share/vite-plus/js_runtime/node/24.21.0/bin:/usr/bin:/bin HOME=/tmp/byok-pr42-fixes-home XDG_CACHE_HOME=/tmp/byok-pr42-fixes-xdg node_modules/.bin/vitest run tests/components/news-detail/news-detail.test.jsx
env -i PATH=/home/lambert/.local/share/vite-plus/js_runtime/node/24.21.0/bin:/usr/bin:/bin HOME=/tmp/byok-pr42-fixes-home XDG_CACHE_HOME=/tmp/byok-pr42-fixes-xdg node_modules/.bin/vitest run tests/pages/NewsDetail.navigation.test.jsx -t "retries a missing translation|restores the filtered|uses the home page|offers original-body|shows the formatted full article|opens the login dialog"
env -i PATH=/home/lambert/.local/share/vite-plus/js_runtime/node/24.21.0/bin:/usr/bin:/bin HOME=/tmp/byok-pr42-fixes-home XDG_CACHE_HOME=/tmp/byok-pr42-fixes-xdg node_modules/.bin/vitest run tests/pages/NewsDetail.navigation.test.jsx -t "opens the same article assistant"
env -i PATH=/home/lambert/.local/share/vite-plus/js_runtime/node/24.21.0/bin:/usr/bin:/bin HOME=/tmp/byok-pr42-fixes-home XDG_CACHE_HOME=/tmp/byok-pr42-fixes-xdg node_modules/.bin/vitest run tests/pages/NewsDetail.navigation.test.jsx -t "latest current private translation"
```

全前端检查：

```sh
cd frontend
env -i PATH=/home/lambert/.local/share/vite-plus/js_runtime/node/24.21.0/bin:/usr/bin:/bin HOME=/tmp/byok-pr42-fixes-home XDG_CACHE_HOME=/tmp/byok-pr42-fixes-xdg node_modules/.bin/tsc --noEmit
env -i PATH=/home/lambert/.local/share/vite-plus/js_runtime/node/24.21.0/bin:/usr/bin:/bin HOME=/tmp/byok-pr42-fixes-home XDG_CACHE_HOME=/tmp/byok-pr42-fixes-xdg node_modules/.bin/eslint .
env -i PATH=/home/lambert/.local/share/vite-plus/js_runtime/node/24.21.0/bin:/usr/bin:/bin HOME=/tmp/byok-pr42-fixes-home XDG_CACHE_HOME=/tmp/byok-pr42-fixes-xdg node_modules/.bin/vite build
```

## 2026-10-12 · T08 四项返修最终证据

本节记录原修复分支 `task/byok-T08-reader-fixes` 上，从代码基线 `f9c233b9bd214768505e483ee240f21ae69f2835` 开始的四项返修。返修覆盖 14 个前后端生产/测试文件；本节是这次返修的最终验证记录，与前文首版 `e9e9644` 和中间阶段 `f2b0a9c` 的结果区分。独立静态审查确认相关数据库锁顺序一致；静态审查不作为并发运行验证。

### 修复范围

1. **私有翻译任务恢复与取消**：取得 job ID 后，查询、订阅或取消的传输错误都保留 job 身份、恢复信息和阻止重复 start 的活动状态；界面提供重新检查状态与再次取消入口，只有确认服务端终态才清除任务身份。覆盖取消 POST 失败后 stream 再失败、恢复 GET 失败后再生成、随后恢复终态。
2. **幂等恢复与正文隔离**：移除按 owner 一次性置位的恢复闩锁，按有效 request 生命周期附着任务；StrictMode 重挂载和 loading/source 变化可恢复。迟到的旧 source 请求不能覆写当前正文的译文。
3. **模型配置与聊天提交锁序**：聊天最终 history commit 按 connection → model config → ChatSession 锁内重验执行快照；模型创建/修改/删除、模型探测最终快照及任务偏好更新显式使用 connection → model 顺序，并在锁内校验归属与配置版本。保留 SQLite 首条写入防升级争用；没有把 provider 网络调用放入数据库锁，也没有增加自动 provider 重试。
4. **译文消费者一致性**：用户从译文 A 生成并完成译文 B 后，详情正文、复制、聊天上下文和中文朗读都选择 B；源正文变化后失效旧结果 ID/current-match 元数据。GET 已完成任务时用文章当前正文重新计算 `current_match`。

### 验证结果

| 检查 | 实际结果 |
| --- | --- |
| 后端相关回归 | 9 个模块、`107 passed in 16.40s`；使用合成 Django secret、测试 stub 与隔离 SQLite 数据库，未调用外部模型。模块：`test_article_translation_readers.py`、`test_shared_translations.py`、`test_ai_translation_jobs.py`、`test_chat_context.py`、`test_ai_chat.py`、`test_ai_preferences.py`、`test_ai_models.py`、`test_ai_model_test_service.py`、`test_ai_connections.py`。 |
| 前端相关回归 | 本轮修复阶段的六文件组合曾记录 `53 passed`；保留该分组结果。另见下行最终全套运行，不将这两个不同范围的计数混为一组。 |
| 最终全前端回归 | 按默认 Vitest 套件配置、180 秒有界运行：`73 passed` 个测试文件、`513 passed` 项测试，耗时 `8.12s`，退出码 0。未跳过测试。Vitest 报告了一些既有 React `act(...)` 警告，但无失败。 |
| TypeScript / ESLint | `tsc --noEmit` 和全前端 `eslint .` 均退出码 0。 |
| Production build | 默认输出 `frontend/dist` 时遇到工作区写权限拒绝，不能把该次失败记为构建成功或代码错误。使用 `/tmp` 输出目录重新运行成功：4340 modules transformed，`✓ built in 540ms`。临时产物位于项目外，不纳入 Git。 |
| Diff | 文档加入后运行 `git diff --check`；结果记录在本次本地交付检查。 |

### 失败与超时记录

修复过程中保留了早期失败记录：hook 定向运行曾为 `31 passed, 4 failed`，暴露 StrictMode 恢复只请求一次、`terminal` 变量作用域错误及其引发的取消竞态等待失败，以及 source-change 状态仍为 active。修复这些问题后，最终全前端 513 项均通过。页面导航相关旧序列曾在约 22 秒和 70 秒有界运行中超时（退出码 124）；此前七文件组合曾手动中断（退出码 130）。这些旧运行不记作通过，也没有跳过或放宽旧断言。最终完整 Vitest 命令已覆盖这些测试并通过。

### 未运行

PostgreSQL 并发测试、真实模型/Provider 请求、浏览器 E2E、手动浏览器 UAT、全量后端套件和部署均为 **NOT_RUN**。SQLite 结果与静态锁序审查不能替代 PostgreSQL 并发验证。

### 本次重现命令

后端相关回归（输出数据库与测试 stub 均在 `/tmp`，pytest cache provider 关闭）：

```sh
env -i PATH=/tmp/byok-t01-verify-20261012/bin:/usr/bin:/bin HOME=/tmp/byok-t01-empty-home PYTHONPATH="/tmp/byok-t02-test-stubs:$PWD/backend" DJANGO_ENV=development DJANGO_SECRET_KEY=synthetic-test-value DJANGO_DB_PATH=/tmp/byok-t08-final-related-complete-20261012.sqlite3 /tmp/byok-t01-verify-20261012/bin/python -m pytest -p no:cacheprovider backend/api/tests/test_article_translation_readers.py backend/api/tests/test_shared_translations.py backend/api/tests/test_ai_translation_jobs.py backend/api/tests/test_chat_context.py backend/api/tests/test_ai_chat.py backend/api/tests/test_ai_preferences.py backend/api/tests/test_ai_models.py backend/api/tests/test_ai_model_test_service.py backend/api/tests/test_ai_connections.py -q
```

最终全前端：

```sh
cd frontend
timeout 180s env -i PATH=/home/lambert/.local/share/vite-plus/js_runtime/node/24.21.0/bin:/usr/bin:/bin HOME=/tmp/byok-t08-final-home XDG_CACHE_HOME=/tmp/byok-t08-final-xdg node_modules/.bin/vitest run
```

类型、lint 和项目外构建输出：

```sh
cd frontend
env -i PATH=/home/lambert/.local/share/vite-plus/js_runtime/node/24.21.0/bin:/usr/bin:/bin HOME=/tmp/byok-t08-final-home XDG_CACHE_HOME=/tmp/byok-t08-final-xdg node_modules/.bin/tsc --noEmit
env -i PATH=/home/lambert/.local/share/vite-plus/js_runtime/node/24.21.0/bin:/usr/bin:/bin HOME=/tmp/byok-t08-final-home XDG_CACHE_HOME=/tmp/byok-t08-final-xdg node_modules/.bin/eslint .
env -i PATH=/home/lambert/.local/share/vite-plus/js_runtime/node/24.21.0/bin:/usr/bin:/bin HOME=/tmp/byok-t08-final-home XDG_CACHE_HOME=/tmp/byok-t08-final-xdg node_modules/.bin/vite build --outDir /tmp/byok-t08-fixes-build-f9c233b-20261012
```
