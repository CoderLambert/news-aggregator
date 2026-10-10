# 任务追踪

基线 HEAD：8c2823e1fcf8cbea38e9bb7c4e98a33232025fbd。每项实施前另附完整固定字段契约；当前仅 P00 冻结，其他任务不可凭表自行猜测实施。

| ID / 历史关联 | 依赖 | 文件 / 实现 | 验收命令/门槛 | 状态 | HEAD / 审核 |
| --- | --- | --- | --- | --- | --- |
| P00 | 无 | ARCHITECTURE/TASKS/PROGRESS；真实路径与 route matrix | fetch/status/角色发现/部署与服务盘点 | TESTED | 基线；主 Agent 只读预检 |
| NH-PUB-01 | P00 | scripts/deploy/preflight.sh、news-lambert-host.md；只读报告 | bash -n、离线 mock 缺命令/失败/成功，不误报 PASS | TESTED | 基线；未审核 |
| NH-PUB-03 | P00 | 严格生产env/可信代理/健康/Host-cookie | check --deploy/权限回归及真实HTTPS非豁免CSRF路径 | REVIEWED | 91dc86b G1；High闭环，公网未执行 |
| NH-PUB-05 G1 | 03 | 逐route/method服务端read_only/capabilities | 离线Provider0次与实际匿名只读/private拒绝 | REVIEWED | 91dc86b G1；High闭环 |
| S05-FRONTEND | P00/03 | Mermaid严格清洗与可信静态CSS/Markdown | R3真实组件与正式域名截图人工检视可读；危险SVG负例 | REVIEWED | 91dc86b G1；High闭环 |
| S05-BACKEND | P00/03 | SafeHTTP固定DNS/peer/TLS/每跳/绝对限额 | 106安全定向及后端回归；production无Jina/subprocess | REVIEWED | 91dc86b G1；High闭环 |
| NH-PUB-04 | 03 | production镜像/限权持久路径 | 实际build0；UID10001/健康/六卷写入/重建保留/manifest | REVIEWED | 91dc86b最终镜像，04B app相同1288c证据；未上线 |
| NH-PUB-02 | 03、04 | 专属vhosts/真实Host guard/共存与TLS | standalone/coexist nginx-t0、Git/news分流、绝对URI恶意Host拒绝、browser CA/SAN/HTTPS/SSE | REVIEWED | 91dc86b本地域名PASS；真实服务器未操作 |
| NH-PUB-10 | 05 | 生产相对API/能力展示/身份缓存/SEO | G1前端436全量及正式域名只读UX/深链通过 | REVIEWED | 91dc86b G1；后续G2身份变更另审核 |
| NH-PUB-11/12 | G1 前项 | CI/deploy/rollback/backup/restore | 正式镜像+domain PASS；真实backup/restore12checks含latest prior/tamper/runningmount拒绝/cleanup PASS | REVIEWED | 91dc86b G1；High增量闭环，外网/真机未验 |
| S01/P01/G2 | G1本地已通过 | Chat隔离/归档、CSRF/持久限速/一次邀请、前端epoch/私有缓存/管理员 | 8be4f9d隔离后端616PASS、前端453PASS/typecheck/lint/build0；b2e982d整改后前端454PASS/build0及增量High闭环；g2域名待验 | DOING | Chat/Accounts/Frontend High整改闭环；整体验收等待g2域名；harness R2 High全部P2闭环；actual seed失败，R3 bootstrap/report整改中 |
| NH-PUB-06/S02/S04/O01/O02/O03/G3 旧费用方案 | 用户已取消 | 不实施站点API/费用/日额度/Token预算 | 不再派发五份旧合同；未写代码 | NOT_RUN | ADR-025取代费用要求，非实现完成 |
| G3-订阅恢复 | G2、已知订阅协议 | 现有订阅长任务断线/重启恢复与私有隔离，无费用平台 | 离线Fake/取消/恢复/Owner/High，翻译ADR026合同已冻结，等待08审查后派发；研究ADR027已定，专用合同待冻结 | TODO | 不含费用/日用量限制；网站真实接入外部依赖 |
| NH-PUB-07 | P00 | openai-hosted-integration.md；身份/plan 批准分离 | 准备文档离线校验0；真实申请未提交/两批准EXTERNAL_BLOCKED | TESTED | d220f00候选；非获批 |
| NH-PUB-08 | G2源码、模式 ADR | subscription service/views/attempt snapshot/0029/tests | 离线模式/快照/当前session/一次消费/nonce/aud/iss/cookie/High | DOING | 源码准备与定向测试；真实订阅未调用，未审核 |
| NH-PUB-09/G4 | 07真实批准/08协议/G2/订阅隔离恢复 | 获批 user plan Provider（未授权禁止派发） | 2获准账号真实 OAuth/撤销/私有凭据与缓存隔离 | EXTERNAL_BLOCKED | 无正式批准 |
| 公网 DNS/TLS/服务器发布 | G1、额外授权 | 仅现场变更单，禁止自动执行 | 真机证书/DNS/端到端验证 | EXTERNAL_BLOCKED | 未获写授权 |

历史 ID 去重：S01→G2；S02/S04/O01/O02/O03→06；S05→内容安全；P01→G2。S03→03/G2，O04→04（reference-plan明确关联）；O05/O06/P02/P03 因本地参考未提供原定义保持 NOT_RUN，不宣称被前项覆盖。密码重置因邮件策略未定为 BLOCKED，待 G2明确；不妨碍其他本地任务。

| 本地域名/HTTPS G1/G2/G3追加 | 02/04/05/10，G2账户，G3任务 | 独立CA/NSS/Nginx/browser/隔离资源 | G1实际domain+volume PASS；g2源码隔离77PASS且R2 High闭环，actual seedFAIL/browser NOT_RUN，R3整改中；无费用订阅恢复TODO | DOING | 91dc86b G1 REVIEWED；公网EXTERNAL_BLOCKED |
