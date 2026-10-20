# RSS 自助添加、公开审核与审核员权限本地验收

已安装本地版本，未部署生产。普通用户添加 RSS 后自动安全连接，无需人工审核；仅推荐到公共目录时需要独立审核员审批。超级管理员可直接新增公共频道，也可按准确用户名授予或撤销独立的频道审核权限。

入口：

- [个人添加记录](http://127.0.0.1:18080/channels/additions)，频道管理 → 添加频道。
- [公开频道审核](http://127.0.0.1:18080/admin/rss/recommendations)。
- [频道审核员](http://127.0.0.1:18080/admin/rss/reviewers)，仅超级管理员可授权。
- [频道核验](http://127.0.0.1:18080/admin/rss/channels)，审核员可核验，超级管理员另有新增公共频道入口。

## 候选身份与范围

代码保留在独立工作区 `/home/lambert/githubRepos/lambert/news-aggregator-channel-recovery-20261021`，分支 `task/channel-recovery-20261021`。HEAD `887194ab1ad4bd2421e824045f5885a90622b73d`，产品基线 `b03a3dfb41911b06dfb24c31074f4faf60fe8845`；产品实现仍为 dirty，不能用 HEAD 单独代表交付内容。上一轮恢复链路改动也在本候选中保留。

实际代码/测试文件摘要见 [candidate.json](rss-self-service-review-20261021/candidate.json)。本地 app 与 rss-sync 同为镜像 `newshub:rss-self-service-66246c23b204`，image ID `sha256:0bdbb6b23cd63cf9238c87aeb37cd97275952347a88b0010cf54cb0f4591f2a7`，运行源码及静态资源摘要 `66246c23b2045ce5e2680f5124d7650775d54d999e57803e8dd725ec11849d86`；[逐文件清单](rss-self-service-review-20261021/runtime-manifest.json)与容器内文件逐项匹配。

范围包含：迁移0077、审核授权/事件/候选/公共成员模型；个人添加与推荐服务/API；审核和核验共用恢复服务；Worker 权限和版本围栏、公开成员首次填充及调度；所有既有存储阅读消费者的成员 ACL、分类投影；独立添加/审核/授权页面和原频道核验页集成。沿用同域 Session/CSRF API，无新增账号体系、队列或付费服务。

## 实际验证

| 验证层 | 结果 | 证据 |
| --- | --- | --- |
| 后端相关全门禁 | PASS，705 tests，109.84秒 | [日志](rss-self-service-review-20261021/backend-final-green.log) |
| 前端全测试 | PASS，105 files / 721 tests | [日志](rss-self-service-review-20261021/frontend-final-review.log) |
| TypeScript / lint / build | PASS；lint 0 error，既有 useSuggestedQuestions 警告1项 | [类型](rss-self-service-review-20261021/typecheck-final-review.log)、[lint](rss-self-service-review-20261021/lint-final-review.log)、[build](rss-self-service-review-20261021/build-final-review.log) |
| 真实隔离引擎 | PASS，Miniflux 2.3.3；个人→推荐→审核→公共；共享目标只有一个物理 Feed；解析失败真实返回 | [结果](rss-self-service-review-20261021/isolated-engine-results.json)、[日志](rss-self-service-review-20261021/live-final.log) |
| 三角色浏览器 | PASS，普通用户自助添加/真实失败/已有文章反馈；审核员核验/批次完成/倒计时；管理员精确查找/新增实际连接 | [记录](rss-self-service-review-20261021/browser-results.json) |
| 手机与键盘 | PASS，412×892 CSS px，无横向溢出；详情全屏；Escape 后恢复打开按钮焦点 | [截图](rss-self-service-review-20261021/review-mobile-412.png) |
| 本地安装与保留 | PASS，备份完整性、迁移、同版本 app/Worker、HTTP200 | [备份](rss-self-service-review-20261021/local-backup.log)、[安装](rss-self-service-review-20261021/local-install.log)、[保留检查](rss-self-service-review-20261021/local-preservation.log) |
| CI / 生产 | NOT_RUN，无推送、无 PR、无生产部署 | 本地证据不代表 CI 或生产验收 |
| 整个后端仓库测试 | NOT_RUN；本轮运行下列语义相关门禁 | 不将相关门禁称为全仓后端通过 |
| 浏览器限额压力操作、授权提交 | NOT_RUN；限额、授权/撤权/重授和迟到响应由后端回归覆盖 | 没有给真实账号授予审核员权限 |
| 首次 live 集成 RED | NOT_RUN；首次真实引擎运行已通过 | 上线前的 RED 证据来自离线测试，不冒称 live RED |

后端命令在无网络、Python3.12、临时 SQLite 的 Docker 环境运行：

```sh
sh .superpowers/sdd/2026-10-21-rss-self-service-and-review/pytest.sh \
  backend/api/tests/rss backend/api/tests/test_channels.py \
  backend/api/tests/test_smart_channel_workspace.py backend/api/tests/test_tts_endpoint.py \
  scripts/deploy/tests/test_rss_channel_recovery.py
```

前端使用 Node22.23.3，执行 `npm --prefix frontend run test:run`、`typecheck`、`lint`、`build`。实际引擎脚本为 `tests/rss_engine_contract/live_self_service_review.py`，必须显式 `RSS_REVIEW_LIVE=synthetic-isolated` 并验证合成目录标记。专用项目 `newshub-self-service-lab-20261021`，浏览器合成域名 `rss-review.localhost:18084`，未登出或改写用户原127.0.0.1会话。最终界面另行新增了第二个合成空 Feed 验证管理员入口，不改变共享目标只创建一次的证明。

最终迁移模型检查 `makemigrations api --check --dry-run`：PASS，无模型漂移。app 与 rss-sync 均 healthy、重启计数0。[检查日志](rss-self-service-review-20261021/schema-check.log)。合成项目已清理，本地 UAT 服务保留；截图和结果不依赖测试服务继续运行。

## 独立审查与修复

一轮独立只读全候选审查完成，随后一轮实现修复，未派发重复审查。

- 修复当前 DTO 为空摘要时误用旧私人摘要作为公开证据：证据改为当前经过清洗的 DTO 摘要 hash，保留旧字节却不给它新的公共授权。
- 修复审核员打开核验页空白；页面和缓存均绑定当前授权版本，新增公共频道仍限超级管理员。
- 修复最旧阻塞审批卡住后续发布：有界轮转；首次公共成员填充也轮转，并在数据库跳过已知超出七天范围或日期推断的历史条目。
- 审核分类通过公共成员投影参与筛选，不重写私人文章分类；新文章采用已审核分类。
- 增加 owner 范围内的文章数量/就绪状态，分别显示等待同步、已有可读文章和同步后空结果。
- “初次填充策略错误导致 Worker 崩溃”不成立：OperationError 继承 ValueError，已有处理捕获它。新增实际策略收紧负例确认不授权且不崩溃。

[后端审查 RED](rss-self-service-review-20261021/review-red.log) 4 fail/9 pass、[界面 RED](rss-self-service-review-20261021/review-ui-red.log) 1 fail/7 pass；[就绪状态后端 RED](rss-self-service-review-20261021/readiness-red.log)、[界面 RED](rss-self-service-review-20261021/readiness-ui-red.log) 均先观察失败。首次筛选修复暴露 JSON 缺失路径的 SQL NULL 行为，改为明确允许 missing 或 false，最终705/721门禁通过。策略异常和轮转额外回归通过；没有伪造未运行的 RED。

## 本地来源与数据保留

安装前在线一致性备份保存在应用数据卷的 `private-backups/rss-self-service-before-0077.sqlite3`，完整性 `ok`，未将真实数据库复制入测试。迁移0077后再启动同版本 app/Worker；本轮没有重启 Miniflux。

原4个账号、7条订阅、50篇文章、10个来源逐行核对相同，包含原正文及翻译；10个绑定的实例/账号/Feed ID/URL/策略和首次采集下界核对相同。未创建真实审核员授权。当前核验列表10个通过、0个待处理；这是已保存技术核验状态与迁移后保留检查，不是本轮重新抓取所有发布者。

上一轮真实恢复结果继续保留：美团 Feed9、WebKit Feed10、Martin Fowler Feed11 均已连接可订阅；其余七个 Feed 保留。完整旧请求边界、重启和逐来源证据见 [频道恢复验收](channel-recovery-2026-10-21.md)。

## 实施判断与代价

1. 延后重叠产品改动提交，保留原有 dirty 工作；代价是后续 Git 集成仍需精确划定提交范围。
2. 重试测试让合成失败记录超过60秒，不放宽真实冷却；代价是测试必须区分冷却与恢复路径。
3. 修改推荐 URL 时撤回本人的旧提交并建立新目标，不改其他人的共享候选；代价是候选 ID 会改变。
4. 旧私人来源正文对公共读者保持仅摘要，直到存在独立公共来源证据；代价是部分公共文章初期只有摘要。
5. Worker 明确传递当前实例/账号，以数字 engine_entry_id 作每 Feed 游标；代价是游标语义必须保持一致。
6. 将文章就绪反馈由 Minor 升为 Important，避免用户无法判断连接后能否阅读；代价是两项 DTO 字段及每行有界的计数查询。
7. 拒绝“OperationError 未捕获”的审查判断并以策略变更负例验证；判断错误的代价是 Worker 可用性风险，因此保留回归。
8. 保留隔离分支、未提交实现和执行台账，不自动删除；代价是后续仍需范围明确的 Git 集成。没有延期的小问题。

## 回退及短验收

发生问题先停止当前 rss-sync，暂停恢复/公开审核入口并将 app 和 Worker 一起切回 `newshub:channel-recovery-9e56c9c255ae`。保留0077和新增审计/候选/成员数据，不反向迁移或清除错误/尝试数；旧代码不会展示新候选。若需数据恢复，必须单独安排停写并确认备份之后的新增数据处理，不自动覆盖数据库。

建议人工仅按三项记录版本+PASS/FAIL/未测：个人添加后能阅读并看见失败原因；审核员能审核且不能授权他人；管理员能新增公共频道、授权/撤销指定用户名。审核员授权由管理员选择真实账号后在页面提交，本轮没有代替选择。
