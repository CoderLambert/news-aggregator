# 开发批次集中验收记录

本批基线为 `main@703af0f161119374593b79325165b3f42a69b198`。验收隔离工作树为 `/tmp/newshub-consolidated-acceptance-20261020`，原始日志保存在 `/tmp/newshub-acceptance-703af0f/reports/`。本记录不代表生产发布或六厂商真实验收完成。

## 已确认并修正的问题

- T02 手填模型最多 160 字符，实际探测路由允许 240 字符，但审计模型字段仍为 80。新增回归使用合法的 160 字符模型 ID，经创建、显式探测和完整 alias 校验；修复前确实失败于 Django 字段验证（169 > 80）。`0072` 前向迁移将审计 alias 扩为 240，保留已有模型和回执身份，不改历史迁移或截断 ID。
- AG-01/AG-05 的五项旧回归仍 mock 已移除的个人客户端入口。现复用连接创建与显式探针 API，取得当前 T03 模型快照，在实际 gateway 构造边界替换合成响应。保留目录 GET 无网络/无模型/无写入、推理前标题变化零调用、推理中标题变化不得提交等原断言。
- 公共 capability 固定 schema 补入已合并的 `research_byok_create`，继续检查关闭状态与无秘密数据。研究门禁分别验证 AI 关闭时 403、AI 开启但 hosted 未批准时 503，两种情况均不得创建运行或会话。

## 实际检查

| 检查 | 当前结果 | 范围与限制 |
|---|---|---|
| 第一轮完整后端 | FAIL：串行 85 passed；并行 2576 passed / 9 failed / 16 skipped | 七项旧合同/fixture 失败如上；另两项分别是 root 身份使 user-mismatch 假设失效，以及未挂载 Docker daemon 导致真实 context 测试无法运行。保留首次失败日志 |
| 修复前定向回归 | 47 passed / 1 failed | 长 alias 负例真实失败，其余迁移后的合同及 CI 非 root 身份测试通过。日志 `acceptance-fixes-red.log` |
| 修复后完整后端（SDK 权限未补齐） | FAIL：串行 85 passed；并行 2585 passed / 1 failed / 16 skipped | 只剩非 root 用户无法读取先前 SDK 目录、导致 Anthropic 导入失败；真实 Docker context 与原九项失败均已通过。日志 `backend-fixed-full.log` |
| SDK 权限补齐后的完整后端 | PASS：2671 passed / 16 skipped；2687 个收集/执行身份完全对账 | 原 `ops/ci/benchmark-xdist.sh`：串行 85、并行 2586 passed / 16 skipped，完整轮次 187 秒，退出 0。日志 `backend-fixed-sdk-full.log`；保留原串行清单、两个 worker、断言及 skip 预算 |
| 完整前端 | PASS：105 文件 / 730 用例 | Node 22，typecheck、lint、完整 Vitest 与 build；一条已有 hooks lint warning。源码与本修复的后端差额无前端变更 |
| T00 SDK/Proxy 协议 | PASS：239 / 239 | 原 `probe.py`，官方 SDK→固定 LiteLLM 1.105.0→合成 HTTP 上游；临时 PostgreSQL，零真实 Provider。另有探针 unittest 37 项、Key guard unittest 27 项通过 |
| CI 工具契约 | PASS：50 用例 | 原 `ops/ci/tests` unittest discovery |
| 后端依赖锁 | PASS：160 个安装版本 | 只读既有 Python 3.12 缓存，补齐现成 SDK 包；没有向共享环境安装 |
| 基线生产候选镜像 | PASS | `newshub:accept-703af0f`，release label 为上述基线；修复后最终镜像/G1 另记，不把旧镜像当作最终候选 |
| 标准 G1 probe 镜像构建 | FAIL：Chromium CDN 下载超时 | 原失败日志保留，没有修改仓库 Dockerfile |
| 缓存版 G1 probe 镜像 | PASS（构建） | 仅临时 Dockerfile 将浏览器下载改为复制现有 Chromium 1234，仍安装原 Playwright 1.62.0 及系统依赖；实际 G1 尚未执行 |
| GitHub CI | NOT_RUN | 核对时两个 self-hosted runner 均 offline；沿用用户授权的 `[skip ci]` 集中验证，不伪造 merge-gate 成功 |

后端使用 Python 3.12、UID:GID 1001:121、临时 SQLite 与合成凭据。SDK 权限问题确认后，仅将四个公开 Anthropic/docstring-parser 包目录复制到本次私有目录供该 UID 读取，没有修改原 SDK/共享缓存权限；预检确认 Anthropic 1.13.0、OpenAI 3.31.0。Docker context 用例只创建/删除随机命名的测试镜像和未启动容器；没有真实数据库、生产目标或收费模型调用。后端完整运行通过后须保留动态收集/执行身份对账结果，不能只相加 pytest 的显示计数。

## 后续验收边界

最终镜像与隔离 G1 已通过（见下），Django/Proxy 联合检查及新授权的 DeepSeek 有界调用仍待完成。其他厂商真实 Key、来源质量/许可判断、人工产品体验与延期的生产门禁仍须分别列明，不能以此报告替代。生产切换、停止旧角色及依赖该前置的旧栈删除继续延期。

缓存浏览器来源固定为现有 CI 镜像 `sha256:666633c9799531b12f4be1525bf6679040a89b52fe0d1efa3e0e9a33923faae6`；缓存版 probe 镜像 ID 为 `sha256:10be5998a22e7b6ee23692f46f63a8e3be267af67d9f3f887ab17935864ee775`。临时 Dockerfile 和构建日志保留在验收目录，仓库正式构建入口不变。

T00 使用独立新建的 Python 3.12.14 SDK/Proxy 环境，按原两份锁文件安装，未修改共享依赖。依赖准备完成后以 Node 22.23.3 重新生成并确认 Prisma；协议运行清空继承环境，只连接临时本地服务。原始结果为 `/tmp/newshub-t00-acceptance-20261020/report.json`，日志 `t00-full.log`。原报告明确保留历史镜像/验签、真实 Provider 和 UAT 为 NOT_RUN，239 项通过不替代这些门禁。

## 合并后候选与隔离浏览器验收

修复已由 [PR #152](https://github.com/CoderLambert/news-aggregator/pull/152) 合并，运行时验收 SHA 为 `36c24dc65bff80679ea6ad14d8741969a29b6929`。该合并树与已运行完整后端及 T00 检查的 PR head `68f6e00a9f9af9ccf6358e6643d31e0b824124c8` 无文件差异。原工作区仅合并更新代码，原 SQLite 与两份独立文档保留。

- 生产目标镜像 `newshub:accept-36c24dc` 构建退出 0，镜像 ID `sha256:60e7db9e521e33b23d44019229fd1ead1ceb3257ac95af32592b4dd870d7cfe3`，revision 为上述精确 SHA，运行用户 `10001:10001`。日志 `production-image-36c24dc.log`。
- 原 `scripts/deploy/local-domain-smoke.sh --execute` 使用该镜像、固定 Nginx digest 和前述缓存版 probe，退出 0。实际浏览器首页/新闻深链、Mermaid、TLS 错误证书拒绝、CSRF、只读权限、静态资源/404、数据库迁移及健康检查通过；合成 SSE 首帧 9ms、总耗时 1010ms，不能当作真实模型流式指标。
- 最终报告 `/tmp/newshub-acceptance-703af0f/fixed-tmp/newshub-local-domain-report-36c24dc65bff80679ea6ad14d8741969a29b6929.ILcTS4/report.json` 在脚本退出后确认 `status=PASS`、`cleanup_status=PASS`。按本次随机 Compose project 查询，容器、网络和卷均已清理。
- G1 为隔离合成环境，不能替代 full 模式账户/新功能 UAT、Django WSGI 实际客户端地址、真实 Provider 或生产验收。正式 CI 的标准浏览器下载问题仍保留，缓存版通过没有改记该次标准构建为 PASS。

## 联合链路发现的流式统计尾帧差额

`36c24dc` 的 G1 只证明只读/合成 SSE；另跑原 `t04_django_localproxy.py` 时，正常问答先收到文字却最终失败。定向只记录帧结构/异常类型，确认固定 Proxy 在 `stop` 后发送 `choices=[{index:0, delta:空, finish_reason:null}]` 的 usage 帧；业务验证器只接受 `choices=[]` 的 usage 帧，在后续空 choice 处拒绝。原失败日志 `t04-proxy-36c24dc-mounted-python.log` 与结构诊断 `t04-diagnostic-frames.log` 保留，没有输出提示/Key。

- 新官方 SDK frame 回归修复前 1 failed / 11 passed（`stream-trailer-red.log`）；修复后该组 12 passed（`stream-trailer-green.log`）。另补统计尾帧后发生传输错误仍须失败的用例，共 13 项已纳入下述完整矩阵。仅接受已见严格 stop、index=0、无内容/角色/工具/拒绝/思考字段的一次统计尾帧；继续消费到干净 EOF，缺 stop、重复统计、后续文字/工具/思考、错误 index/终态继续拒绝。原 Proxy guard、路由限制和取消/提交围栏未改。
- 联合流程随后暴露旧研究夹具把字符串 UUID 直接传给期望 serializer 已解析数据的内部保存函数。夹具现走实际偏好 PATCH，保留原授权与响应断言，没有扩大服务层接受范围。
- 同一联合流程曾在翻译进度 GET 返回 503；单独验证原 pytest 环境实际为 `memory / journal=memory`（`t04-database-mode.log`），不符合应用文件 WAL 的并发运行方式。该联合测试现独占临时文件库，并强制断言文件存在、journal_mode=wal；不改应用数据库配置或为 503 增加忽略/重试。原失败记录保留，不能把切换测试数据库记作已定位所有可能的 SQLite 竞争。

本节的修复尚在验证，不能由先前的完整矩阵/G1 成功推导当前联合链路已通过。

研究工具往返进一步复现未建向量索引时的 `NotFoundError`：默认 hybrid 的关键词分支已有结果逻辑，但 `count()` 在集合尚不存在时抛错，中止整次工具调用。使用实际 Chroma 1.5.9 新目录复现，修复前 1 failed / 1 passed，修复后 2 passed；集合始终未被读取创建。默认 count 对缺集合返回 0，显式指定的管理/重建集合仍抛 NotFoundError，其他存储错误仍传播。关键词/semantic/hybrid 和索引恢复的既有授权逻辑未替换，后续完整回归必须覆盖这些消费者。日志 `vector-cold-red.log`、`vector-cold-green.log`。

后续使用文件 WAL 的完整联合流程已越过问答、取消、T05/T06 翻译与 T09 正常工具往返；但在原 T09 `NO_FINISH` 负例中，原始上游 JSON 没有 finish_reason，研究却被记为 succeeded。该轮仍为 **FAIL：1 failed / 2 passed**，日志 `t04-file-wal-cold-index-green.log`。这是待修复的原始终态证明问题，不能修改预期为成功、仅依赖 LiteLLM 归一化后的 stop，或以其它矩阵通过覆盖。新的 DeepSeek 真实调用继续等待这条负例修复。

上述统计尾帧/冷索引修复后的三根完整矩阵退出 0：串行 85 passed，并行 2601 passed / 16 skipped；总计 **2686 passed / 16 skipped，2702 个收集/执行身份完全对账**。原始日志 `backend-stream-vector-full.log`，单轮 187 秒，无测试重试。它证明这批源代码回归范围；独立 Django/Proxy 联合负例仍 FAIL，尚不能 Ready/发布或宣称研究终态合同通过。

## 原始非流式终态修复与复核

在后续批次中，现有 `ProviderKeyGuard.async_post_call_success_hook` 验证固定 LiteLLM 1.105.0 的实际请求私有 `Logging` 对象与其原始响应 JSON；拒绝缺失/空终态、重复 JSON 字段、错误响应、多候选、与归一化结果不一致的终态，以及未知版本、伪造字典或未完成调用记录。只返回静态错误代码，不记录原文/Key。明确的 length/content_filter 等原始非成功终态保留，由原业务层拒绝；不新增厂商 adapter、直连或付费重试。

- Guard 定向单元：修复前 31 个测试中有 15 个负例 subtest 失败；修复后 31 个测试通过。日志 `raw-completion-guard-red.log`、`raw-completion-guard-preserve-length.log`。整个 shared gateway 静态/CLI/guard pytest 共 35 passed，日志 `shared-gateway-tests-final.log`。
- 第一版 guard 过度拒绝已明确给出 length 的响应，原 T00 检查如实报 238 passed / 1 failed（`t00-raw-terminal-proof.log`）。修正为保留已证明的非成功终态后，原 239 项全部通过，没有改旧截断断言。新增通用 Chat alias 的缺原始终态拒绝及上游恰好一次派发验证，最终 **241 / 241 PASS**，日志 `t00-raw-terminal-generic.log`，报告 `/tmp/newshub-t00-acceptance-20261020/raw-terminal-generic-report.json`。
- 原 Django/SDK/Proxy 联合流程 **3 passed**；再新增明确 length 的研究负例，验证真实 raw finish_reason=length 存在、SDK保留该状态、研究仍失败且无完成事件/会话报告，最终 **3 passed in 30.07s**（`t04-raw-terminal-length-evidence.log`）。原上游脱敏 recorder 补齐 length 的事实字段；缺终态等旧负例断言不变。
- 固定 digest 的真实容器镜像已跑原 T00-G 合成运维流程，**26 checks PASS**，包含两项目 Key、路由隔离、日志、重启、备份恢复与清理；零真实 Provider。日志 `t00g-fixed-image-raw-terminal.log`。新增该镜像缺原始终态/恰好一次请求/错误不泄密的用例后，**28 checks PASS、退出 0、cleanup=0**（`t00g-fixed-image-negative-terminal.log`）：HTTP 502，上游从 2 次变 3 次，确认为恰好一次派发，无秘密/提示泄漏。没有以 Python Proxy 进程结果代替镜像级结果。

上述当前结果修复了前节 NO_FINISH 的误成功；最终合并后镜像/G1 与有界 DeepSeek 真实调用仍待继续。正式 GitHub CI、生产和人工 UAT 继续分别保留状态。
