# NewsHub｜本地 Codex 合并验收合同（2026-10-14）

> 仓库：`CoderLambert/news-aggregator`
> 验收基线：`main@5afbcaa7a45d30ebebb22dfca8a35db129313c42`
> 参考已合并 PR：[#58–#67](https://github.com/CoderLambert/news-aggregator/pulls?q=is%3Apr+is%3Amerged)
> 该基线 GitHub Actions `38525934475` 已成功；验收以本地运行结果为准，不能把线上 CI 视为本地测试已执行。

## 0. 执行规则（发给 Codex）

你是 **只执行验收、不自行开发、不部署** 的独立验收 Agent。严格按本文件执行：

1. 首先确认工作区干净、远程正确、`origin/main` 提交不低于本合同的 40 位基线。**如果 `main` 已前进**，记录新 SHA、识别后续改动，并以新 HEAD 重新测试；禁止强制回退、`reset --hard`、自动 cherry-pick 或隐藏本地改动。
2. 所有自动测试使用隔离测试数据库和 Fake Provider；不得连接 `news.lambert.host`、生产 SQLite、真实 OAuth/BYOK 密钥；不得发真实付费模型调用或抓取源站。
3. 先自动化检查，再输出供我手动验收的步骤与明确 PASS/FAIL/NOT_RUN；**不得自动代替我做真实浏览器/生产验收**。
4. 不修改业务代码、不自动合并、不部署；如发现失败，仅记录 SHA、复现命令、日志路径、根因和建议修复。需要开发时另开独立任务。
5. 不输出 `.env`、凭据、Cookie、真实文章私有内容或完整数据库。测试环境仅使用随机/合成数据。

## 1. 准备与基线

```bash
set -euo pipefail
git status --short
git remote -v
git fetch origin main
git rev-parse origin/main
git log -1 --format='%H %cI %s' origin/main
```

确认没有本地未提交的工作；如有，先提示停止，**不要清理或覆盖用户更改**。在隔离工作树/新克隆执行自动测试：

```bash
git worktree add --detach ../news-aggregator-accept origin/main
cd ../news-aggregator-accept
git rev-parse HEAD
```

若 worktree 目录已存在，请使用新的唯一目录，禁止覆盖。

## 2. 依赖与静态验证

使用 `Node 22`（匹配 CI）及 `Python 3.12`、Docker（可选，限本地隔离镜像）。保持 `frontend/package-lock.json` 不变。

```bash
cd frontend
npm ci
npm run typecheck
npm run lint
npm run test:run
npm run build
cd ..
```

后端环境优先复用**专为验收创建的** `backend/venv`；若没有，按 CI 工作流 `.github/workflows/ci.yml` 与 `backend/requirements.txt` 安装（项目当前 CI 在安装依赖之前先安装 CPU-only torch）。不要安装到系统 Python。检查设置：

```bash
PYTHONPATH=backend:crawler RUN_MAIN=true backend/venv/bin/python -m pytest --collect-only -q tests/ backend/api/tests/ scripts/deploy/tests/
PYTHONPATH=backend:crawler RUN_MAIN=true backend/venv/bin/python -m pytest -q tests/ backend/api/tests/ scripts/deploy/tests/
PYTHONPATH=backend:crawler RUN_MAIN=true backend/venv/bin/python backend/manage.py makemigrations --check --dry-run
```

`makemigrations --check --dry-run` 需使用测试/合成配置；若环境变量不足，按 CI/文档补充合成值，不用生产 `.env`。仅当 Docker 安全可用且用户本地资源允许时，按 `docs/deployment/release-gates.md` 执行 G1 隔离浏览器 smoke；**不得执行** `deploy.sh --execute`、`restore.sh --execute`、源站真实爬取或真实模型调用。

## 3. NH-01～NH-15 合并功能验收矩阵

每项提供：证据截图或日志、实际结果、PASS/FAIL/NOT_RUN、发现 Issue 建议。仅以下 10 项是已经合并的开发功能；其他 NH 任务尚未以“完成”标记。

| ID / PR | 自动验证（隔离） | 用户手动验收 | 失败判据 |
|---|---|---|---|
| NH-01 / #58 | 完整 CI 同等命令；`NewsList.test.jsx` 分页用本地化可访问名称 | 资讯列表进入第 2 页，键盘触发、URL 与返回正常 | CI 红或无障碍按钮查询失败 |
| NH-02 / #59 | 检查迁移 `0045`；ORM 删除有文章/订阅的 Source/Category 必须 `ProtectedError`；未引用可删除；收藏/聊天/屏蔽仍在 | 本地测试后台尝试删除被引用来源/分类，确认无法删除，历史仍在 | 任何级联删除或迁移变更丢数据 |
| NH-03 / #60 | 两来源同 URL、HN 二次改链、同主源安全更正、旧 revision CAS、冲突测试 | 从聚合来源跳转及阅读原发布者文章，不能串台/覆盖收藏 | 次级来源改写主文章 ID/URL/正文 |
| NH-04 / #61 | 41 条收藏/屏蔽跨页、URL `page`、切页、筛选、账号隔离、恢复末条 | 在本地放入 41 条模拟收藏和屏蔽并翻页、刷新、返回、恢复 | 仅能读 20 条、串账号或空白死页 |
| NH-05 / #67 | 迁移 `0046`；共享租约单用户/全站容量；旧租约/取消/超时；检查日志不含 key | 本地 Fake Provider 并发请求观察 `translation_capacity`、Retry-After；无需真实 Key | 超额仍调用模型、重复计费模拟次数超标、过期租约占满 |
| NH-08 / #65 | 105+ 旧 `pending`、一条新订阅，batch=1；证据变更可重审 | 开启本地建议/自动归组（Fake AI），新增频道不被旧订阅阻塞 | 旧 pending 永久消耗队列名额 |
| NH-09 / #64 | HTML `body_partial` + Jina disabled；受禁来源仍 unsupported | 资讯详情对模拟部分正文不应显示永久不支持 | 可恢复质量错误被覆盖为 unsupported |
| NH-12 / #66 | `news,discussion` OR 过滤；非法枚举 400； keyword/semantic/hybrid 走同样过滤范围 | 高级搜索勾选两个来源类型，可同时看到两个类型的结果 | 实际只返回第一个选择的类型 |
| NH-13 / #63 | 人为延迟网络响应，条件切换过程中无旧结果伪装；Query Key 不串用户 | 低速网络切换关键词/来源、排序，结果与 URL 一致 | 旧标题当作新查询结果展示 |
| NH-15 / #62 | PATCH 只给 `topics` 不清空简介，只给 `description` 不清空主题；无变化不增 revision | 管理来源元信息分别修改简介/主题 | 未修改的另一字段被清零 |

特别关注组合回归：NH-12 与 NH-13 在同一高级搜索页；NH-02/05 迁移 0045/0046 依次作用于相同数据库；NH-08/15 共用智能频道数据和预览证据。

## 4. 数据库迁移与恢复（只允许临时 DB）

- 在自动生成的**隔离 SQLite** 上执行完整 migrations，并确认 `makemigrations --check` 不产生新变更。记录 0045 与 0046 是否生效。
- 合成数据准备：一组 Source/Category、News、Favorite、BlockedNews、ChatSession、ChannelSubscription、SharedArticleTranslationTask；测试升级前后的主键、关系和限制不变。
- 在同一临时数据库上，测 WAL 下并发入库、旧租约超时、重复提交与队列恢复。不得用生产数据复制样本。
- 针对 `scripts/deploy/backup.sh` 和 `restore.sh`，优先跑仓库已有隔离单测、参数校验及 dry-run；任何 `--execute` 必须局限 Codex 明确创建的临时文件并有明确来源路径证据；不能操作真实容器卷。
- 不得声称成功运行了生产迁移、异机恢复或线上回滚。

## 5. 手动浏览器验收建议

使用开发模式、本地测试账号、模拟内容，不访问公网网站。按顺序检查：

1. 首页：筛选组合（范围+地区+来源+分类）、排序与重复新闻、分页、移动端响应、空状态、错误/重试。
2. 文章详情：摘要/全文区分、阅读返回位置、正文权限、收藏/屏蔽/撤销、正文变更后的翻译显示。
3. 收藏管理：41+ 条翻页、标签切换、历史回退、最后一项恢复、切换账户。
4. 高级搜索：新闻+讨论等多类型 OR、切换关键词/排序与慢网络、清空筛选。
5. 频道：订阅同源多组、手动排除自动归组、分类预览/取消/撤销、管理员 PATCH 保留未提交字段。
6. 翻译（Fake Provider）：两个账号同时提交多篇，达到容量后明确报错，不静默使用站点付费 Key；SSE 断流重连无重复结算。
7. 键盘与移动端：Tab、Enter、Escape、对话框焦点返回、屏幕阅读器标签、浅色/深色对比。

以上仅是用户可执行的手动验收清单；Codex 如果没有真实浏览器环境，应标 `NOT_RUN`，不要推断 PASS。

## 6. 统一验收门槛

- `PASS`：精确同一 HEAD 上所有适用测试实际成功、没有本次引入的 P0/P1、所有迁移在隔离 DB 验证、无生产/密钥/付费调用。
- `CONDITIONAL_PASS`：所有自动门禁绿，但真实浏览器或生产事项仍 `NOT_RUN`，可进入**人工验收**，不可写“生产已验收”。
- `FAIL`：核心用例失败、账密隔离破坏、文章历史丢失、数据库迁移不一致，或完整 CI 没有完成。
- `BLOCKED`：缺失工具/系统资源导致无法运行；列确切缺失项，不把阻塞算成功。

## 7. Codex 交付物（仅本地）

建议在本地工作树外新建 `acceptance-output/` 并提供：

- `RESULT.md`：HEAD、环境版本、每项结果、失败优先级、最终 PASS/CONDITIONAL_PASS/FAIL。
- `commands.log`：命令与退出码、必要的截断日志，不含密钥。
- `manual-checklist.md`：逐项给我手动验收，不代替我勾选。
- `issues-to-fix.md`：每个失败的最小复现与建议修复，不自动改代码。

**完成后立即停下。后续生产上线、备份/恢复、真实 OAuth/BYOK、付费模型和新的功能开发均需独立授权。**
