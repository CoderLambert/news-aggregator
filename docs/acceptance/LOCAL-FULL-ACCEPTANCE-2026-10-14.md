# NewsHub 全功能本地验收报告（NH-01～NH-33）

## 1. Executive Summary

**最终更新（2026-10-15）：`LOCAL_INCOMPLETE`。生产门槛：`NOT_RUN`。**

固定基线的初次结论为 `LOCAL_FAIL`；第 12～14 节记录随后完成的缺陷修复、固定提交复验和 NH-30 有限真实访问。最终修复提交为 `be23cb60ab74646fb550bed7d018d9b2a441186f`。当前没有未修复 P0/P1 代码缺陷；完整移动/平板/主题/慢网/Mock AI/TTS 浏览器矩阵和七项生产操作员门槛仍未完成，因此不能宣称本地完整验收通过或可正式发布。

固定基线 `1d225adbb72855770fbf422f96ebc1fc55662cb6` 的前端 84 个 Vitest 文件、566 个用例全部通过；后端三个指定测试根目录收集 1755 项，并在 CI 对齐环境下得到 **1755 passed、1 warning**。全新隔离 SQLite 的迁移、完整性、关键唯一约束和索引通过。生产镜像构建、固定 SHA、非 root 用户、Compose 解析、发布脚本、备份恢复合同和 G1 本地域名门禁通过。

未达到“本地完整验收通过”的原因：

- **P0：0。** 未发现身份隔离突破、密钥泄露或不可逆数据丢失。
- **P1：0 个未修复代码缺陷。** 初次发现的 G2 三项缺陷和随后发现的 `crawl all` 并发预算饥饿、错误成功退出均已修复并回归。
- **NH-30 来源许可：证据已记录。** 负责人 Lambert 批准 51 个启用来源，其中 21 个允许全文、30 个允许摘要；图片二进制存储均为 NO。离线校验通过。
- **NH-30 内容质量：正式门槛仍为 `NOT_RUN`。** 用户停止全量真实访问前完成 26/51 个来源的逐源运行；25 个来源和 326 个排队全文任务未执行，不推断为通过。
- 初次发现的 HSTS、Category 排序、Playwright task 和 Mermaid 时序问题均已修复；细节及证据见第 12～14 节。
- 移动端 `390×844`、平板、深浅主题、真实慢网/取消、完整频道与 Mock AI 交互没有独立端到端浏览器记录，相关 NH 项标为 `PARTIAL`，没有推断为通过。
- G3、真实生产授权、真实 OAuth、真实付费模型、异机恢复、密钥恢复、完整来源人审样本、2C/4GB 压测均为 `NOT_RUN`。

## 2. 固定版本与环境

| 项目 | 实际值 |
|---|---|
| 执行日期 | 2026-10-15，Asia/Shanghai |
| 固定验收 SHA | `1d225adbb72855770fbf422f96ebc1fc55662cb6` |
| 提交时间 | 2026-10-14 22:28:38 +08:00 |
| 对应提交 | `feat(newshub): deliver remaining A09 workflows and offline acceptance gates` |
| `origin/main` | `1d225adbb72855770fbf422f96ebc1fc55662cb6` |
| 原工作区分支/HEAD | `fix/workspace-layout-admin` / `72070e977b25c1d4a1486c91af04a6413b6e58a2` |
| 隔离 worktree | `/tmp/newshub-local-acceptance-20261015/source`，detached、固定 SHA、验收结束时无跟踪文件改动 |
| Node / npm | 22.23.3 / 10.9.9 |
| host Python | 3.12.14 |
| 镜像 Python | 3.12.15 |
| Docker / Compose | 29.7.2 / 5.5.1 |
| Chromium / Playwright | 152.0.7977.82 / 1.62.0 |
| 生产镜像 | `newshub:local-1d225adbb72855770fbf422f96ebc1fc55662cb6` |
| 最终镜像 ID | `sha256:18e5a7cb5a09656400fbc8ca02ea3e56b5de5324f98b73072ff83915def251a3` |
| 镜像用户 | `10001:10001` |
| Nginx | `nginx@sha256:0985e772fb9f729e6fa0980da05fca5d9c468e870eed43071545afa9d2e27d94` |
| 临时证据根目录 | `/tmp/newshub-local-acceptance-20261015` |

原工作区已有 `backend/db.sqlite3` 修改和 `docs/features/NEWSHUB-CODEX-LOCAL-ACCEPTANCE-2026-10-14.md` 未跟踪文件，均未修改、隐藏或清理。没有读取真实 `.env`；隔离 worktree 中不存在 `.env`。验收使用合成密钥、合成账号、隔离 SQLite、禁用公网出口的容器和 Mock/禁用 AI。

已核对 `.github/workflows/ci.yml`、`docs/deployment/release-gates.md`、`docs/startup.md`、`docs/deployment/NH28-NH31-operator-acceptance.md`、`docs/deployment/production-containers.md`、`compose.prod.yaml` 和 `compose.workspace.prod.yaml`。

## 3. 自动测试与部署汇总

### 3.1 前端

| 命令 | 退出码 | 耗时 | 结果/证据 |
|---|---:|---:|---|
| `npm ci` | 0 | 7.261s | 535 packages；`logs/frontend-npm-ci.log` |
| `npm run typecheck` | 0 | 3.359s | PASS；`logs/frontend-typecheck.log` |
| `npm run lint` | 0 | 6.683s | PASS；`logs/frontend-lint.log` |
| `npm run test:run` | 0 | 10.582s | 84 files、566 tests PASS；`logs/frontend-test-run.log` |
| `npm run build` | 0 | 0.784s | Vite 8.0.13，4364 modules；`logs/frontend-build.log` |

本地数量与给定 CI 参考值完全一致。Vitest 输出一条 jsdom `Window.scrollTo()` 未实现提示，不计为失败或测试 warning。

### 3.2 后端与数据库

| 命令/检查 | 退出码 | 耗时 | 结果/证据 |
|---|---:|---:|---|
| 三根目录 `pytest --collect-only -q` | 0 | 4.282s | 1755 collected；`logs/backend-collect.log` |
| 首次镜像内全量 pytest，无 Node | 1 | 134.239s | 1754 passed、1 failed、1 warning；仅环境缺少 Node；`logs/backend-pytest.log` |
| 失败项 + Node 22 定向回归 | 0 | 1.525s | 1 passed；`logs/backend-targeted-node22.log` |
| 三根目录全量 pytest + Node 22 | 0 | 133.604s | 1755 passed、1 warning；`logs/backend-pytest-node22.log` |
| `manage.py check` | 0 | 2.181s | 0 issues；`logs/django-check.log` |
| `manage.py check --deploy` | 0 | 2.139s | 2 HSTS warnings；`logs/django-check-deploy.log` |
| `makemigrations --check --dry-run` | 0 | 2.186s | No changes detected；`logs/django-makemigrations-check.log` |
| 全新 SQLite `migrate --noinput` | 0 | 17.131s | 0001～0047 及 Django migrations 全部应用；`logs/django-migrate-fresh.log` |
| 第二次 `migrate --noinput` | 0 | 1.974s | No migrations to apply；`logs/django-migrate-noop.log` |
| SQLite schema/integrity 检查 | 0 | 0.018s | integrity `ok`；18 个关键命名约束/索引齐全；News URL 唯一索引存在；`logs/sqlite-schema-verify.log` |

三个测试根目录 `tests/`、`backend/api/tests/`、`scripts/deploy/tests/` 均成功收集。全量回归实际覆盖并发重复发现、CAS/revision、旧租约、SQLite busy、进程锁、SIGTERM/SIGKILL 恢复、幂等请求、迁移兼容、备份恢复和 fail-closed 路径。未对用户现有数据库执行 migrate。

Host 虚拟环境安装 CPU-only PyTorch 时远端索引发生 `SSL: UNEXPECTED_EOF_WHILE_READING`，退出 1；随后改用固定 SHA 生产镜像内的 Python 3.12.15、torch 2.14.1+cpu，挂载 CI 对齐 Node 22 只读完成全量测试。证据为 `logs/backend-torch-cpu-install.log`。

### 3.3 发布脚本、镜像与门禁

| 项目 | 退出码 | 耗时 | 结果/证据 |
|---|---:|---:|---|
| production 镜像构建 | 0 | 7.408s（缓存重验） | 固定 SHA、用户 10001:10001；`logs/docker-build-final.log` |
| `compose.prod.yaml config --quiet` | 0 | 0.050s | PASS；`logs/compose-prod-config.log` |
| prod + workspace Compose | 0 | 0.041s | PASS；`logs/compose-workspace-config.log` |
| Compose 安全摘要 | 0 | 0.062s | 环境键、卷、secret、限制；`logs/compose-safe-summary.json` |
| release dry-run/fail-closed tests | 0 | 6.507s | deploy/rollback/smoke/backup/restore PASS；`logs/test_release_scripts.sh.log` |
| static export tests | 0 | 0.861s | PASS；`logs/test_export_static.sh.log` |
| preflight tests | 0 | 0.506s | PASS；`logs/test_preflight.sh.log` |
| local-domain 参数合同 | 0 | 5.701s | PASS；`logs/test_local_domain_args.sh.log` |
| release manifest describe | 0 | 1.448s | 65 migrations，static SHA 固定；`logs/release-manifest-current.log` |
| G1 私有卷备份恢复 | 0 | 35.530s | 完整性、0600、busy/tamper/stale/wrong DB 拒绝、清理均 PASS；`volume-acceptance/report.json` |
| G1 未改动本地域名门禁 | 0 | 30.985s | PASS；`newshub-local-domain-report-...9VtfmI/report.json` |
| G2 未改动门禁 | 2 | 20.014s | FAIL，停在 parent identity；`logs/g2-official-current.log` |
| G2 临时诊断适配 | 0 | 51.639s | 合成账号产品流程 PASS，但不是正式门禁；`newshub-local-domain-report-...r9ZsSY/report.json` |
| operator evidence init | 0 | 0.030s | 8 个 gate 全部 pending；`logs/operator-ledger-init.log` |
| operator evidence check | 2 | 0.033s | 8 个 gate `NOT_ACCEPTED`，符合 fail-closed；`logs/operator-ledger-check.log` |

channel-worker 合同：只挂载 `db-data`、`logs-data` 与一个 BYOK gateway secret；无 broad `env_file`；根文件系统只读；`cap_drop: ALL`；`no-new-privileges`；`tmpfs /tmp`；512 MiB；128 PID。它使用 host network 访问 loopback gateway，风险与原因已在仓库文档中声明。其他长期服务没有显式内存/PID 上限，因此 NH-31 不能据此通过。

健康检查只证明进程命令和 readiness；报告没有把 Worker 心跳等同于实际抓取成功，也没有启动默认真实 crawler。

## 4. NH-01～NH-33 逐项矩阵

证据路径均相对 `/tmp/newshub-local-acceptance-20261015/`；“全量后端”指 `logs/backend-pytest-node22.log`，“前端全量”指 `logs/frontend-test-run.log`。

| NH | 状态 | 本地证据 | 未满足条件 |
|---|---|---|---|
| NH-01 | PARTIAL | 前端全量；G1 首页/深链/搜索；`NewsList.test.jsx` | 未做 1440/390 真实分页、返回位置和全键盘矩阵 |
| NH-02 | PASS | 全量后端；迁移 0045；删除保护测试 | 本地数据不含真实历史，符合隔离要求 |
| NH-03 | PASS | 全量后端的 ingestion identity、secondary source、HN 与修复冲突测试 | 无实时发布者验证，按授权不执行 |
| NH-04 | PARTIAL | 前端收藏分页测试；G2 A/B 收藏所有权与删除 | 未在真实浏览器放入并翻阅 41+ 条收藏/屏蔽 |
| NH-05 | PASS | 全量后端 shared translation、capacity、lease、cancel、recovery；Mock provider | 真实付费模型调用不授权 |
| NH-06 | PASS | suggested questions 的预算、revision、重复请求、上下文范围测试；前端 hook tests | 真实模型不运行，属于要求内的 Mock 验收 |
| NH-07 | PASS | public policy、rate limit、search/request budget；G2 登录/注册限流 | 未作长期压力测试 |
| NH-08 | PARTIAL | channel pending fairness、智能分组和旧证据测试；前端 workspace tests | 未在浏览器执行 AI 预览/撤销完整流程 |
| NH-09 | PASS | full-content provider/status tests，Jina disabled 保留真实失败原因 | 无源站访问 |
| NH-10 | PASS | malformed title/URL/GUID 与 checkpoint 测试 | 无源站访问 |
| NH-11 | PASS | `not_due` 健康跳过及真实失败不被覆盖测试 | 无实际调度周期观测 |
| NH-12 | PARTIAL | keyword/semantic/hybrid + 多 source type 过滤后端测试；G1 keyword search | AI disabled，未浏览器执行三模式切换 |
| NH-13 | PARTIAL | 前端 LocalSearch/SearchBar/query cache/race tests | 未用真实浏览器节流执行慢网和取消请求 |
| NH-14 | PASS | Retry-After 200/429、oversize、日期与冷却测试 | 无真实源站响应 |
| NH-15 | PARTIAL | channel metadata PATCH/no-op revision 后端测试 | 未通过管理员浏览器分别编辑简介/主题 |
| NH-16 | PARTIAL | intake URL/credential validation、重复申请、review/receipt 后端与前端 tests | 未完成浏览器用户提交到管理员审核全链路 |
| NH-17 | PARTIAL | classification evidence、proposal/apply、stale evidence、人工 override tests | 未完成浏览器预览、重试、撤销、多账号流程 |
| NH-18 | PARTIAL | content review CAS/revision、incomparable body、管理员 API/前端组件 tests | 未在浏览器处理待复核正文 |
| NH-19 | PASS | publisher promotion 保留 News ID、历史和 source mapping 测试 | 无实时发布者校验 |
| NH-20 | PARTIAL | chat terminal receipt、complete/interrupted/failed、history reconciliation tests | 未执行真实浏览器 SSE 断开/恢复交互 |
| NH-21 | PARTIAL | crawler readiness/heartbeat/outcome tests；G2 管理员 dashboard 加载 | 未浏览器逐项观察冷却、下次轮询和失败原因 |
| NH-22 | PASS | category corrections dry-run/apply/idempotency/conflict/undo；primary publisher category tests | 无生产历史分类执行 |
| NH-23 | PARTIAL | TTS handshake、stream、atomic cache、interrupt、oversize tests | 未在浏览器播放、取消和恢复音频 |
| NH-24 | PASS | 两套 Compose 解析、least-privilege 摘要、release tests | host network 仍为已记录依赖；未做生产 gateway 连通验收 |
| NH-25 | PARTIAL | reading position、NewsDetail navigation、search focus tests | 未真实执行前进/后退/刷新/新标签和移动端焦点 |
| NH-26 | PARTIAL | token-aware editorial tests；真实发布时间/推断时间前后端 tests | 未浏览器查看管理文案与所有时间状态 |
| NH-27 | PARTIAL | full-body keyword 权限、持久预算、anonymous/unbounded 拒绝、三搜索模式 tests | 未浏览器对比“仅有全文”与“检索已保存全文”文案 |
| NH-28 | PARTIAL | research BYOK、预算、取消、恢复、citation/injection 合同 tests；G2 AI fail-closed | 正式 BYOK 授权与 hosted integration approval 为 NOT_RUN |
| NH-29 | PARTIAL | `volume-acceptance/report.json` 全部 PASS；release scripts PASS | 异机加密恢复和密钥恢复为 NOT_RUN |
| NH-30 | PARTIAL | `logs/source-policy-offline-audit.json`：57 total、51 enabled、6 disabled | 许可/转载/署名/审批/owner/rate budget 和人审真实样本为 NOT_RUN；发布阻塞 |
| NH-31 | PARTIAL | Compose 合同、限流、故障降级单测、G1 SSE 数据 | 无隔离 2C/4GB 代表性压测、阈值审批和生产监控证据 |
| NH-32 | PASS | display text 不改变 feed validators、semantic contract 才失效测试 | 未实时重新抓取，符合离线范围 |
| NH-33 | PARTIAL | research evidence、提示注入隔离、危险/未验证引用、readiness provenance tests | 未通过浏览器执行 Mock 研究会话和引用点击流程 |

## 5. 浏览器验收记录

### 5.1 正式 G1

| 页面/角色 | 操作 | 预期 | 实际 | 状态 |
|---|---|---|---|---|
| `/` 匿名只读 | HTTPS 打开首页 | HTTP 200、SPA root、无外连 | 符合；外部 host 请求被阻止 | PASS |
| `/news/<synthetic>` 匿名 | 打开深链并滚动正文 | HTTP 200，Mermaid 可见 | 符合，图表尺寸和文字被实测 | PASS |
| `/favorites` 匿名 | 打开私有深链 | 不调用收藏 API | 符合 | PASS |
| CSRF/Host/TLS | 初始化 CSRF、错误 Host、未信任 CA、错误 SAN | Secure/host-only/SameSite；拒绝错误边界 | 符合 | PASS |
| SSE fixture | 通过 Nginx 读取两帧 | 不被缓冲到全部完成 | first frame 6ms，total 1007ms | PASS |

截图：`newshub-local-domain-report-1d225adbb72855770fbf422f96ebc1fc55662cb6.9VtfmI/mermaid-g1.png`。

### 5.2 正式 G2 与诊断 G2

未改动 G2 在容器父身份检查处失败，尚未进入账号浏览器流程，状态为 **FAIL**。证据：`logs/g2-official-current.log`，退出 2。

为了采集后续产品证据，在临时目录使用三项最小诊断适配：接受脚本自己创建的两个 owned volumes；允许 production research 的 `hosted_integration_unapproved` 禁用原因；将管理员失效 UI 断言限定到登录 dialog。未改业务代码。诊断流程实际完成：

- 邀请注册 A/B，CSRF 轮换，Secure/HttpOnly/host-only/SameSite cookie；
- B 不能读取或删除 A 的收藏、聊天、研究记录；切换账号后 A 的缓存不泄露；延迟 `/api/auth/me/` 响应不能覆盖 B 身份；
- AI disabled 时 Chat POST 返回 403 且无 provider call；
- 普通用户管理员 API 403，页面不提前请求管理 API；
- A 的 same-origin CSRF 删除仅影响 A；
- 活跃管理员可读 dashboard/provider API；失效后旧 session 三个受保护 API 均为 403，UI 回到登录态；
- 注册/登录固定窗口限流返回 429 和 Retry-After，伪造 XFF 不产生新桶；
- 浏览器没有外部网络请求。

诊断截图：`newshub-local-domain-report-1d225adbb72855770fbf422f96ebc1fc55662cb6.r9ZsSY/g2-accounts.png` 和 `mermaid-g2.png`。诊断日志有六条 `Target closed` 未回收 task 警告，见 ACC-006。

### 5.3 未执行的浏览器矩阵

下列项没有实际浏览器证据，标记 `NOT_RUN`：桌面 1440×900 精确 viewport、移动 390×844、平板宽度、深浅主题切换、慢网络/请求取消、空列表/图片缺失/超长标题溢出、完整 Tab/Enter/Escape/焦点恢复、新标签行为、频道申请与 AI 分组全链路、Mock AI 聊天/翻译/TTS 的交互式断开恢复。对应代码有 Vitest/pytest 证据时，NH 状态仍只记 `PARTIAL`。

## 6. 安全与数据一致性结论

- **权限隔离：PASS（已覆盖路径）。** G2 诊断实测匿名、A/B、普通用户、管理员、失效管理员；跨用户收藏/聊天/研究读取与删除被拒绝。全量后端还覆盖 read_only/full、CSRF、owner-scoped idempotency 和 query cache owner key。
- **模型与费用保护：PASS（Mock/禁用范围）。** 未配置用户模型时 Chat 403，诊断 G2 没有 provider call；单元/集成测试覆盖 BYOK、预算、并发、lease、重复提交与 credential generation fence。没有真实付费调用。
- **密钥：PASS（本地边界）。** channel-worker 仅获得必需项目 secret；日志和报告没有真实密钥。未验证生产密钥恢复。
- **SSRF/外连：PASS（已覆盖路径）。** G1/G2 浏览器路由阻断外部 host；后端覆盖 URL/host/scheme/redirect/DNS pin/budget 合同。未实时抓取发布者。
- **XSS/提示注入：PASS（自动测试范围）。** Markdown/Mermaid security tests、research evidence tests 防止正文与外部网页成为 system instruction；未验证引用不会在真实浏览器中产生所有形式的危险点击。
- **CSRF/session：PASS。** 实测 Secure、host-only、SameSite=Lax；session HttpOnly；注册轮换 CSRF；写操作要求 same-origin token；logout 过期 session。
- **租约、CAS、revision：PASS。** 全量后端覆盖旧租约、乱序完成、正文 revision、翻译/建议缓存失效、worker 中断恢复和 SQLite busy。
- **删除与历史：PASS。** Source/Category 删除保护、publisher promotion 保留 ID/历史、NewsSourceItem 稳定映射均由全量后端验证。
- **生产 TLS 硬化：PARTIAL。** `check --deploy` 仅有 HSTS includeSubDomains/preload 两项 warning，详见 ACC-005。

## 7. 性能与稳定性结论

只记录本机实测数据，不外推为生产指标：

- 前端 Vitest：566 tests，10.23s（命令包装 10.582s）。
- 后端 pytest：1755 tests，131.81s（命令包装 133.604s）。
- 全新 SQLite 65 个 migration 应用：17.131s；再次 migrate：1.974s。
- G1 SSE：首帧 6ms，总时长 1007ms。
- 诊断 G2 SSE：首帧 6ms，总时长 1007ms。
- G1 当前镜像完整门禁：30.985s；诊断 G2：51.639s。
- G1 私有卷备份恢复合同：35.530s。

这些数据来自当前开发机与合成 fixture，不能代表 2C/4GB VPS 的 p50/p95/p99、RSS、队列容量或真实源站吞吐。NH-31 正式容量门槛为 `NOT_RUN`。

## 8. 缺陷与阻塞清单

### P0

无。

### P1

#### ACC-001：G2 parent identity 与自身 Compose 挂载矛盾

- 固定 SHA：`1d225adbb72855770fbf422f96ebc1fc55662cb6`
- 位置：`scripts/deploy/local_domain_acceptance.py:378-409`
- 复现：运行未改动 `local-domain-smoke.sh --execute --stage g2 ...`，退出 2。
- 根因：检查要求 app 恰好一个 mount，但 G2 生成的 app 同时挂载 owned `db-data` 和 `logs-data`。
- 最小修复：精确允许这两个 owned named volumes，同时继续拒绝 bind、foreign 和额外 volume。
- 回归：原始 G2 必须无需适配器通过；保留恶意额外挂载负例。

#### ACC-002：G2 capability 原因断言与生产 fail-closed 值不一致

- 位置：`scripts/deploy/local_domain_acceptance.py:1098-1103`；`backend/api/capabilities_views.py:59-64`
- 触发：绕过 ACC-001 后读取 production capabilities。
- 根因：G2 要求 research reason=`ai_disabled`，生产代码有意返回 `hosted_integration_unapproved`。
- 最小修复：断言 research 保持 disabled，并接受/精确要求生产环境的受控原因值。
- 回归：分别覆盖开发 AI-disabled 与生产 hosted-unapproved。

#### ACC-003：失效管理员登录按钮定位器歧义

- 位置：`scripts/deploy/local_domain_acceptance.py:1685-1687`
- 触发：失效管理员刷新后页面同时出现 header 登录按钮和 dialog 登录按钮。
- 实际：三个 protected API 已是 403，UI 正确显示登录 dialog，但 Playwright strict locator 匹配 2 个元素。
- 最小修复：将 locator 限定到 dialog 或稳定的单一 accessibility name。
- 回归：同时断言 API 403 与 scoped UI 登录态。

#### GATE-001：NH-30 来源许可与审批证据缺失

- 位置：`backend/api/services/source_policy.py:7`、`backend/api/services/sector_feeds.py:1`
- 实际：57 条策略、51 启用、6 fail-closed；schema 不含六项法务/运营字段。
- 最小闭环：逐来源提供官方入口、访问/转载许可、署名要求、审批日期、owner、rate budget；未批准来源保持 disabled。
- 回归：离线 ledger 校验所有 enabled policy 均有可校验证据；不能用公网可达性替代授权。

### P2

#### ACC-005：生产 HSTS 配置检查有两项 warning

- 位置：`backend/newsaggregator/settings.py:256-257`
- 实际：`security.W005`、`security.W021`。
- 建议：确认所有子域 HTTPS 和 preload 长期承诺后再启用；若有意不启用，应形成发布例外记录。

### P3

#### ACC-004：Category 分页 queryset 无稳定排序

- 位置：`backend/api/views.py:998-1002`
- 实际：DRF `UnorderedObjectListWarning`。
- 建议：添加显式排序和唯一 tie-breaker；跨页验证不重复、不丢失。

#### ACC-006：G2 完成后仍有未回收 Playwright task

- 位置：`scripts/deploy/local_domain_acceptance.py` 的 response listener/关闭流程。
- 实际：六条 `Task exception was never retrieved: Error('Target closed')`。
- 建议：关闭 context 前移除 listener 并 await/cancel+gather 所有 response tasks。

### 环境记录

- Host pip 的 PyTorch CPU index SSL EOF，已用固定镜像内环境完成验收，不是产品失败。
- 首次镜像内 pytest 缺 Node 导致 1 项失败；挂载 CI 对齐 Node 22 后定向和全量均通过，不是产品失败。

## 9. 未执行事项

| 项目 | 状态 | 原因 |
|---|---|---|
| G3 真实 task/worker/生产验收 | NOT_RUN | 超出本轮授权，仓库 harness 也明确保留 |
| 正式 NH-28 两个 gate | NOT_RUN | 无 hosted integration 正式授权；不做真实 OAuth/付费模型 |
| NH-29 off-host restore | NOT_RUN | 仅完成本机隔离 volume rehearsal |
| NH-29 key recovery | NOT_RUN | 未使用或恢复真实加密材料 |
| NH-30 source license | NOT_RUN | 缺逐来源许可与运营证据 |
| NH-30 content quality | NOT_RUN | 不授权实时批量发布者采样 |
| NH-31 2C/4GB capacity | NOT_RUN | 未建立独立 2C/4GB 代表性环境和阈值 |
| NH-31 degradation 正式门槛 | NOT_RUN | 单测不能替代运营环境演练 |
| 生产 DNS/TLS/firewall/监控 | NOT_RUN | 不授权修改公网或生产部署 |
| 真实 OAuth、真实 BYOK、真实付费模型 | NOT_RUN | 明确不授权 |
| 移动/平板/深浅主题完整浏览器矩阵 | NOT_RUN | 当前仓库没有对应完整 E2E；未临时另建第二套框架 |
| Django `REMOTE_ADDR` 真实代理观察 | NOT_RUN | 当前 endpoint 不暴露 WSGI `REMOTE_ADDR`；G1 只验证 proxy header echo |

`operator-evidence.json` 的八个 gate 保持 pending；checker 退出 2 并列出全部 `NOT_ACCEPTED`，没有把模拟测试冒充正式生产验收。

## 10. 最终发布建议

### 本地结论：`LOCAL_FAIL`

前后端代码回归、迁移、G1、镜像和备份恢复合同总体稳定，未发现 P0，也未发现产品权限隔离被突破。但正式 G2 在未改动脚本上可重复失败，存在三个 P1 发布门禁缺陷；NH-30 正式许可证据缺失；若干本地可执行的真实浏览器矩阵仍没有端到端证据。因此不满足本轮“本地完整验收通过”的结束条件。

建议统一修复 ACC-001～ACC-003 后只重跑 G2 及对应发布脚本回归；修复 ACC-004/ACC-006 并复核 HSTS 决策。随后补齐移动端、深浅主题、慢网取消、频道/Mock AI/TTS 的浏览器记录，再评估 `LOCAL_PASS`。

### 独立生产门槛：`NOT_RUN`

即使后续本地转为 `LOCAL_PASS`，NH-28～NH-31 八个 operator gate、G3、生产授权、异机恢复、来源许可、人审质量样本和 2C/4GB 压测仍必须独立完成并由负责人签字。

## 11. 工作区与新增文件

验收未提交、未推送、未创建 PR、未合并、未部署生产，也未修改业务代码。

原工作区最终预期状态：

```text
 M backend/db.sqlite3
?? docs/features/NEWSHUB-CODEX-LOCAL-ACCEPTANCE-2026-10-14.md
?? docs/acceptance/LOCAL-FULL-ACCEPTANCE-2026-10-14.md
```

前两项为验收前已存在的用户改动；本轮仅新增本报告。机器可读结果、日志、截图、临时诊断适配器和合成数据库保存在 `/tmp/newshub-local-acceptance-20261015/`，未加入 Git。

## 12. 修复回归附录（2026-10-15）

### 修复范围与状态

修复在隔离 worktree `/tmp/newshub-local-acceptance-20261015/source` 的分支 `fix/local-acceptance-findings-20261015` 中完成，基线仍为 `1d225adbb72855770fbf422f96ebc1fc55662cb6`。未提交、未推送、未创建或合并 PR。最终工作区差异指纹为 `af01886b77b0bb0e5c1d72887e324fdecd8d671a`；该值只用于标识未提交的本地验证镜像，不是 Git commit SHA。

| 编号 | 修复状态 | 修复与复核结果 |
|---|---|---|
| ACC-001 | RESOLVED | G2 精确允许 owned `db-data`、`logs-data` 两个 named volume，继续拒绝 bind、foreign、额外挂载及错误 owner/driver/scope/options；新增日志卷负例。 |
| ACC-002 | RESOLVED | G2 精确要求 research=`hosted_integration_unapproved`，其余禁用 AI 能力仍要求 `ai_disabled`；与生产 fail-closed 合同一致。 |
| ACC-003 | RESOLVED | 失效管理员登录按钮限定在 `dialog` 内查找；最终 G2 的 API 403 与 UI 登录态同时通过。 |
| ACC-004 | RESOLVED | Category queryset 按 `id` 显式稳定排序并新增回归断言；全量 pytest 不再出现 `UnorderedObjectListWarning`。 |
| ACC-005 | RESOLVED | production HSTS 调整为 31536000 秒并启用 includeSubDomains/preload；合成生产设置 `manage.py check --deploy` 为 0 issue、0 silenced。 |
| ACC-006 | RESOLVED | 三处 Playwright response completion 改为显式读取 `body()`；最终 G2 日志无 `Task exception was never retrieved` 或 `Target closed`。 |
| ACC-007 | RESOLVED | 修复回归中发现 Mermaid SVG 文本挂载时序抖动；先等待 SVG 可见及文本节点 attached，再执行标签、尺寸和颜色断言。失败截图与后续 PASS 证据均保留。 |
| GATE-001 | OPEN / NOT_RUN | NH-30 逐来源许可、审批 owner、署名与 rate budget 仍缺外部正式证据；没有伪造或自动放行。 |

### 自动与浏览器回归

| 验证 | 结果 | 证据 |
|---|---|---|
| 部署、生产设置、公共策略定向 | 211/211 PASS | `/tmp/newshub-local-acceptance-20261015/logs/`；首次容器缺 Node 的环境失败已用 Node 22 重跑排除 |
| 三测试根目录 collect | 1760 collected；补分类排序断言后最终总数 1761 | `logs/backend-fix-collect.log`、`logs/backend-fix-full-docker.log` |
| 修复主体全量 pytest | 1761 passed，0 warning，133.84s | `logs/backend-fix-full-docker.log` |
| 随后的 Mermaid 最终等待变更专项 | 153/153 PASS | `scripts/deploy/tests/test_local_domain_acceptance.py` 定向执行记录；最终 G1/G2 再次覆盖真实浏览器 |
| production `check --deploy` | PASS，`System check identified no issues (0 silenced)` | 合成密钥、独立 SQLite、production 环境 |
| 最终 G1 | PASS，cleanup PASS | `fix-smoke-tmp/newshub-local-domain-report-af01886b77b0bb0e5c1d72887e324fdecd8d671a.A1eLQ8/report.json`；`logs/g1-fix-final-rerun.log` |
| 最终 G2 | PASS，cleanup PASS | `fix-smoke-tmp/newshub-local-domain-report-af01886b77b0bb0e5c1d72887e324fdecd8d671a.inHym3/report.json`；`logs/g2-fix-final-rerun2.log` |
| 镜像 | `newshub:local-fix-20261015`，非 root `10001:10001` | image ID `sha256:9aa3047bca07661843b15e0390132a9a94abbb214a07c004c9ddc7e270e14d2a` |

最终 G2 无临时适配器，覆盖合成注册、登录/退出、A/B 用户数据隔离、延迟身份响应、普通用户管理员拒绝、管理员失效、CSRF、登录与注册限流、AI fail-closed、Mermaid、TLS 和 SSE。执行结束后无 G1/G2 容器或 volume 残留。

### 修复后的结论

ACC-001～ACC-007 的本地代码缺陷均已修复并获得可复核证据，原三个 G2 P1 发布门禁缺陷已关闭。正式发布结论仍保持 `LOCAL_FAIL`，原因是 GATE-001 的 NH-30 来源许可/审批证据仍未取得，且原报告列出的生产授权、G3、异机恢复、2C/4GB 压测及未执行浏览器矩阵没有因本次代码修复自动转为 PASS。

## 13. 最终提交复验与操作员门槛准备（2026-10-15）

本节取代第 12 节中“未提交工作区镜像”的状态描述；原始基线验收和中间失败证据仍保留。

### 已提交修复

- 分支：`fix/local-acceptance-findings-20261015`
- 远端：`origin/fix/local-acceptance-findings-20261015`
- 最终提交：`334b5d740a909681b56c41c0c7158ea39801c0dd`
- 提交链：`df8237ef12f05f8b7d968d0f3aae9d63f01bca1b`、`ed40f0dd01f9a7965894c0e7817686a12d1821b6`、`334b5d740a909681b56c41c0c7158ea39801c0dd`
- 推送方式：普通 push；未创建 PR、未合并、未 tag、未发布。

固定提交生产镜像为 `newshub:334b5d740a909681b56c41c0c7158ea39801c0dd`，image ID `sha256:31f3daa508b60ea86337dc2b698fa6e064b42129017bfac5f6c9df2f8930b932`，revision label 与 Git SHA 一致，运行用户 `10001:10001`。

| 验证 | 结果 | 证据 |
|---|---|---|
| Mermaid 等待逻辑专项 | 154 passed，0 failed | `logs/` 中本轮命令输出；新增 zero-size readiness failure 回归 |
| 最终提交 G1 | PASS，cleanup PASS；SSE 首帧 7ms、总时长 1009ms | `fix-smoke-tmp/newshub-local-domain-report-334b5d740a909681b56c41c0c7158ea39801c0dd.wMWa00/report.json`；`logs/g1-commit-334b5d74.log` |
| 最终提交 G2 | PASS，cleanup PASS；SSE 首帧 6ms、总时长 1007ms | `fix-smoke-tmp/newshub-local-domain-report-334b5d740a909681b56c41c0c7158ea39801c0dd.BFoEE2/report.json`；`logs/g2-commit-334b5d74.log` |
| 资源清理 | PASS | 无 `newshub-local-g*` 容器或 volume 残留 |

正式提交复验过程中保留两次 fail-closed 证据：首次捕获 SVG 已出现但尺寸仍为 0 的过渡帧；第一次修复又因 Playwright Python 的 `arg` 仅允许关键字传参而失败。最终实现等待标签齐全且 SVG 尺寸非零，并把 mock 签名收紧为关键字参数；工作区指纹镜像和最终提交镜像的 G1/G2 均实际通过。

### NH-30 操作员材料

已在仓库外创建权限为 `0700` 的私有证据目录：

`/home/lambert/.local/share/newshub-acceptance/334b5d740a909681b56c41c0c7158ea39801c0dd/`

其中包含：

- `NH-30-source-license.csv`：57 个来源的逐项许可台账，51 个当前技术启用来源保持 `PENDING_REVIEW`，6 个代码策略禁用来源保持 fail-closed；
- `NH-30-review-guide.md`：负责人填写、决定和技术启用步骤；
- `validate_nh30_license.py`：离线完整性校验器；初始运行按预期退出 2，未把待审来源误记为通过；
- `release-evidence.json`：绑定最终 SHA 的八项 operator gate ledger，初始全部 `NOT_RUN`。

所有文件权限为 `0600`。NH-30 负责人需要逐来源填写官方入口、访问/转载/全文/图片权利、署名、条款证据、rate budget、日期、owner 和审批决定；任何 `DISABLE` 决定必须先落实为代码 fail-closed 并回归。随后还需在另行批准的限速窗口完成真实内容质量抽样，才能分别记录 `NH-30-source-license` 和 `NH-30-content-quality`。

### 当前结论

**本地代码结论：`LOCAL_INCOMPLETE`。** 已发现的 ACC-001～ACC-007 与后续 Mermaid 门禁时序问题均已修复；固定提交 G1/G2 通过，当前无已知未修复 P0/P1 代码缺陷。原报告未实际执行的完整移动/平板/主题/慢网/Mock AI/TTS 浏览器矩阵仍不能标为 PASS。

**生产门槛：`NOT_RUN`。** NH-30 的负责人已明确，但 51 个来源尚未逐项形成许可决定，内容质量尚未真实抽样；当前主机实测为 20 CPU、约 64 GB RAM，不能作为独立 2C/4GB NH-31 证据。NH-28 正式外部授权、NH-29 异机恢复与密钥恢复、NH-31 容量/降级、G3 和生产 DNS/TLS/监控均保持 `NOT_RUN`。

## 14. NH-30 授权、有限真实同步与并发修复（2026-10-15）

本节取代第 13 节中 NH-30 尚未形成许可决定的描述。用户声明其为来源许可负责人，授权当前 51 个技术启用来源使用官方 RSS/API，并允许在项目策略、robots、请求预算、限流和正文验证允许时取得全文。用户随后要求停止全量真实运行，因此本节严格区分已执行证据和未执行范围。

### 许可台账

- 最终修复提交：`be23cb60ab74646fb550bed7d018d9b2a441186f`。
- 私有证据目录：`/home/lambert/.local/share/newshub-acceptance/be23cb60ab74646fb550bed7d018d9b2a441186f/`，目录权限 `0700`、文件权限 `0600`。
- `NH-30-source-license.csv` 共 57 行来源：51 个启用来源均填写负责人、日期、访问与展示决定、署名、请求间隔和存储范围；21 个 `APPROVED_FULLTEXT`、30 个 `APPROVED_SUMMARY`，图片二进制存储全部为 NO；6 个原代码禁用来源保持禁用。
- `validate_nh30_license.py NH-30-source-license.csv`：退出码 0，输出 `READY_FOR_OPERATOR_RECORD`。
- CSV SHA-256：`d5b7421f0248605406aabd16606ec362bebc7e986ae84d941ff662adb47bc5cd`。
- `release-evidence.json` 已把 `NH-30-source-license` 记录为 `EVIDENCE_RECORDED`。总 checker 仍退出 2，明确列出另外七项未完成门槛；操作员批准记录没有冒充出版方书面许可。

### 真实访问证据与停止点

所有访问使用固定镜像 `newshub:334b5d740a909681b56c41c0c7158ea39801c0dd`、独立 Docker volume `newshub-nh30-334b5d74-db`、独立 SQLite、无 AI/翻译/OAuth/付费模型。没有读取或修改现有业务数据库，也没有操作现有 Compose 项目。

首次执行 `manage.py crawl all` 启动 51 个 Spider 后退出码为 0，但机器可读汇总为 50 个 `deferred`、1 个 `network_error`；只抓到 262 项。这证明并发 Spider 争抢全局请求预算，且命令把未完成批次错误报告为成功。证据为旧 SHA 私有目录中的 `NH-30-full-sync-crawl.log` 和 `NH-30-crawl-all-defect.json`。

随后用逐来源串行方式运行，用户叫停时已完成 26/51 个来源：19 个 `updated`、1 个 `unchanged`、1 个 `partial`、3 个 `network_error`、2 个 `blocked`，各次 Spider 汇总合计 884 项。异常来源为：

- `devto`：主列表与多数详情已写入 202 项，3 个详情请求延迟，结果 `partial`；
- `arxiv_ai`、`github`、`ithome_energy`：本次为网络失败；
- `electrive`、`lancet`：访问策略阻止；没有绕过 robots 或站点限制。

停止后的隔离数据库实测为 998 篇 `News`、1006 条 `NewsSourceItem`、22 个已映射来源；42 篇正文状态为 `complete`，956 篇为 `missing`，326 个全文任务保持 `queued` 且未继续执行。重复 URL 为 0，重复 `(source_key, upstream_id)` 为 0。25 个未运行来源、326 个全文任务及完整人工内容质量检查保持 `NOT_RUN`，不得由上述样本推断为通过。机器可读证据为旧 SHA 私有目录中的 `NH-30-serial-sync-results.json` 和 `NH-30-isolated-db-report.json`。

### ACC-008：全量抓取并发预算饥饿且错误成功退出（P1，RESOLVED）

- 固定缺陷 SHA：`334b5d740a909681b56c41c0c7158ea39801c0dd`。
- 位置：`backend/api/management/commands/crawl.py` 的 `all` 分支。
- 触发：运行 `NEWS_CRAWL_ONLY=1 python backend/manage.py crawl all`。
- 实际：51 个 Spider 同时启动并争抢两个全局预算槽；50 个来源为 `deferred`，命令仍退出 0。
- 根因：批量入口在同一个 `CrawlerProcess` 排入所有来源，没有等待、逐源隔离、重试或聚合失败退出。
- 修复：最终提交 `be23cb60ab74646fb550bed7d018d9b2a441186f` 逐源启动隔离子进程；`deferred` 与 `network_error` 最多短暂重试两次；只接受 `updated`、`unchanged`、`valid_empty`、`not_due` 为健康终态，其他结果在全部来源处理后以非零状态退出并列出来源。持久 crawler Worker 原有逐任务串行路径保持不变。
- 回归：固定提交生产镜像内 Python 3.12 定向测试 32 passed、0 warning；日志为 `/tmp/newshub-local-acceptance-20261015/logs/crawl-all-fix-final-production-image.log`。

最终生产镜像 `newshub:be23cb60ab74646fb550bed7d018d9b2a441186f` 的 image ID 为 `sha256:185fd1b75ecfd2004108f12db723d9dd6a7c7d3b89f3dc40b5ff0bec43af334d`，revision label 与提交一致，运行用户为 `10001:10001`。该提交已普通推送到 `origin/fix/local-acceptance-findings-20261015`，未创建或合并 PR。

### 最终状态

**本地代码结论：`LOCAL_INCOMPLETE`。** 当前无已知未修复 P0/P1 代码缺陷；NH-30 来源许可台账已形成并通过完整性校验。由于用户停止真实全量访问，NH-30 内容质量、25 个剩余来源、排队全文任务以及原报告未执行的浏览器矩阵仍未完成。

**生产门槛：`NOT_RUN`。** 当前 ledger 仅 `NH-30-source-license` 有证据记录；NH-28 两项、NH-29 两项、NH-30 内容质量、NH-31 两项和 G3 均未完成。
