# ChatGPT 订阅重授权、独立撤销与部署身份管理

- 日期：2026-10-10
- 分支：`feat/ui-ux-workbench-redesign`
- 本次提交范围：修正本地 ChatGPT 订阅授权的部署身份、返回登录提示与撤销行为，并记录用户操作和公网适配边界。

## 变更目标

已有账号的普通重授权应保留可用凭据，完成身份验证后再替换；用户明确撤销时停止调用并清除凭据，不自动重新登录。网站用户的连接、Token 和活动账号独立，部署级 host ID 保持稳定。

用户操作已明确为四种情况：首次连接点“连接新账号”；停止授权点“撤销授权”；已授权账号再次授权直接点原卡片“重新授权”；已撤销账号恢复时也手动点原卡片“重新授权”。恢复原账号不应通过“连接新账号”重复注册。

## 实际改动

| 文件或区域 | 模块 | 改动 |
| --- | --- | --- |
| `backend/api/models.py` | 订阅数据 | 用部署级 `ChatGPTOAuthHost` 表达运行环境；连接增加加密 ID Token |
| `backend/api/migrations/0023_chatgpt_user_oauth_hosts.py` | 迁移 | 创建兼容的过渡 host 模型，取消旧进行中授权，保留旧 host 表到迁入完成 |
| `backend/api/migrations/0024_chatgpt_deployment_oauth_host.py` | 迁移 | 收敛部署级 host；删除旧表前保留原安装的 host ID，不清除用户或连接凭据 |
| `backend/api/migrations/0025_chatgpt_connection_id_token.py` | 迁移 | 为连接添加 `encrypted_id_token`，旧连接默认无账号提示 Token |
| `backend/api/services/chatgpt_subscription.py` | OAuth 服务 | 原子持久化部署实例 UUID；普通重授权使用原 client 与账号提示；验证后加密保存 ID Token；撤销先停止使用、再尝试远端撤销、最后清理本地凭据 |
| `backend/newsaggregator/settings.py`、`.env.example` | 配置 | 添加部署实例标识与文件位置配置 |
| `.gitignore`、`.dockerignore` | 运行数据 | 排除部署实例运行目录 |
| `frontend/src/pages/ChatGPTSubscriptionSettings.tsx` | 设置界面 | 区分新增、重新授权与撤销；显示尚未收到回调；撤销后显示已断开且不自动登录；撤销期间暂停新登录操作 |
| `backend/api/tests/test_chatgpt_subscription.py` | 后端回归 | 覆盖账号提示、重授权凭据保留、撤销重试、用户隔离及旧数据库升级 |
| `frontend/tests/pages/ChatGPTSubscriptionSettings.test.tsx` | 前端回归 | 覆盖原卡片重新授权；远端确认/未确认撤销均不调用连接 API 或打开登录窗口 |
| `README.md`、`docs/startup.md`、`docs/chatgpt-subscription-oauth.md` | 文档 | 记录持久化、登录流程、四种操作、额度归属、超时实测与待实施公网接入方案；同步现有 Obsidian 笔记 |

## 实现与兼容性

同一部署的所有网站用户共享非敏感 host 标识，但各自保存已验证身份、issued client ID、Token 和活动账号。返回登录携带所选连接的 `id_token_hint` 和已验证邮箱 `login_hint`，不会把其他连接的凭据混用。

普通重授权失败或取消不会主动撤销原凭据。撤销操作通过 generation fence 停止该连接、取消旧授权，并防止迟到的刷新或回调恢复旧状态；远端未确认撤销时，仍清理本地凭据并提示用户处理远端授权。

新迁移尚未发布。提交前检查补上了旧安装 host 的迁入，迁移测试使用独立测试数据库，不操作正在运行的 SQLite。旧部署更新应保留稳定凭据加密密钥和数据库；同一部署保留实例文件，新机器/VM 不复制旧实例 UUID。

## 验证

| 命令或检查 | 结果 |
| --- | --- |
| `docker compose exec -T app pytest -q backend/api/tests/test_chatgpt_subscription.py` | 45 项通过，包括旧 host、管理员权限与凭据保留的迁移测试 |
| `docker compose exec -T app pytest -c backend/pytest.ini -q backend/api/tests` | 235 项通过，包含上述订阅测试 |
| `PYTHONPATH=<repo>/backend:<repo>/crawler backend/venv/bin/python -m pytest -c backend/pytest.ini -q tests/backend tests/crawler` | 44 项通过；一个 ChromaDB 依赖弃用警告 |
| `cd frontend && npm run test:run` | 58 个测试文件、373 项通过；测试环境提示未实现 `window.scrollTo`，不影响结果 |
| `cd frontend && npm run typecheck` | 通过 |
| `cd frontend && npm run lint` | 通过 |
| `cd frontend && npm run build` | 通过 |
| `python3 scripts/validate_build.py` | 构建产物检查通过 |
| `docker compose exec -T app python backend/manage.py check` | 无系统问题 |
| `docker compose exec -T app python backend/manage.py makemigrations --check --dry-run` | 无遗漏迁移 |
| `git diff --check` | 通过 |
| docs 与 Obsidian 笔记逐字比较 | 一致 |

## 分支合并范围

本次分支合入 main 时，还包含两条此前已提交的变更：

- `4f882f4`：工作台界面改版、暖色纸张主题和非阻塞助手，涉及 Header、新闻卡片、聊天助手、全文阅读、列表/收藏/检索页及样式。
- `dcc00c7`：Compose 挂载宿主机前端构建目录，让当前单机部署使用最新构建产物。

上述已有 UI 变更已经纳入本次全量前端测试、类型检查、Lint 与构建验证。本次新提交不重复修改或改写这两条历史提交。

## 限制与后续工作

- 已实测“不先撤销、直接重新授权”成功；“撤销后再次登录”曾出现 OpenAI 页面超时，其具体外部请求原因尚未定位。独立撤销不会清除 OpenAI 浏览器 Cookie，也不是超时修复。
- 当前仍使用本地 loopback 授权。公网接入的正式客户端、HTTPS 回调和订阅使用资格需要按 OpenAI 批准的集成配置落实，文档中的公网模式尚未实现。
- 多用户的凭据隔离不增加订阅额度：连接不同 ChatGPT 账号各用各的额度，连接同一账号会累计使用同一订阅。
- 运行中的 `backend/db.sqlite3` 修改不纳入本次提交；不提交 Token、环境密钥、运行实例文件或生成的前端构建产物。
