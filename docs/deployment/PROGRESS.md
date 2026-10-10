# 执行证据与下一任务

## 2026-10-10 P00 / 重启目录确认
- 当前合同已移动至根 GOAL.md；保留用户 START_HERE.md、.codex 和参考文档。
- git fetch origin 退出0；origin/main 与 HEAD：8c2823e1fcf8cbea38e9bb7c4e98a33232025fbd。计划旧基线 80d28756f1236347d104e69a76c86e6d707b1376 已过时。
- 工作分支 feat/news-public-readiness。backend/db.sqlite3 是用户已有未提交修改，未覆盖/迁移/提交；用户其他未追踪文档保留。
- 已读 README、docs/startup.md、compose.yaml、Docker/Waitress/entrypoint、settings、API urls/权限、测试命令、Provider 路由、研究 CSRF、Chat 归属及 Mermaid；具体发现见 ARCHITECTURE。
- codex --version=0.161.0；features list goals/multi_agent=true（退出0）；原生工具发现所需 implementer 与 security_reviewer 固定角色。子 Agent 尚未派发，不将配置文件存在等同模型实测。
- Docker info 退出0，daemon 29.7.2。Python venv/Node依赖存在；dig/nginx 缺失。公网 DNS/证书/真机只读检查 NOT_RUN，生产写入与真实 API/OAuth EXTERNAL_BLOCKED。
- P00 状态 TESTED（本地盘点与架构/任务方案），不是部署成功；功能测试、check --deploy、镜像/恢复、安全里程碑审核均 NOT_RUN。
- 下一任务：NH-PUB-01 只读预检脚本与离线负例；同时主 Agent 冻结 NH-PUB-03 配置/代理/探针完整合同，再派发实现。G1→G2→G3→条件G4按合同推进。

### P00 后续冻结/调度证据
- P00文档提交：f7371da5664fcd1c34fba76f0b8805f15fa42fd5；本次恢复前回合为 progress（fetch/真实代码盘点证据），被用户暂停中断，未重复启动已有实施进程。
- 原生 /root/pub01_preflight 与 /root/pub03_settings 已运行，agent_type=implementer，由工具角色定义固定gpt-6-luna/max；最多2子Agent，无再派生。已发包含全部8字段的实现合同及03网络决策补充。
- 当前9527已被用户服务监听，禁止停止/替换；Docker现有镜像可用于缓存，隔离测试端口19527。
- ADR006 API门禁/能力协议、ADR007生产绑定/代理来源、ADR008不可信内容输送已由主Agent冻结，尚未验收。
- web open https://news.lambert.host/ 返回工具不可访问；只证明该工具未取得页面，不能推断DNS不存在/站点宕机，公网端到端仍NOT_RUN。
- 01首轮语法/TLS mock失败由实施Agent按证据修复中；03测试尚未返回，不宣称PASS。下一步收敛01/03定向测试，再派发05门禁及独立S05前端安全切片。

### 用户范围澄清
用户明确news.lambert.host尚未使用，先完成开发、测试与审核再上线。当前停止一切真实域名/服务器探测，预检只验收离线mock；现场DNS/TLS/服务器核验为发布时NOT_RUN，真实写操作仍EXTERNAL_BLOCKED。此澄清不缩减G1/G2/G3与G4合法骨架的开发验收范围。

## 批次01/03：本地定向验收
候选HEAD f7371da5664fcd1c34fba76f0b8805f15fa42fd5 加本批diff；独立High里程碑审查尚NOT_RUN，任务仅TESTED。
- NH-PUB-01：bash -n scripts/deploy/preflight.sh scripts/deploy/tests/test_preflight.sh 退出0；bash scripts/deploy/tests/test_preflight.sh退出0（离线/缺工具/公网IP参数/超时/SAN/SSH opt-in/未知参数mock负例）；bash scripts/deploy/preflight.sh --offline退出2（预期，15项NOT_RUN，零网络）。最初语法与TLS mock失败已根据证据修复并通过，不需再运行同版本用例。真实现场项仍NOT_RUN。
- NH-PUB-03：PYTHONPATH=backend:crawler RUN_MAIN=true backend/venv/bin/python -m pytest backend/api/tests/test_production_settings.py backend/api/tests/test_health.py tests/backend/test_waitress_proxy.py -q 退出0，44 passed；仅chromadb依赖弃用警告。
- 生产manage.py check --deploy（DJANGO_ENV=production/DJANGO_DEBUG=0/合成50+字符密钥/WAITRESS_TRUSTED_PROXY=127.0.0.1/RUN_MAIN=true）退出0；仅W005/W021，ADR005说明单域HSTS试运行不含子域/不预加载。没有SILENCED_SYSTEM_CHECKS。
- 指定py_compile、env模板空Key核验、git diff --check退出0。主Agent核对health仅SELECT1/live不查库、Waitress代理洗头与WSGI scheme测试、Secure Host-only Cookie测试及生产不读dotenv/Hermes。部署网络实际smoke待04验证。
- 角色生效证据来自调度工具的固定role/model/effort定义；两子Agent运行界面自身不提供独立查询标签，如实记录，不把TOML文件当实测日志。
- 下一批：NH-PUB-05完整契约已存contracts/NH-PUB-05.md；独立S05-FRONTEND存contracts/S05-FRONTEND.md。03通过后执行；禁止生产资源/真实Provider/OAuth。

## S05-FRONTEND 本地定向验收
候选基于7bef7fbcb580bdd528cafbe38b946abfcc5536f5；High完整G1审查待后续，状态TESTED。Mermaid strict/不可覆写安全配置/20k字符500边/真实DOMPurify SVG净化，Markdown skipHtml；懒加载和过期取消保留。dompurify3.4.7直接依赖，lock只添加直接声明，未升级。
- cd frontend && npm run test:run -- tests/components/news-detail/MarkdownContent.mermaid.test.jsx tests/components/news-detail/MarkdownContent.security.test.tsx tests/components/news-detail/MarkdownContent.extractor-contract.test.jsx：退出0，3文件7测试PASS。
- npm run typecheck、npm run lint、npm ls dompurify --depth=0、manifest/lock核验、git diff --check退出0。首轮类型/清理后断言失败已证据修复；未再重复同版本通过测试。
- 主Agent核对实际diff：SVG二次净化、未执行bindFunctions、危险DOM/超限/Markdown链接负例实测；按React技能核对effect生命周期、hook顺序、直接依赖、懒加载，未发现本切片集成冲突。
- 自动继续：/root/pub01_preflight复用为S05-BACKEND安全HTTP输送；NH-PUB-05仍正在逐46route×methods测试。04合同/ADR009已由主Agent冻结，需05整合后执行。

## NH-PUB-05 本地定向验收
候选HEAD f537b7baaf59562cc39d1916bbf37901a89908f4 加05diff；状态TESTED，High待完整G1。实现按路由/方法read_only拒绝，capabilities no-store；46路由枚举、匿名/登录/管理员、模型0调用、DB无写入；CORS预检短路已复现并由Sol补充合同修复；full+AI1语义兼容/full+AI0语义关闭已消除合同歧义并实际mock分支证明。
- 合同pytest(public_policy/health/production_settings/waitress_proxy)退出0，63 passed（3条依赖/分页警告）。public_policy单独19 passed退出0，两个CORS定向2 passed退出0；git diff --check/py_compile退出0。主Agent核对实际policy/capabilities与回归，不重复已通过版本测试。
- 用户新增“本地域名测试验收”已纳入ADR011：Docker DNS alias+测试CA+独立Nginx443与临时浏览器信任，不修改hosts/系统CA/公网。新增G1/G2本地域名发布门槛，尚NOT_RUN。
- 下一任务：04阶段A生产Compose/卷/非root/迁移/静态导出；S05-BACKEND继续，完成后10前端能力感知与本地域名/反代模板验收。

### S05-BACKEND 总期限验收整改R1
初始五文件88PASS，最后safe_http40PASS/py_compile/diff-check0；初始证据只覆盖慢body。主Agent追加离线probe（mock socket.getaddrinfo sleep0.1、safe_urlopen timeout0.01）实测elapsed0.1，暴露DNS无总deadline；代码检查getresponse header parsing亦仅idle timeout。不能将初版88PASS当完整S05 gate。已发R1，仅safe_http/test_safe_http，ADR012冻结有界DNS/所有读取绝对deadline/GET边界；任务仍DOING，High尚NOT_RUN。

### CI收集范围诊断
主Agent分别实际运行collect-only（未执行测试/业务Provider）：backend/api/tests/退出0、355tests；tests/backend/ backend/api/tests/ tests/crawler/退出0却仅51tests且没有API节点。原因根pytest.ini filename pattern过窄，而backend/pytest.ini模式广。NH-PUB-11增加root pytest.ini修正和三目录节点范围证据；当前不能宣称后端全量PASS。

## S05-BACKEND / R1 本地闭环
候选HEAD d7b247b8149625d6a636832616ad9dccd5e35362加安全输送diff，状态TESTED，独立High待完整G1。生产URL全地址校验/固定sockaddr/peer核对/TLS SNI与验证/每次跳转/2MiB限制；生产Jina/subprocess明确禁用，开发兼容。
- 最终六file pytest（safe_http、article_fetcher_security、article_fetcher、provider_comparison_service、article_fetcher_quality_report、provider_comparison_api_command）：退出0，106 passed，1 chromadb依赖弃用warning。py_compile/diff-check/空白检查0。R1首次参数名request触发pytest保留名收集退出2，改名后验收通过；没有改变安全协议。
- DNS固定2线程/2pending限额、慢头/状态行/正文绝对deadline、累计wire2MiB+64KiB/仅GET无data均新增离线负例。主Agent重跑原失败probe：slowDNS0.1/requestdeadline0.01现在elapsed0.011秒即UnsafeURL Public DNS resolution deadline exceeded，证明旧缺口已修复；底层DNS尚待返回但最大2个，无新连接。
- 比较API现fixture同步到安全DNS目标，DB中News URL同样验证；未执行真实DNS/HTTP/TLS/付费。后续G3的研究/翻译候选网页也必须接此输送，当前不把关闭入口当最终安全。
- 下一步：10前端能力感知；04阶段A定向闭环后02/本地域名阶段A；稳定候选完成CI/真实Docker/本地域名与High再过G1。

### 04阶段A与容器上下文整改
04A实际54PASS（数据路径/临时migration/并发锁/容器配置/03/Waitress），bash-n/export mock/合成Composequiet/diff-check退出0；04-A-R1默认开关映射与Workerhealth补充后context8PASS/composequiet/export mock/diff-check0。真实生产镜像/卷/本地域名/恢复仍NOT_RUN，04整体DOING。
主Agent额外真实FROM scratch上下文probe构建0，发现嵌套dummy backend/.env、frontend/.env.local、backend/media/tts_cache/private.mp3 included；自建镜像/container精确清理。已签04-A-R2仅.dockerignore/context tests/container docs，增加层级秘密/缓存排除并实测fixture；不是读取真实秘密或构建生产镜像。待R2通过整合，自动转02本地域名阶段A；10正并行实现前端能力与关闭自动请求。

## 04阶段A/R1/R2整合（正式镜像阶段B待执行）
候选HEAD fa7e8bdb5e4d61bd75ddfb50a3a5858510dab2af加04diff。路径/迁移锁/Compose/静态导出代码闭环；整项04仍DOING，生产Docker build/smoke/卷持久性NOT_RUN，High尚待G1。
- 04A54PASS与shell/export/composequiet检查0；R1八开关default/explicit覆盖与两Workerhealth回归8PASS；R2 context9PASS，实际Docker最小synthetic build/cp证明nested env/credentials/cache excluded、source.py/token_manager.py/frontend源码 included。首轮scratch无CMD create失败已补未启动占位命令后通过。测试随机container/image最终无残留，未真实build生产image/读用户DB/改变运行服务。
- 默认development/root保留旧bind-mount SQLite权限，production必须--target production且UID10001/SHA标签；生产卷paths、flock迁移一次性service、app/Worker依赖和静态current/previous/共享hashassets已由主Agent读diff整合。
- 下一批：02+本地域名阶段A（生产模板、测试CA/DNS alias/browser脚本开发与离线/语法核验）；10仍实现capabilities UX。待10结束整合commit才build同SHA镜像，执行04B和正式域名本地HTTPS验收。

## NH-PUB-10 前端完整边界验收
候选HEAD baa21eacb5055ae7a0dbd15fffa0e94be7b3be3c加10前端diff；状态TESTED，High待G1，未访问真实站点/Provider/OAuth。17feature强类型与fail-closed provider、私有deep route保护、按钮/自动fetch/translation恢复门控、keyword fallback、私人缓存marker清理、local handoff精确URL与SEO均实现。旧full行为用显式fixture验证，无test环境全开豁免。
- 4新增定向文件31tests PASS退出0；cd frontend && npm run typecheck && npm run lint && npm run test:run && npm run build退出0，全量63files/421tests。首轮测试generator无yield lint错误已修复合法progress event后全链通过，最终版本不重复跑。git diff --check0。
- 主Agent核对CapabilitiesContext/FeatureRoute/AuthContext/API schema、禁用时不挂private页面以及默认ctx关闭，逐owned diff统计未见越界；后续G2还要补Auth refresh/logout并发响应的epoch保护，不将当前cache清理当全部账户竞争验收。
- 下一任务：11/12真实测试收集/CI/一致快照恢复与dryrun发布，独立于02本地域名脚本；02当前上游9527保留生产模板，19527仅04 host-network smoke。

## 本地域名验收要求与02阶段A结果
用户要求后续开发补充本地域名测试验收，已在local-domain-testing.md明确为固定开发/上线前门槛，并区分G1只读、G2账户与G3离线任务链路。使用正式域名、隔离DNS alias、临时CA及独立Nginx，不修改公网DNS、hosts、系统证书库或现有服务。
- 02实施返回：PYTHONPATH=backend:crawler RUN_MAIN=true backend/venv/bin/python -m pytest scripts/deploy/tests/test_nginx_templates.py -q退出0，4 passed；shell语法、mock参数测试、py_compile、diff-check均0。原合同不带PYTHONPATH的pytest退出1，原因是pytest-django找不到newsaggregator，不能将该命令记录为通过。
- 当前候选HEAD 5c0e46bec0e3d933daf8207848f5a767fffc31ef；阶段A文件尚未提交。实际Docker/Nginx/HTTPS/browser链路、截图、TLS负例及SSE时序均NOT_RUN；G2/G3也NOT_RUN。上线现场公网验收仍EXTERNAL_BLOCKED。
