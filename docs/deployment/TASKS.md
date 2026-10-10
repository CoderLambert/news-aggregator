# 任务追踪

基线 HEAD：8c2823e1fcf8cbea38e9bb7c4e98a33232025fbd。每项实施前另附完整固定字段契约；当前仅 P00 冻结，其他任务不可凭表自行猜测实施。

| ID / 历史关联 | 依赖 | 文件 / 实现 | 验收命令/门槛 | 状态 | HEAD / 审核 |
| --- | --- | --- | --- | --- | --- |
| P00 | 无 | ARCHITECTURE/TASKS/PROGRESS；真实路径与 route matrix | fetch/status/角色发现/部署与服务盘点 | TESTED | 基线；主 Agent 只读预检 |
| NH-PUB-01 | P00 | scripts/deploy/preflight.sh、news-lambert-host.md；只读报告 | bash -n、离线 mock 缺命令/失败/成功，不误报 PASS | TESTED | 基线；未审核 |
| NH-PUB-03 | P00 | settings/start_waitress/health/.env.production.example/测试；严格 env 与可信代理 | 定向 pytest/check --deploy/Host/代理/cookie/探针 | TESTED | 基线；未审核 |
| NH-PUB-05 G1 | 03 | 服务端模式中间件/capabilities/views/urls/测试；逐路由拒绝 | 全 route/method 矩阵、Provider 0 次、内部 Worker | TESTED | 基线；未审核 |
| S05-FRONTEND | P00/03 | Mermaid/Markdown/DOMPurify与负例 | 3文件7测试、typecheck、lint退出0；High待G1 | TESTED | 7bef7fb候选；未审核 |
| S05-BACKEND | P00/03 | article_fetcher安全输送/各provider/比较验证器 | 106测试PASS；DNS/每跳/全deadline/wire/GET；High待G1 | TESTED | 7bef7fb候选；未审核 |
| NH-PUB-04 | 03 | Dockerfile/compose.prod/entrypoint/持久路径 | 阶段A54+8PASS；B镜像/健康/重建持久性/权限待验 | DOING | 基线；未审核 |
| NH-PUB-02 | 03、04 | deploy/nginx/模板与隔离验证 | 阶段A离线4项PASS；真实nginx/TLS/browser阶段B待验 | DOING | 5c0e46b候选；未审核 |
| NH-PUB-10 | 05 | services/api/AuthContext/页面/index/测试 | 31定向+421全量PASS、typecheck/lint/build0；High待G1 | TESTED | 基线；未审核 |
| NH-PUB-11/12 | G1 前项 | CI/部署回滚备份恢复/release-gates | 后端432PASS；release16PASS/shell0/收集452；真实Docker/恢复/High待验 | TESTED | 7f1148d候选；未审核 |
| S01/P01/G2 | G1 本地门槛 | Chat 归属迁移/事务/账户 CSRF 限速/前端缓存 | A/B/匿名/并发/历史隔离/登录重放/High | TODO | 基线；未审核 |
| NH-PUB-06/S02/S04/O01/O02/O03/G3 | G2 | Provider 合规路由/预算/持久任务/SSE | Fake Provider 原子配额/幂等/取消/恢复/隔离/High | TODO | 基线；未审核 |
| NH-PUB-07 | P00 | openai-hosted-integration.md；身份/plan 批准分离 | 申请材料完整；真实审批 EXTERNAL_BLOCKED | TODO | 基线；未审核 |
| NH-PUB-08 | G2、模式 ADR | subscription service/views/models/前端/tests | 离线模式/快照/重放/nonce/aud/iss/cookie/High | TODO | 基线；未审核 |
| NH-PUB-09/G4 | 07真实批准/08协议/G2/G3 | 获批 user plan Provider（未授权禁止派发） | 2获准账号真实 OAuth/撤销/缓存费用隔离 | EXTERNAL_BLOCKED | 无正式批准 |
| 公网 DNS/TLS/服务器发布 | G1、额外授权 | 仅现场变更单，禁止自动执行 | 真机证书/DNS/端到端验证 | EXTERNAL_BLOCKED | 未获写授权 |

历史 ID 去重：S01→G2；S02/S04/O01/O02/O03→06；S05→内容安全；P01→G2。S03→03/G2，O04→04（reference-plan明确关联）；O05/O06/P02/P03 因本地参考未提供原定义保持 NOT_RUN，不宣称被前项覆盖。密码重置因邮件策略未定为 BLOCKED，待 G2明确；不妨碍其他本地任务。

| 本地域名/HTTPS G1/G2/G3追加 | 02/04/05/10，G2追加账户，G3追加任务 | 隔离DNS alias/CA/Nginx/browser验收脚本与说明 | 正式域名HTTPS不跳过证书、深链/权限/SSE/CSRF/Cookie/登录/A-B/任务；实际运行NOT_RUN | DOING | ADR011；阶段A完成，未审核 |
