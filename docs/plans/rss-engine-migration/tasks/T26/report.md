# T26 合成迁移/恢复候选报告

状态：**SYNTHETIC_CANDIDATE_NOT_SEALED**。候选工具及以下隔离合成实测可交付；T26 的真实授权副本演练、生产兼容 seal、完整部署回滚链未完成。没有生产操作、用户数据库读取、反向 migration、真实 AI/provider 请求或镜像 registry 发布。

## 实际代码与镜像

当前应用代码为 `32a340a0e0535543a52321488a899b8c313f23f9`，包含 T09、T25、T14 和0059；兼容应用为 `3035c6bb4fd2dc15a3b40f61a7e9432211d93e60`，包含旧/新写 fence、available/ACL、精确 hash 译文读取及相同0059 schema。两者均保留完整应用 AI/crawler 包和已有前端产物，实际运行 WSGI 路由；不是只安装 ORM 的轻量 RSS 镜像。

- 当前镜像：`sha256:b0104a5800dc6537d9f04ad86bf7c9ad0bfc9e9462072ec5e20fd06b0e5fd680`。
- 兼容镜像：`sha256:202474a1e685a29684c070e78c6a4d065970d78153349a02d791c3ad220ab26d`。
- Full app 缓存基底：`sha256:d593f000671099a3bdcede08379c2e2ce5738f14a4586632d173a7d4ebc0894b`。
- RSS 锁依赖基底：`sha256:3ae4135b142cecc266e2b0407aea46604315a69fff85e2517f139c930b2cf4b9`。
- 另从只读显式 `--dependency-site` 复制已锁定 `listparser==0.20`、`defusedxml==0.7.1`，核对 METADATA 与 requirements pin，没有修改根 venv。

完整镜像标签、digest、来源和 harness hash 在 `ops/rss/T26/evidence/candidate.json`。缓存 frontend/dependency 层不是从最终发布 Dockerfile 重建的精确 release，基底未声称具备当前应用 revision；应用 backend/crawler 由上述 SHA 覆盖。实际 app 容器使用 UID1000 的隔离写目录；生产 UID10001 启动/部署权限由尚未完成的完整回滚链承担。任务工具提交 SHA 与受测应用 SHA 分开，不能用后续文档/工具提交替换被测镜像身份。

## 实测结果

| 合同 | 实际结果 | 证据边界 |
| --- | --- | --- |
| T26-A1 | PASS，历史0051 ORM→完整0059；56张旧表旧列聚合完全相同，其中34张非空；FK/integrity均通过 | 合成数据，非用户副本 |
| 关系保留 | 原 News/Source/Category、publisher item、用户/订阅/分组/NewsPreference、收藏/屏蔽/ReadingDay、Chat/Research、私人/共享译文及任务、智能分组配置/覆盖/提案、intake、合成凭据/OAuth selection、FeedState 均含非空样本 | 新 NewsReadState 缺记录仍未读，不由 ReadingDay 推断 |
| 旧译文 |0059保留 title/content/full_content 唯一兼容字段副本，逐字段精确源文本/hash匹配；原行及原文字节不变 | 一时点 stopped-writer legacy 绑定，不虚构 provider/connection |
| T26-A2 | PASS，2来源共享组必须完整选择；miniflux→legacy→miniflux后 epoch7/body_owner_version4；旧 ingest 和全文 worker 拒写；旧标题译文仅归档历史 | 切换政策 receipt 为明确合成适配器，不声称这里调用真实引擎 |
| T26-A3 应用代码兼容 | PASS，当前→兼容→当前镜像读同一 DB；available revision18、unknown completeness、public body、个人 paused A/B/匿名 ACL、已读、旧 hash 译文不当前均正确 | 各镜像实际 WSGI HTTP detail200/个人404；已授权 DRF 订阅/OPML/已读读取也验证 |
| 控制数据兼容 | 当前应用实际订阅 POST、OPML preview/confirm/process durable intents；兼容镜像可读导入进度、导出本人订阅、本人已读；B读A import404 | network none，仅固定 synthetic instance/account，无外部 collector/provider 调用；不是跨版本完成引擎注册的证明 |
| T26-A3 完整部署链 | **BLOCKED，未执行** `recovery.py rollback → rollback.sh` | 不能用镜像往返 PASS 代替脚本、静态 current、生产 UID/readiness 全链证明 |
| T26-A4 | PASS，真实 Miniflux2.3.3/PG17.6 对上述完整升级数据执行 T03 成对备份/恢复；live app、错误实例拒绝；两个逻辑库/hash/FK/全部样本关系恢复一致；恢复后的完整 app ACL 正确 | 原始 miniflux identity 对齐是备份前显式 synthetic fixture 设置，不是生产重绑定工具 |
| 恢复后真实同步 | PASS，实际 T09 增量及全量 reconcile 完成，cursor4，增加本地文章，个人 paused 范围保持 | 本地 HTTPS publisher、合成 collector；没有公网/生产来源质量结论 |
| T03最终schema补验 | PASS，现成 T03 harness 在0059上运行 overwrite/replay/fresh restore，篡改pair/hash/schema/instance/prior及活动writer均拒绝 | 复用同一 recovery 工具，无第二套备份恢复实现 |
| 失败清理 |5专项 PASS，包括真实容器timeout、失败退出及路径拒绝 | 精确 name+label/ID 清理，不能广泛删除前缀匹配资源 |

应用往返没有 migrate/restore 调用，所有表指纹始终为 `aae24a08604fa559cc60e249e4351340485717bbd5a219c7708c76f739d084c3`。灾难恢复是另一套单独目标：先复制完整 synthetic 数据，配对备份后分别提交 SQLite/PG 后续修改，再明确恢复到记录的两个 UTC restore points；后续修改的丢失就是该恢复点的 RPO，不隐藏在普通应用回滚中。恢复比较后才重新启动引擎、执行授权的 T09 对账，因此其合法新数据写入单独记录。

## 命令与工件

实际使用 Python3.12 完整 app 镜像与只读 `/tmp/newshub-rss-coordinator-venv`，全部 DB 路径显式隔离。以下命令退出码均为0，预期的负向门禁另在证据内标明。

```sh
python ops/rss/T26/run.py --output /tmp/newshub-rss-t26-complete \
  --rollback-candidate newshub-rss-t26:candidate-3035c6bb4fd2
python ops/rss/T26/paired.py --dataset /tmp/newshub-rss-t26-complete \
  --output /tmp/newshub-rss-t26-complete-paired.json
python ops/rss/T03/verify_isolated.py \
  --python /tmp/newshub-rss-coordinator-venv/bin/python \
  --output /tmp/newshub-rss-t26-paired-0059.json
python ops/rss/T26/rollback_preflight.py \
  --output /tmp/newshub-rss-t26-rollback-preflight.json
RSS_TEST_ALLOW_LIVE=1 RUN_MAIN=true \
  DJANGO_DB_PATH=/tmp/newshub-rss-t26-tests.sqlite3 PYTHONPATH=backend:crawler \
  /tmp/newshub-rss-coordinator-venv/bin/python -m pytest -q \
  tests/rss_engine_contract/test_migration_rehearsal.py
```

持久 evidence 仅保存合成汇总、hash、image identity、完整 applied migration 清单和受控路径。原合成 SQLite 留于 `/tmp/newshub-rss-t26-complete` 供审查；配对恢复目标/备份/secrets/容器/网络/卷均 finally 清理，不入仓库。候选镜像本地保留，无 registry push。`README.md` 给出显式缓存/依赖参数和可复现步骤。

## 未验证及具体阻塞

1. 用户尚未提供授权真实业务备份副本：实际来源数量、FK分布、库规模、恢复耗时/RPO预算、真实来源兼容尚未验证；**不能 sealed，也不能把 T26 总体验收标 DONE**。
2. 完整部署脚本链：host UID1000不能遍历 `/var/lib/docker/volumes/<唯一T26卷>/_data`。实际 T03 `sqlite_target()` 拒绝不可访问父路径；唯一 helper 挂该卷后，真实 Docker volume filter 列出它，现有停写检查应拒绝。没有绕过 quiesce、挂父目录躲检查、更改宿主 ACL、使用 sudo/nsenter。9527预检为空闲但未启动完整生产 app。最小下一条件是可直接访问明确卷 Source 的授权 host runner；再执行原脚本并验证静态 current/readiness/所有 collector 停止。
3. 回滚 env_file 必须保留与 manifest一致的 RSS_ENGINE_INSTANCE_UUID/ACCOUNT_ID。collector 停止和缺 heartbeat 的unknown健康可符合failclosed，不能替代身份配置。
4. 未运行生产构建/真实 secret挂载/浏览器/真实AI provider；未重复整仓测试。当前候选不包含其后集成的UI/health/分类ACL补丁，后续发布不能把这些变化自动纳入本候选证明。
5. HTTP正文公网站点重定向/DNS/出口网关隔离门禁属于既有 T00 部署风险，本演练私有 HTTPS fixture 不能解决它。

独立审查由主调度执行；工具失败清理、依赖来源/版本、完整wrapper链边界已经按其意见修正。T14临时边界修复单独提交 `15f1bdc`，不与本T26工具提交混合。
