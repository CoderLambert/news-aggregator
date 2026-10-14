# 国内医疗来源验收清单

## 自动验证

| 验证 | 结果 |
| --- | --- |
| Django system check 与迁移差异检查 | PASS |
| 全量后端 `api/tests` | PASS：1084 项，114.91 秒；1 个第三方 ChromaDB Python 3.16 弃用预警 |
| 动态 JSON Spider 独立 SQLite 全链路 | PASS：`Source → NewsSourceItem → News`，条件状态成功提交 |
| 前端 TypeScript | PASS |
| 前端 ESLint | PASS |
| 前端 Vitest | PASS：84 个文件、566 项 |
| 前端生产构建 | PASS |
| 部署相关回归 | PASS：350 项，6.32 秒 |
| Playwright 隔离管理流程 | PASS：登录、新建、探测错误展示与恢复、审批、试运行、启用、刷新 |

Playwright 使用临时 SQLite 和临时超级管理员。为避免额外访问出版方，探测先验证一个不可达测试域名的错误恢复，再在隔离数据库中注入当前版本的 `SUPPORTED` 探测状态以继续审批流程。这是界面和状态机验收，不是真实上游成功验收。

主要命令：

```bash
PYTHONPATH=backend:crawler uv run --with 'feedparser>=6.0.12,<7.0' \
  --python backend/venv/bin/python python -m pytest -q backend/api/tests
PYTHONPATH=backend backend/venv/bin/python -m pytest -q scripts/deploy/tests
cd frontend && npm run typecheck && npm run lint
cd frontend && npm run test:run -- --reporter=dot
cd frontend && npm run build
backend/venv/bin/python backend/manage.py check
backend/venv/bin/python backend/manage.py makemigrations --check --dry-run
git diff --check
```

## 产品人工验收

- [ ] 在非生产环境确认六个迁移来源全部显示，且调度关闭。
- [ ] 检查出版者、频道、分类、域名、读取政策和正文许可。
- [ ] 对可用源重新探测，人工对照样本标题、身份和时间字段。
- [ ] 单独审批一个源，执行单次试运行，检查摘要、原文链接和来源映射元数据。
- [ ] 确认无正文许可时 `full_content` 为空；有许可时正文通过完整性和 CAS 校验。
- [ ] 确认 UDI 只产生 `regulatory_data` 公告/增量条目，不下载或伪装产品主数据。
- [ ] 确认修改入口、域名或解析规则后，审批失效且调度关闭。
- [ ] 观察一个完整调度周期的 Worker 心跳、成功、失败、冷却和下次轮询。

## 未通过的生产门槛

- 未对任何新渠道执行生产启用。
- 国家卫健委和国家药监局资讯入口仍为 `BLOCKED` HTTP 412，没有绕过。
- 中新网健康 Feed 可解析，但探测时最新条目停在 2026-03-06。
- 当前证据是本地代码、固定 fixture、隔离数据库和低频官方入口探测，不代表生产长期稳定性。
