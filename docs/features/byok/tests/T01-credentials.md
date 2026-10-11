# Test T01 · 个人 Key 连接增删改停

对应：[T01 Task](../tasks/T01-credentials.md)。

> **已执行；T01-03 的真实在途 worker/提交端集成仍为 NOT_RUN。** 本卡没有 worker 调用方，已验证替换/停用/删除会递增 credential epoch，并验证旧 epoch 无法再取得凭据。没有据此宣称真实 provider 兼容。

| 用例 | 场景 / 失败注入 | 结果 | 证据 |
| --- | --- | --- | --- |
| T01-01 | 新增、名称更新、替换、停用/启用、删除；列表从数据库恢复最新状态 | PASS | API CRUD/AAD 测试；页面新增、改名、替换、停用、删除测试；GET 只返回掩码 |
| T01-02 | 其他用户、匿名、缺 CSRF、跨站 Origin 尝试访问/写入 | PASS | API 测试验证 owner 隔离、匿名拒绝、CSRF 及 Origin 检查；其他用户得到 404 |
| T01-03 | 替换/停用/启用/删除后，旧 credential epoch 再读取 | PARTIAL | `require_active_connection` 直接拒绝陈旧 epoch；在途 worker 在 T01 范围内不存在，端到端“不提交结果”集成验证为 NOT_RUN |
| T01-04 | 读取、保存、替换、改名不触达 provider；状态不冒称已验证 | PASS | 受控 socket connect 禁止测试、状态固定 `not_tested`；UI 无测试动作且 Key 不进入浏览器持久存储 |
| T01-05 | 功能开关关闭、只读模式、缺加密密钥 | PASS | API 验证拒绝写入；缺密钥返回通用 503 且不持久化凭据；设置默认关闭 |

## 执行环境

| 项目 | 结果 |
| --- | --- |
| 基线 `origin/feat/byok-user-api-keys` 本地 tracking ref | `3cd584c95acd52bc533bba0b55eab75b35c41ad5` |
| T01 实现代码 SHA（证据文档之前的提交） | `326028c` |
| OS / 架构 | Linux 7.2.5-3-omarchy x86_64 |
| Python / Django / DRF / cryptography / SQLite / pytest | 3.14.8 / 6.1.2 / 3.18.3 / 50.0.2 / 3.53.1 / 9.1.1 |
| Node / npm / Vitest | 26.7.0 / 11.19.0 / 4.1.7 |
| 数据库 | 临时 SQLite 文件 `/tmp/byok-t01-*.sqlite3`；未打开仓库内 DB |
| 凭据 | 仅测试内合成账户、合成 Django secret、合成 AES 密钥和合成 provider Key；未读取既有 Key 或真实环境凭据 |
| 隔离 | Python venv 和空 HOME 在 `/tmp`；测试使用 `env -i`；`chromadb` 未安装，使用仅供测试导入的 stub（若业务路径调用会立即失败） |
| 浏览器 | Vitest DOM 测试；真实浏览器 / 手工验收 NOT_RUN |

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
152 passed, 2 warnings in 28.87s
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
| UAT | **NOT_RUN** | 未启动真实浏览器或真实用户账户 |

公开文档查阅仅用于核对受信登记信息；DeepSeek 文档当前列出 OpenAI-compatible base URL `https://api.deepseek.com`：[DeepSeek API Docs](https://api-docs.deepseek.com/)。没有向该地址发出请求。

## 可复现用户路径与剩余验证

登录用户打开 `/settings/ai`，选择固定官方端点，输入 API Key 并保存；成功后 Key 输入框清空，只显示掩码及“未测试”。列表支持刷新、改连接名、替换 Key、停用/启用和删除。另一个账户的列表不显示该连接；直接改其他用户 UUID 返回 404。所有更改仍由 Session/CSRF 与服务端 owner 校验保护。

未验证项：真实浏览器 A/B 手工验收；worker 接入后的旧 epoch 在途提交拦截；任何官方 SDK/Proxy/真实厂商调用。以上保持 NOT_RUN，留给对应后续实现卡验证。`npm ci` 在已有锁文件下安装依赖时显示 19 个 audit findings；本卡未升级依赖或更改 lockfile。
