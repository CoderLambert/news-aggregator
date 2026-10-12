# Test T03 · 用途默认模型设置

对应：[T03 Task](../tasks/T03-preferences.md)。

> **READY FOR REVIEW。** 偏好保存、用户隔离、失效选择拒绝、解析快照和设置页已按本卡范围验证。T03-04 的 resolver 快照测试通过，但尚无真实业务 worker 消费快照；端到端在途任务和历史结果行为保持 NOT_RUN。没有真实供应商请求。

## 提交与执行环境

| 项目 | 结果 |
| --- | --- |
| T02 父提交 / 父分支 | `c2f50dd6a56e17dad65e78b295a13598895b4c76` / `task/byok-T02-models-and-tests`（已同步 T01 最新文档及工具探测修复） |
| T02 PR | [#36 Draft](https://github.com/CoderLambert/news-aggregator/pull/36)，未合并 |
| T03 实现提交（重放后） | `1fbd8535454d50c3d4939b4949c762fff23daa9f` |
| T03 分支 / PR base | `task/byok-T03-preferences` / `task/byok-T02-models-and-tests` |
| T03 PR | [#37 Draft](https://github.com/CoderLambert/news-aggregator/pull/37)，依赖 PR #36 |
| OS / 架构 | Linux 7.2.5-3-omarchy x86_64 |
| Python / Django / DRF / pytest | 3.14.8 / 6.1.2 / 3.18.3 / 9.1.1 |
| Node / npm / Vitest / Vite | 24.21.0 / 11.19.0 / 4.1.7 / 8.0.13 |
| 数据库 | 自动创建的临时 SQLite；迁移检查也使用独立临时 SQLite；未打开仓库数据库 |
| 隔离 | Python venv `/tmp/byok-t01-verify-20261012`、测试 stub `/tmp/byok-t02-test-stubs`；未读取仓库 `.env` 或用户凭据 |

## 后端验证

从 T03 工作树根目录运行：

```sh
PYTHONPATH="/tmp/byok-t02-test-stubs:$PWD/backend" \
  /tmp/byok-t01-verify-20261012/bin/python -m pytest backend/api/tests -q
```

结果：`537 passed, 1 skipped, 2 warnings in 53.58s`。跳过项需要专用 Proxy runner；两条 warning 是既有 Category/Source 分页未排序提示，与本卡无关。

提交后复跑本卡 API 和模型目录边界：

```sh
PYTHONPATH="/tmp/byok-t02-test-stubs:$PWD/backend" \
  /tmp/byok-t01-verify-20261012/bin/python -m pytest \
  backend/api/tests/test_ai_preferences.py backend/api/tests/test_ai_models.py -q
```

结果：`20 passed in 5.44s`。覆盖五用途严格提交、owner 隔离、CSRF/no-store、停用与删除后的 fail-closed、无默认模型时拒绝回退、不可变执行快照及无 provider 网络连接。`manage.py check` 无问题，`makemigrations --check --dry-run` 显示 `No changes detected`；迁移 `0036` 在隔离 SQLite 上成功应用。

## 前端与本地浏览器

完整前端套件在最终文案微调前通过：`npm test -- --run`，69 个测试文件、487 个测试通过。最终文案变更后复跑了设置/API 相关用例：

```sh
npm test -- --run \
  tests/pages/AIModelSettingsPage.test.tsx \
  tests/services/aiTaskPreferencesApi.test.ts \
  tests/services/aiModelsApi.test.ts \
  tests/pages/SettingsPage.test.tsx \
  tests/pages/ChatGPTSubscriptionSettings.test.tsx
npm run typecheck
npm run lint
```

结果：5 个文件、38 个测试通过；TypeScript 检查和 ESLint 通过。`npm run build` 与 `python scripts/validate_build.py` 在同一实现上通过，文案微调后未重跑构建。

隔离浏览器 smoke 使用本地合成用户和测试密文，没有访问 provider：390×844 viewport 下全局默认与新闻问答模型保存后刷新仍保留，五个用途选择框正常显示，`window.innerWidth` 与页面 `scrollWidth` 均为 390，无横向溢出。既有 ChatGPT 订阅设置测试也通过；真实用户 UAT 未运行。

## 用例结果

| 用例 | 场景 / 正确性约束 | 状态 |
| --- | --- | --- |
| T03-01 | 保存完整五用途集合并重新读取；另一用户看不到该选择 | PASS；API 与隔离浏览器保存/刷新验证 |
| T03-02 | 未保存草稿可撤销；保存失败不丢草稿、不显示成功 | PASS；Vitest 页面交互测试 |
| T03-03 | 跨用户模型拒绝；连接停用/模型删除要求重选；无选择时不回退站点或订阅凭据 | PASS；API 与 resolver 测试 |
| T03-04 | 默认变更后新 resolver 使用新模型；已取得快照保持不变 | PARTIAL：不可变 secret-free resolver 快照通过；真实 worker、在途任务提交 fencing 和历史结果读取未接入/未运行 |
| T03-05 | AI 设置可操作、旧设置入口回归、390px 布局无溢出 | PASS；设置页/API 测试及本地浏览器 smoke；人工产品 UAT 未运行 |

## 兼容回归与未运行项

浏览器的共享 Axios interceptor 会在 GET 请求追加 `?lang=zh`。本卡因此允许连接偏好与模型目录/列表只接收 `lang=zh|en`，其它查询参数仍被拒绝；模型目录旧测试增加了 `lang: 'zh'` 输入以覆盖真实客户端行为，原有安全断言未放宽。

| 等级 | 状态 | 说明 |
| --- | --- | --- |
| SDK_LOCAL / PROXY_LOCAL | NOT_RUN | T03 不发起 SDK 或 Proxy 请求 |
| PROVIDER_REAL | NOT_RUN | 没有连接 DeepSeek 或其它供应商，也没有读取真实 API key |
| 业务 worker / 在途提交 | NOT_RUN | 当前无业务 worker 调用 `resolve_execution`；T04 等调用卡负责接入和端到端 fencing |
| 人工 UAT | NOT_RUN | 自动化浏览器 smoke 使用合成账号，不代表真实用户验收 |
| 生产数据库迁移 | NOT_RUN | 仅在临时 SQLite 验证迁移；没有对任何共享或生产数据库执行迁移 |
