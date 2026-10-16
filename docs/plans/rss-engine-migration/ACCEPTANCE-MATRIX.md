# 验收层级、真实运行门禁与证据矩阵

所有产品验收目前NOT_RUN。真实引擎/网关、授权数据副本、浏览器、生产操作条件未建立，因此相关门禁BLOCKED；静态审计不等于运行PASS。此规划PR仅执行文档一致性校验和独立审核。

## 目标追踪

| 门禁 | 场景及硬预期 | 所有者 | 必要实际证据 |
| --- | --- | --- | --- |
| A01 | Miniflux唯一采集，PG隔离、官方SDK、固定版本 | T00/T02/T04/T35 | 引擎/API契约、网络访问、digest |
| A02 | RSSHub仅已有批准路由、网关私网防护/凭据隔离 | T01/T18 | 公网回流、TLS、DNS、IPv4/v6、redirect、真实Trending；缺Token阻塞 |
| A03 | 增量和对账、崩溃/晚提交/cleanup/超时恢复 | T08/T09/T10 | kill/丢响应/DB busy/重启，复合身份与cursor证据 |
| A04 | 首访只读已有内容，后台预获取 | T13/T14/T27 | 无用户访问先采集，浏览器首访网络/后端调用追踪无旧fetch |
| A05 | HTML安全、代码表格图片、可读性≠完整性 | T06/T07/T13 | 恶意夹具、代码复制比对、截图、逐篇完整性审核 |
| A06 | 不退化、不覆写、历史译文/用户数据保持 | T05/T07/T26 | 同hash/no-op、CAS、降级隔离、全部FK/hash前后对比 |
| A07 | 两用户共享Feed且个人状态隔离 | T08/T11/T12/T19 | 并发20次注册、A退订B有效、组/收藏/已读/ReadingDay |
| A08 | 个人源无首页/直接ID/搜索/AI/统计/缓存泄漏 | T11/T14/T21/T27 | A/B/匿名端到端拒绝、向量二次授权、退订撤权 |
| A09 | 关键词、URL发现、参数、预览和直接订阅 | T15–T20 | 固定种子、0/1/多候选、真实状态、键盘/移动端、无采集预览 |
| A10 | OPML预览确认/部分失败/本人导出 | T21/T22 | 真上传/确认/刷新恢复，恶意XML/限额/多组roundtrip |
| A11 | AI阅读体验保留、研究能力差异明确 | T14/T27 | 翻译/问答/研究/TTS均授权本地上下文，无旧Provider；未收录给摘要链接 |
| A12 | 两库备份恢复/兼容回滚/实例重绑定安全 | T03/T36/T26 | 隔离真实dump/restore、manifest/schema/身份校验、失败关闭 |
| A13 | 来源覆盖与按源单owner迁移 | T24–T29 | 每实际source_id独立差异、批准、执行、验收工单 |
| A14 | 旧进程/代码/依赖/重启入口全部退出 | T30–T32 | 宿主进程/cron/systemd、镜像依赖、import/运行扫描、重启 |
| A15 | 单栈质量/性能/资源与完整回归 | T27/T33 | 同机同窗口native+PG+sync+RSSHub合计；失败清单不移出分母 |
| A16 | 发布合规与完成定义 | T34/主控 | 特定生产批准、必需CI/保护、独立审核、SHA/PR/证据齐全 |

硬门槛：错误覆盖、串用户/来源政策绕过、旧数据丢失、代码文本误改均0；已确认原生全文样本完整保留。性能候选：目录p95≤500ms、正常无积压引擎持久化→NewsHub可见p95≤60s；T00锁定样本数/硬件/数据规模并报p50/p95/最大值，初次大批量与源站发布时间另记。普通准入文章90%完整正文是待规划审核的首批产品目标，不能承诺所有来源；未达目标列BLOCKED/差异等待用户决策，不能悄悄降级为PASS。

## B0：本轮规划验证

- 固定基线、原文一致、所有变更只在本目录。
- 所有37节点都有task/tests/report、前置存在、图无环、目标合同链接有效。
- 所有测试入口标现有或PLANNED，不将不存在测试说成已通过。
- 原文路径/共享模式/研究能力/已读差异由独立ADR说明；所有实际环境缺口显式BLOCKED。
- 独立规划审核，修复P0/P1，文档PR及CI可追踪。结果见PLANNING-REPORT.md。

## B1：任务级

每项tests.md列出计划新增的测试文件和命令；执行时先确认测试文件存在，按任务范围跑专项、type/lint、API/DB契约及必须实际运行。任何必需条件缺失不能通过skip制造PASS。每个PR满足GitHub实际要求，API403不能推断无必需检查。

## B2/B3：批次级全量

下面是当前基线CI的现有命令；最终删除crawler后T32必须同步PYTHONPATH/测试根的等价覆盖，不能直接删掉测试门禁。

```bash
RUN_MAIN=true PYTHONPATH=backend:crawler backend/venv/bin/python -m pytest --collect-only -q tests/ backend/api/tests/ scripts/deploy/tests/
RUN_MAIN=true PYTHONPATH=backend:crawler backend/venv/bin/python -m pytest -q tests/ backend/api/tests/ scripts/deploy/tests/
(cd frontend && npm ci && npm run typecheck && npm run lint && npm run test:run && npm run build)
bash -n scripts/deploy/smoke.sh scripts/deploy/deploy.sh scripts/deploy/rollback.sh scripts/deploy/backup.sh scripts/deploy/restore.sh scripts/deploy/tests/test_release_scripts.sh
bash scripts/deploy/tests/test_release_scripts.sh
bash scripts/deploy/tests/test_export_static.sh
bash scripts/deploy/tests/test_preflight.sh
bash scripts/deploy/tests/test_local_domain_args.sh
```

CI另外执行synthetic production `manage.py check --deploy`、non-root镜像build及隔离local-domain-smoke。完整参数/镜像/证书/临时卷以已审CI和T32为准；禁止把生产环境变量用于这些测试。现有G1烟测不等于未实现的G3引擎验收，scripts/run_tests.sh缺失多个测试根不能替代以上全量。

B2/B3还须运行后续交付的 `tests/rss_engine_contract/`（rss_live marker、明确隔离allowlist）、RSS浏览器流、双库备份恢复、真实来源抽样；只有专项和mock不够。B3在最终不含旧栈的镜像上再实测资源、重启和所有端到端路径。

## 证据要求与阻塞

每份报告必须包含任务/用例ID、时间、执行人/独立审核Agent、环境/负载与配置hash、版本/digest、输入来源/对象身份（脱敏）、测试命令及退出码、原始工件hash、基线/目标/修复/合并SHA、CI链接、失败/遗留/回滚。截图仅证明界面，HTTP200仅证明响应，不能单独证明来源质量/权限/完整性。

当前BLOCKED清单：T00缺隔离引擎实际验证；T01缺批准的公网网关/DNS/证书/回流和Token；T24缺授权一致性数据副本及实际source_id/状态；T26/T27缺受测系统；T28及以后缺特定生产授权；分支保护API403尚无法确认。规划PR可以提交，产品门禁不得因此改PASS。
