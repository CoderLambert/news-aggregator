# 分层验收、证据复用与上线门禁

所有产品运行仍 NOT_RUN。本文修订验收归属，不宣称引擎/浏览器/数据迁移/性能已经通过。开发专项、模块集成、真实产品验收、生产执行分别记录；缺环境只阻塞对应门禁。

## 风险与唯一主验收位置

| 门禁 | 真实风险与必须验证的结果 | 主验收位置 |
| --- | --- | --- |
| A01 引擎边界 | Miniflux 唯一常规采集、固定身份/版本、PG/API 隔离，sync 不导入模型/抓取依赖 | T00/T02/T04；组合在 T08 |
| A02 RSSHub | SSRF、DNS/跳转/凭据泄漏、真实路由配置和返回对象 | T18；仅阻塞 RSSHub 上线 |
| A03 可靠同步 | 创建成功响应丢失、kill/DB busy 重放、低 ID 晚提交、老正文更新、cleanup，cursor 不提前 | T08/T09 |
| A04 首访 | 无用户访问先采集，首访/搜索/hover 不排旧任务 | T13 组件；T27 真浏览器/调用追踪 |
| A05 内容 | XSS/危险媒体、代码表格保真、unknown 可读且不假称全文 | T06 转换；T13 渲染；T27 有限真实样本 |
| A06 写入与译文 | 复合身份、关联/读取/主写分离、CAS、退化保护、仅兼容字段译文不丢失/错配 | T05/T07；T26 副本往返 |
| A07 用户状态 | 共享 Feed 不共享个人组/读/收藏，注册和取消并发收敛，ReadingDay 保持 | T08/T13/T19 |
| A08 权限 | A/B/匿名直接 ID/搜索/AI/TTS/计数/缓存；退订撤权；public/personal 停更不变 | T11/T14 参数化访问矩阵；T27 端到端 |
| A09 元数据和频道 | 同 HTML 仍处理元数据；非主写不覆写；摘要本地派生；旧/新成员筛选一致 | T09，引用 T07 译文保护 |
| A10 发现/OPML | 目录/URL/模板、选择/组归属、token/幂等、部分失败、本人导出 | T16/T17/T19/T20/T21 |
| A11 AI 保留 | 本地授权上下文、未收录只摘要链接、联网搜索保留、旧异步结果不能发布为新版本 | T14；T27 真实用户流 |
| A12 回滚恢复 | 两库配对、实例/schema/映射、完整 fence、兼容镜像读 available/ACL、新数据保留 | T03 工具；T26 组合演练后封存 |
| A13 切源 | 共享 Feed 最小组无双采集、旧任务和其他 legacy source 晚写拒绝、覆盖差异明确 | T24/T25；T29 逐源结果 |
| A14 删除 | 旧进程/宿主定时/代码/依赖退出，升级/重启不复活，通用安全和索引保留 | T30/T31；T33 最终镜像 |
| A15 最终质量/资源 | 同机同窗口，计入 Miniflux+PG+sync+可选 RSSHub，失败来源不移出分母 | T27 来源质量；T33 最终资源 |
| A16 发布 | 验证版本与获批目标一致，CI/角色/备份/兼容版本明确 | T33 发布阶段 |

硬门槛：测试中的错误文章覆盖、跨用户泄漏/政策绕过、代码文本误改、旧数据丢失均为零；经确认原生全文样本完整保留。人工完整性只抽架构约定的每类约 5–10 篇，不要求每篇生产文章人工 verified，也不新增审核平台。

普通准入文章 90% 完整正文、目录 p95≤500ms、正常无积压引擎落库到可见 p95≤60s 是待测产品目标。报告固定分母/硬件/规模、p50/p95/最大值和失败原因；未达目标由上线评审决定范围/整改，不能伪造 PASS，也不阻塞纯转换/数据库模块验收。

## B0 文档检查

按 [VALIDATION.md](VALIDATION.md) 校验原架构 hash、26 有效任务和 11 合并索引、任务/表/DAG 一致且无环、链接/C01–C11、纯文档范围和 whitespace。这是规划质量证据，不是产品运行证明。

## B1 任务专项

每项只测自身风险。T06 保留恶意输入/代码保真/确定性/大小/无网络，不套用重启、跨用户、上游故障或生产批准反例。数据库任务使用临时合成库；UI 使用契约 fixture；fake adapter 证明逻辑，不能称实际引擎通过。

T00/T02/T04/T08/T09 的真实引擎/容器集成仍是其相应完成条件。没有真实环境时可完成实现，运行门禁保持 BLOCKED；只依赖接口的其他开发可以继续。关键身份/ACL/迁移/恢复需独立复核，普通小任务按常规实现评审，不强制另起 Agent 和统一冗长报告。

## B2/B3 全量组合

以下为代码基线现有命令；T31 删除 crawler 后须同步 PYTHONPATH/测试根等价覆盖。完整回归在产品集成和最终运行组成改变时执行，不在每个无关 PR 重跑。

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

CI 的 synthetic manage.py check --deploy、non-root 镜像和隔离域名烟测保留；不能用活动/生产配置。新增 tests/rss_engine_contract/ 的 live 测试使用明确隔离目标 allowlist。scripts/run_tests.sh 缺多个测试根，不能代替全量。

T26 迁移、兼容回滚和两库恢复在同次演练产生证据，再封存镜像；不另设封存任务重复演练。T27 复用这些证据并跑真实来源/浏览器。每源切换只新增该源 owner/映射/覆盖/数据证据，不每源重跑公共权限与完整 restore。T33 在删旧栈后的最终镜像重验恢复/重启和关键用户流，因为运行组成确实改变。

## 证据有效性与阻塞范围

必要记录：测试场景、命令/退出码、环境/配置、受测 SHA/digest、结果/失败和相关工件链接。涉及真实来源/恢复时另记对象身份（脱敏）、时间、恢复点/RPO。常规纯函数测试不要求备份 ID、生产批准或每条断言数量。

同 SHA/配置/相关代码不变时可以复用证据；相关代码、权限、schema、运行角色或依赖版本变化后重跑受影响部分。不能用截图/HTTP200 证明权限/全文完整。未知分支保护不等于无要求，遵守 GitHub 实际必需检查。

当前：引擎/网关实际条件未验证；生产副本未知；产品/浏览器/恢复/资源未运行；生产执行未授权。分别标对应运行门禁 NOT_RUN/BLOCKED，而非要求所有开发同时等待。RSSHub DNS/Token 阻塞 T18 上线；数据副本阻塞 T24 真实盘点和 T26；生产批准阻塞 T29/T30/T33 的实际执行，不阻塞 SDK/模型/目录/转换实现。
