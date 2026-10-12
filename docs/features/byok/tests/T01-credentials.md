# Test T01 · 个人 Key 连接增删改停

对应：[T01 Task](../tasks/T01-credentials.md)。

> **T01 本地实现与测试证据完成；PR #34 仍为 Draft，CI 尚未全绿。** `credential_epoch` worker 消费端集成现有堆叠 PR #39 的合成 worker 证据；PR #39 尚未合并，独立 T01 PR #34 仍只包含凭据管理。两者均没有真实 provider 调用。`credential_epoch` 是授权撤销/fencing 版本；独立的 `credential_version` 标记当前密文并参与 AAD。

| 用例 | 场景 / 失败注入 | 结果 | 证据 |
| --- | --- | --- | --- |
| T01-01 | 新增、名称更新、替换、停用/启用、删除；列表从数据库恢复最新状态 | PASS | API CRUD/AAD 测试；本地浏览器完成新增、改名、替换、停用/启用、刷新恢复及删除 |
| T01-02 | 其他用户、匿名、缺 CSRF、跨站 Origin 尝试访问/写入 | PASS | API 测试验证 owner 隔离、匿名拒绝、CSRF 及 Origin 检查；其他用户得到 404 |
| T01-03 | 替换/停用/启用/删除后，旧 credential epoch 再读取 | PASS（堆叠 PR #39） | 本卡服务测试证明旧 epoch 被拒绝；T05 worker 测试证明旧 epoch 仍在队列时 provider 不启动，且在途撤销时不保存部分结果、不发送 `complete`。PR #39 尚未合并，见下方跨卡证据 |
| T01-04 | 读取、保存、替换、改名不触达 provider；状态不冒称已验证 | PASS | 受控 socket connect 禁止测试、状态固定 `not_tested`；本地浏览器未发 provider 请求，Key 不进入浏览器持久存储 |
| T01-05 | 功能开关关闭、只读模式、缺加密密钥 | PASS | 缺密钥时新建/替换/重新启用拒绝 503；停用/删除仍成功撤销；重启服务检查设置默认关闭 |

### 两种版本的职责

- `credential_epoch` 是授权 fencing version；替换 Key、停用、启用和删除都会递增它。worker 需要用排队时记录的 epoch 调用 `require_active_connection`，旧 epoch 应被拒绝。
- `credential_version` 标识当前已加密的 Key 并参与 AAD；新建从 1 开始，只有替换 Key 时与 `credential_epoch` 一起递增并重新加密。停用/启用只改变授权 epoch，不改变密文版本，所以重新启用后仍可解密。
- 重新启用前必须能解密当前密文；缺主密钥或凭据不可用时返回 503。停用与删除是撤销操作，不依赖解密；删除清除密文并使行 tombstone 化。
- AAD 仍绑定 owner、connection id、provider、endpoint profile、endpoint profile version 和 credential version。防篡改断言现检查 `credential_version`；授权 epoch 由独立的旧 epoch fencing 测试覆盖。

## 执行环境

| 项目 | 结果 |
| --- | --- |
| 基线 `origin/feat/byok-user-api-keys` 本地 tracking ref | `3cd584c95acd52bc533bba0b55eab75b35c41ad5` |
| T01 初始实现 / 本次修复代码 SHA | `326028c` / `34f5a843dbc4a9fb218ff9fadf8ed32886f46953` |
| OS / 架构 | Linux 7.2.5-3-omarchy x86_64 |
| Python / Django / DRF / cryptography / SQLite / pytest | 3.14.8 / 6.1.2 / 3.18.3 / 50.0.2 / 3.53.1 / 9.1.1 |
| Node / npm / Vitest | 26.7.0 / 11.19.0 / 4.1.7 |
| 数据库 | 临时 SQLite 文件 `/tmp/byok-t01-*.sqlite3`；未打开仓库内 DB |
| 凭据 | 仅测试内合成账户、合成 Django secret、合成 AES 密钥和合成 provider Key；未读取既有 Key 或真实环境凭据 |
| 隔离 | Python venv 和空 HOME 在 `/tmp`；测试使用 `env -i`；`chromadb` 未安装，使用仅供测试导入的 stub（若业务路径调用会立即失败） |
| 浏览器 | Vitest DOM 测试；Codex in-app browser 对隔离本地前后端完成合成账户手工验收 |

### 2026-10-12 当前分支复测

当前分支 HEAD `33ec3461eedad60c560c0f5c2b7eea447017cd90`；最后一项 T01 业务代码/回归测试改动为 `34f5a843dbc4a9fb218ff9fadf8ed32886f46953`，之后提交只更新文档。后端沿用隔离 Python 3.14.8 环境 `/tmp/byok-t01-verify-20261012`、空 HOME `/tmp/byok-t01-empty-home`、只供导入的 ChromaDB stub `/tmp/byok-t01-preview-stubs/chromadb.py`，并使用全新 SQLite `/tmp/byok-t01-verification-20261012e.sqlite3`：

```sh
env -i PATH=/tmp/byok-t01-verify-20261012/bin:/usr/bin:/bin \
  HOME=/tmp/byok-t01-empty-home PYTHONPATH=/tmp/byok-t01-preview-stubs \
  DJANGO_ENV=development DJANGO_SECRET_KEY=t01-synthetic-only-not-a-secret \
  DJANGO_DB_PATH=/tmp/byok-t01-verification-20261012e.sqlite3 \
  /tmp/byok-t01-verify-20261012/bin/python -m pytest -q \
    api/tests/test_account_security.py \
    api/tests/test_chat_ownership.py \
    api/tests/test_chatgpt_subscription.py \
    api/tests/test_public_policy.py \
    api/tests/test_research_csrf.py \
    api/tests/test_production_settings.py \
    api/tests/test_ai_connections.py
```

```text
154 passed, 2 warnings in 20.42s
```

两条 warning 仍是 `Category` 与 `Source` queryset 未排序的既有 DRF `UnorderedObjectListWarning`。前端在相同提交重跑上文八个定向 Vitest 文件：

```text
Test Files  8 passed (8)
Tests       65 passed (65)
Duration    5.62s
```

这次复测重新确认当前提交的连接管理 API 和 UI 回归。上述 154 项和 65 项仅覆盖 T01 自身；worker 消费端由下方堆叠 T05 测试补齐，不将服务层 epoch gate 单独推导为端到端通过。

### T01-03 跨卡 worker 消费端证据（2026-10-12）

T01 分支本身没有翻译 worker；T05 堆叠 PR #39 (`task/byok-T05-private-translation`) 在 head `54df6ab` 增加并运行了两个合成 worker 用例：

- `test_queued_translation_after_credential_revocation_never_starts_provider`：epoch 1 的任务保持排队时停用连接并递增 epoch；worker 将任务置为 `failed/execution_changed`，`provider_started=false`，没有调用 provider，结果/进度为空且没有 SSE `complete`。
- `test_credential_epoch_change_during_worker_discards_partial_output`：在途合成流发生撤销后，worker 停止、丢弃未完成结果且不发送 SSE `complete`。

T05 的新增后端测试文件在该 head 上为 `11 passed in 4.95s`。这验证了 T01 `credential_epoch` 契约接入 worker 后的撤销栅栏；它依赖尚未合并的下游 PR #39，不能算作 T01 PR #34 单独包含 worker，也不构成真实 SDK、Proxy 或 Provider 兼容证据。

### PR #34 GitHub checks（head `33ec3461eedad60c560c0f5c2b7eea447017cd90`）

- 前端两组检查均通过。两个后端 run 均失败于既有 `backend/api/tests/test_subscription_recovery.py` 并发 SQLite 用例：run [38190564955](https://github.com/CoderLambert/news-aggregator/actions/runs/38190564955) 中 `test_sse_disconnect_does_not_cancel_background_worker` 遇到 `OperationalError`，worker 未保存成功终态；run [38190568500](https://github.com/CoderLambert/news-aggregator/actions/runs/38190568500) 中 `test_simultaneous_database_connections_share_one_unique_task` 遇到 `OperationalError`。失败不位于 BYOK 连接管理路径；本地定向测试未复现，测试和生产断言均未调整。
- 因当前 head 检查未全部通过，PR #34 保持 Draft；CI 失败不会被本地测试或 T05 堆叠证据覆盖。

最初用户报告的基线 `ea2ce55ae22e19e1604e88031b824b68f2666cec` 已由基线前合入的文档 PR #31 前移至以上 tracking ref。实现基于该 ref 建立的独立工作树；最终实时 `git ls-remote` 因 DNS 无法解析 `github.com` 暂不可验证。

## 定向测试命令与脱敏输出

以下 Python 命令在 `backend/` 执行，固定空 HOME、临时 SQLite、隔离依赖和合成设置；`PYTHONPATH` 仅指向不会实现应用行为的测试导入 stub。

**后端基线（未改动前，六个旧测试文件）：**

```sh
env -i PATH=/tmp/byok-t01-test-venv-20261011/bin:/usr/bin:/bin \
  HOME=/tmp/byok-t01-empty-home PYTHONPATH=/tmp/byok-t01-test-stubs \
  DJANGO_ENV=development DJANGO_SECRET_KEY=t01-synthetic-only-not-a-secret \
  DJANGO_DB_PATH=/tmp/byok-t01-baseline.sqlite3 \
  python -m pytest -q \
    api/tests/test_account_security.py \
    api/tests/test_chat_ownership.py \
    api/tests/test_chatgpt_subscription.py \
    api/tests/test_public_policy.py \
    api/tests/test_research_csrf.py \
    api/tests/test_production_settings.py
```

```text
144 passed, 2 warnings in 23.54s
```

**后端实现后（同一六个旧文件 + 本卡 API 安全测试）：**

```sh
env -i PATH=/tmp/byok-t01-test-venv-20261011/bin:/usr/bin:/bin \
  HOME=/tmp/byok-t01-empty-home PYTHONPATH=/tmp/byok-t01-test-stubs \
  DJANGO_ENV=development DJANGO_SECRET_KEY=t01-synthetic-only-not-a-secret \
  DJANGO_DB_PATH=/tmp/byok-t01-final.sqlite3 \
  python -m pytest -q \
    api/tests/test_account_security.py \
    api/tests/test_chat_ownership.py \
    api/tests/test_chatgpt_subscription.py \
    api/tests/test_public_policy.py \
    api/tests/test_research_csrf.py \
    api/tests/test_production_settings.py \
    api/tests/test_ai_connections.py
```

```text
154 passed, 2 warnings in 34.49s
```

两条旧 warning 都是既有公共策略分页对 Category/Source queryset 未排序的 DRF `UnorderedObjectListWarning`；基线与实现后各为 2 条。

**前端基线**从干净 `git archive 3cd584c95acd52bc533bba0b55eab75b35c41ad5` 目录运行，复用已按锁文件安装的 `node_modules`，Node/npm 与实现后相同：

```sh
npm run test:run -- \
  tests/pages/SettingsPage.test.tsx \
  tests/pages/ChatGPTSubscriptionSettings.test.tsx \
  tests/App.readOnly.test.tsx \
  tests/context/AuthContext.races.test.tsx \
  tests/context/AuthContext.capabilities.test.tsx \
  tests/services/capabilities.test.ts
```

```text
Test Files  6 passed (6)
Tests       58 passed (58)
```

**前端实现后**追加本卡设置页和 API service 测试：

```sh
npm run test:run -- \
  tests/pages/SettingsPage.test.tsx \
  tests/pages/ChatGPTSubscriptionSettings.test.tsx \
  tests/App.readOnly.test.tsx \
  tests/context/AuthContext.races.test.tsx \
  tests/context/AuthContext.capabilities.test.tsx \
  tests/services/capabilities.test.ts \
  tests/pages/AIModelSettingsPage.test.tsx \
  tests/services/aiConnectionsApi.test.ts
```

```text
Test Files  8 passed (8)
Tests       65 passed (65)
```

**附加检查（前端目录）：**

| 命令 | 脱敏结果 |
| --- | --- |
| `npm run typecheck` | `tsc --noEmit` 退出码 0 |
| `npm run lint` | `eslint .` 退出码 0 |
| `npm run build` | Vite 8.0.13，4338 modules transformed，build 成功 |
| `python scripts/validate_build.py`（仓库根目录） | Dist directory、JS imports、CSS files、Bundle size 全部 OK |

**附加检查（后端目录，使用同一隔离环境）：**

```sh
python manage.py check
python manage.py makemigrations --check --dry-run
python -m py_compile api/ai_connection_views.py api/services/ai_credentials.py \
  api/services/ai_registry.py api/models.py newsaggregator/runtime_config.py \
  newsaggregator/settings.py
```

输出：`System check identified no issues`、`No changes detected`；`py_compile` 退出码 0。`manage.py check` 启动时报告缺少可选 embedding 模型模块，检查本身无 Django issue；本卡未调用该业务路径。

## 隔离本地浏览器验收

使用 `/tmp/byok-t01-ui.sqlite3` 与回环本地服务：Vite `127.0.0.1:5173`，临时 Django API `127.0.0.1:9528`。两者均已停止，临时 Vite 代理配置已还原。仅使用两个合成账户、合成 Django secret、合成加密密钥和合成 DeepSeek 字符串；该 UI 路径没有调用 DeepSeek 或任何 provider。

1. 用户 A 登录后打开 `/settings/ai`，保存合成 Key；界面清空输入框，只显示掩码与 `not_tested`。
2. 刷新页面仍能恢复连接；改名、替换合成 Key、停用后重新启用均成功。重新启用会先由服务端解密现存密文。
3. 用户 A 登出，用户 B 登录后列表为空。
4. 用户 A 重新登录并删除连接；列表删除后再刷新仍为空。
5. 临时数据库脱敏检查显示该连接为 tombstone、已停用、ciphertext/key id 已清空；最终 `credential_epoch=5`、`credential_version=2`。

这证明当前实现通过隔离数据库和真实浏览器 UI 的合成用户路径；它不是生产环境 UAT，也不证明第三方 provider 兼容。

## 旧测试断言 diff

- `backend/api/tests/test_public_policy.py`：扩展 capability 名称集合，并新增 `ai_byok` 默认关闭和 BYOK route 被关闭策略拒绝的断言。现存 feature、公共只读策略与订阅断言保留。
- `backend/api/tests/test_production_settings.py`：配置探针和期望值新增 `AI_BYOK_ENABLED`；保留原有设置默认值、安全项、非法值测试，另加新 flag 的严格解析断言。
- `frontend/tests/App.readOnly.test.tsx`：在原禁用 route 参数表追加 `/settings/ai`；原 `/settings/chatgpt` 与其它 route 保留。
- `frontend/tests/pages/SettingsPage.test.tsx`：只新增 `/settings/ai` 链接断言；原 `/settings/chatgpt` 断言保留。
- **弱化或删除旧断言：无。** `git diff` 对应改动均为新增 feature fixture/assertion 或新增 route 场景。

## 本地与真实 provider 验证状态

| 层级 | 状态 | 说明 |
| --- | --- | --- |
| 本卡 provider API 调用 | **0 次** | socket guard 在 catalog/保存/列表/别名更新测试中禁止出网；浏览器保存不触达 provider |
| SDK_LOCAL | **N/A（T01 不执行 SDK）** | T01 只保存凭据，不属于 SDK 兼容性验证 |
| PROXY_LOCAL | **NOT_RUN** | 本卡无 Proxy 请求 |
| PROVIDER_REAL | **NOT_RUN** | 未使用 DeepSeek 或其他真实 Key；本地协议通过不代表任何厂商真实兼容 |
| 合成账户本地 UI 验收 | **PASS** | 上述回环服务、隔离 SQLite 和 Codex in-app browser 完成 A/B 隔离与 CRUD 完整流程 |
| 生产 / 真实用户 UAT | **NOT_RUN** | 未连接生产环境或真实用户账户 |

公开文档查阅仅用于核对受信登记信息；DeepSeek 文档当前列出 OpenAI-compatible base URL `https://api.deepseek.com`：[DeepSeek API Docs](https://api-docs.deepseek.com/)。没有向该地址发出请求。

## 可复现用户路径与剩余验证

登录用户打开 `/settings/ai`，选择固定官方端点，输入 API Key 并保存；成功后 Key 输入框清空，只显示掩码及“未测试”。列表支持刷新、改连接名、替换 Key、停用/启用和删除。另一个账户的列表不显示该连接；直接改其他用户 UUID 返回 404。所有更改仍由 Session/CSRF 与服务端 owner 校验保护。

未验证项：真实 SDK/Proxy/厂商调用、生产部署和真实用户 UAT，均保持 NOT_RUN。旧 epoch 的 worker 消费端已在下游 T05 PR #39 用合成 worker 集成验证，但该 PR 尚未合并，且 T01 PR #34 自身不包含该 worker。`npm ci` 在已有锁文件下安装依赖时显示 19 个 audit findings；本卡未升级依赖或更改 lockfile。
