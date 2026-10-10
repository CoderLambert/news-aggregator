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

## 恢复执行与真实后端全量
- 02阶段A及本地域名要求已提交7f1148dd5e1bafc4aaba72ac68e75dc7616e1233；当前两实施任务为11/12收尾与04B/本地域名实际运行。ADR018/合同补充停服后的旧manifest一致快照，迁移失败不自动跨schema启动旧版本。
- 主Agent从上述已提交HEAD git archive建立/tmp/newshub-full-tests-99_v8thk/source隔离副本，仅复制修正的pytest.ini；子进程独立临时HOME/SQLite且无用户env/Key/Hermes。实际三目录全量pytest退出0，收集432项全部通过（3个已知依赖/分页warning），日志/tmp/newshub-full-tests-99_v8thk/pytest.log。未读取或改动用户数据库；此证据替代原51项不完整收集。部署助手定向测试由11/12另验，真实CI尚NOT_RUN。
- G2-CHAT合同已预先冻结，但须G1本地门槛完成后才派发；不能将合同准备记作功能完成。

## 11/12本地定向闭环与构建网络诊断
- release_finish返回owned pytest16PASS，shell语法/mock发布与回滚/备份恢复exit0；包含真实repo compose路径、旧manifest停服快照、失败闭锁、120s快照deadline/半成品与连接清理、CI固定actions/Nginxdigest。三root collect-only452items exit0（432既有+4Nginx+16release），CI远程运行及Docker volume恢复尚NOT_RUN；状态为TESTED而非REVIEWED。
- 正式production build固定app源码7f1148dd5e1bafc4aaba72ac68e75dc7616e1233；第一轮Docker bridge apt反复超时且npm ci 198.5s内部错误退出1，日志/tmp/newshub-production-build-7f1148dd5e1bafc4aaba72ac68e75dc7616e1233.log。主Agent对比同Debian InRelease：宿主curl200/1.328s，curl容器hostnetwork200/1.045s，bridge12s超时28。仅本地构建加--network=host重试，应用验收仍internal网络；无daemon/生产配置改动。
- hostnet构建大文件网络仍慢但有进展，保留独立日志/tmp/newshub-production-build-hostnet-7f1148dd5e1bafc4aaba72ac68e75dc7616e1233.log；主Agent一次延长上限至30min，连续10min无I/O/输出进展停止，不无限重试。已实际完成frontend dist与torch CPU依赖安装，整镜像/真实HTTPS/browser尚未PASS。
- G2账户/前端、G3core与08模式合同已准备待依赖通过后派发，仍非功能完成；当前先冻结G1代码开展High完整相关diff审核，Docker运行验证并行且修复必须重新定案。

## G1集成与High首轮审核
- d220f006445986756f86032bd47afeb9764475fc隔离git archive全量452 tests实际运行退出0/452PASS（3已知warning），日志/tmp/newshub-g1-integrated-sm8tucwn/pytest.log；独立临时HOME/DB无用户凭据。
- g1_security完整G1相关baseline→d220f00静态只读审核返回4P1：export-static公开目录0700/files600；backup容器python重复argv及host600manifest不可读；共享历史assets污染两版本manifest；production-containers直接up绕维护窗口。另3P2：capabilities重取失败沿用full；代理头验收用redirect豁免health不证明secure；priorbackup未证明当前target完整内容对应。均非已整改，G1不能REVIEWED。
- 审核前后实测HEAD/120个任务文件hash/完整相关diff SHA256均相同（d5227323dda25405f5d95b797174291fa585266d012f1782fef039c124b6f70b），未含用户DB；审核未写文件。预hash/tmp/newshub-g1-audit-pre-d220f00.json。
- 主Agent冻结G1-RELEASE-R1/ADR020，待Luna定向整改；真实Dockerbuild还在有界推进，前端dist已完成，整镜像/运行验收仍NOT_RUN。

## G1审核整改定向闭环（复审/实际运行待完成）
- G1-RELEASE-R1返回：四P1按ADR020整改，restore P2持锁完整内容对应核验；shell syntax/export-static/release mock0，release_operations21PASS退出0，diff-check0。实际异UID Nginx与production volume仍NOT_RUN，不将mock当真实运行。
- G1-CAPABILITIES-R1仅context与既有测试：cached full重取reject/非法schema即FAIL_CLOSED，成功后恢复；QueryClient真实5tests/typecheck/lint/diff-check均0。NH07申请准备文档离线校验0；两项正式批准仍false/EXTERNAL_BLOCKED，未提交申请。
- domain_runtime代理P2：非豁免auth/csrf路径真实scheme/cookie检查，Fake头回显另记录，无法观测Django clientaddr明确NOT_RUN；新增3定向pytest、shell syntax/mock、py_compile/diff-check全0。尚未实际运行镜像/浏览器，不预填PASS。
- 原始build下载依赖文件受限：官方Django HTTPS range256KiB host11.2s/container8.0s，TUNA4.4s；镜像cache probe证明pip层未命中，90s内取消probe130而保留原构建。为了不重复下载已安装Torch，主Agent最终一次有界延长原build至90min，连续10min无IO/输出停止、不自动重试、不更改依赖/registry。正式G1实际验收需依赖层完成后，用修复候选新SHA快速重建frontend/label再运行。

## R2实际Nginx与前端集成
- R1 High复审仅新增旧chunk路由P1，其余4P1/3P2静态闭环；posthash23文件/HEAD/diff均相同。domain_runtime两assets块显式root /srv/newshub、仍全站current；主Agent真实Nginx启动检出原regex花括号语法错误（独立nginx-t exit1），Luna仅引用两regex后实际nginx-t exit0、模板4PASS/diff-check0。
- Primary真实静态fixture第一次仅两release文件/hash通过，Nginx启动失败（container exit1/exec137，无OOM事件）；自有资源清理PASS，失败报告/tmp/newshub-static-runtime-4u529uwg/report.json，不冒充通过。修复后用原production模板、pinned Nginx、自签SAN信任cert且无TLS绕过：A/B源码自身diff/hash、umask077、异UIDworker101/导出者1000、HTTPS首页/旧新chunk200且immutable、缺asset404无immutable、静态切回A旧新chunk仍200、cleanup全PASS；报告/tmp/newshub-static-runtime-r2-asp3ztzb/report.json，template SHA256 bab3dddbbe5ba10220d58b8c9c444c5e98c107b33831bf5c4479fedada54a7ed。
- 前端0df4b1e已提交源码独立archive复验（临时HOME、仅symlink已有node_modules、无真实env）：typecheck/lint/test/build全0，63files/423tests PASS；日志/tmp/newshub-g1-frontend-uh95b72m。正式production app/volume/browser仍NOT_RUN，不能以静态fixture替代；下一步R2增量High及新SHA镜像运行验收。

## R2增量审核与非hash资源实际验收
- High对22214b3增量静态审核无P0/P1，剩余P2为generic static regex抢先匹配非hashassets；仅排除assets/，保持hash规则优先，不使用^~。前后6文件/HEAD/diff一致，diff SHA256 41d4f02b0d3db70e19811b6059ab96a69a9ff2d86bea0773b8e570136cf40732。
- 正式模板实际隔离Nginx、network-none、临时SAN证书与curl CA校验：共享目录独有SVG/font200 no-cache、hashJS200 immutable、missing两类404无immutable、nginx-t与清理全部PASS。报告/tmp/newshub-static-nonhash-2y77fckr/report.json，template SHA256 436b67d1b1b143f9bd70d6b69dc32d21d68056659856e5f81f0174556f603828。
- 22214b3隔离后端全量退出0/460PASS，日志/tmp/newshub-g1-r2-integrated-stumdn6b/pytest.log。生产应用/卷恢复/完整浏览器仍待镜像，G1整体不能标PASS。
- 独立90秒HOME位置cache probe在apt阶段超时124，未到pip，无命中或失配证明；仅自身Dockerfile临时变动已全部撤回，无probe image。先前--cache-from错误只是registry importer授权拒绝，不能证明本地层不存在。日志/tmp/newshub-g1-build-cache-probe.log。原正式构建继续最终90分钟边界。

## 后续源代码准备与门槛保留
用户再次要求持续完成全部任务。ADR021冻结221a93d为G1运行候选，未来构建必须使用其git archive；独立G2源码准备可在网络等待期间离线推进，不改用户DB/生产开关。G1整体仍DOING，G2只有源代码准备不是发布完成，G2整体验收依赖G1真实运行。G1-VOLUME-RUNTIME runner正在准备，实际镜像未给定故runtime NOT_RUN；G3-PROVIDER完整契约已冻结但尚未实施。
- volume runner初版新增两owned文件、17离线测试/compile退出0，runtime未执行。主控整合定位exec --user值被误当container的真实argv兼容问题与失败时创建台账缺口，已给同范围整改；不把初版17PASS当真实CLI通过。
- G3的CORE/PROVIDER/BUSINESS/FRONTEND/DEPLOY与G2/G3本地域名合同已补齐输入、费用、worker/SSE、私有结果及默认关闭策略；全部仍待实施。主控对实际OpenAI3.26.1使用纯MockTransport做timeout/max_completion_tokens兼容probe退出0，发现默认admin/org/project环境继承须显式隔离，已冻结；未真实调用API。

## G1真实组件浏览器检查与优先整改
- volume runner整改40离线测试/compile0，只两owned文件，42a5864提交；实际production image/volume仍NOT_RUN。
- 主控用0df4b1e隔离frontend archive的实际MermaidBlock/index.css、独立临时HOME/Vite loopback19357、Chromium与禁外部请求fixture，真实labels存在，但computed nodeFill/textFill均rgb(0,0,0)。截图/tmp/newshub-mermaid-component.png已人工检视，节点黑块且文字不可读；JSON /tmp/newshub-mermaid-component.json。临时Vite session已Ctrl-C退出130，仅自身测试服务；不是正式域名验收。
- 已冻结G1-MERMAID-READABILITY/ADR023并派Luna定向修复可信静态CSS；保留全部SVG安全限制。原221a93d不再用于最终PASS，依赖层完成后需新修复SHA重建，G1失败优先于G2源码准备。
- 构建11:29:43+08起的最终90min硬上限仍12:59:43；pip当前到numpy16.7MB慢下载，连续10min无I/O停止。不再延长/换旧开发镜像替代，网络未完成如实记录BLOCKED并继续独立本地源码工作。

## Mermaid R3闭环与用户授权构建重试
- 可信CSS初版配色恢复后实际截图仍检出文字锚点/原width100%失去最大尺寸的问题；R3仅清洗后viewBox有限数字归一化root宽高与静态text-anchor。19定向测试/typecheck/lint0；主控真实Chromium确认两label bbox均在node内、图173x160、配色244/240/255与17/24/39、危险元素和inline styles0，截图/tmp/newshub-mermaid-component-r3.png人工检视PASS。08838fe提交。
- 08838fe独立archive前端全量63files/436PASS、typecheck/lint0，日志/tmp/newshub-mermaid-r3-integrated-2qg40_rm；不重复旧423项报告。build在正式Docker重试中执行，尚未完成。
- High对22214b3→08838fe七项变化/调用链只读审查无新增P0/P1，发现volume runner两P2（timeout真实ID未补ledger导致清理失败；工作目录mkdir竞争后finally覆盖既有report）。前后HEAD/七文件hash/diff相同，diff SHA256 208f068ffef0033ae1fd2255e395cca9198ebed93b00cdee8f1fc4e50032f838；预文件/tmp/newshub-g1-audit-pre-08838fe.json。已派同两文件G1-VOLUME-RUNTIME-R2，未闭环前不标runner REVIEWED。
- 原hostnet构建在约77min自行失败：numpy16.7MB只到5.8MB，files.pythonhosted.org ReadTimeout、pip exit2/build exit1，无候选镜像。用户随后明确“现在重试”，因此撤销前一轮不再重试限制，仅开启新一轮正式build，不更改依赖/registry。
- 新构建从09c991f148ce63dea639ecb561c54fab7d6583b2 git archive干净context，production target/networkhost/固定SHA，镜像newshub:local-09c991f148ce63dea639ecb561c54fab7d6583b2。日志/tmp/newshub-production-retry-9xvihkw9/build.log，结束result.json记录exit/耗时；单次90min硬timeout，10min无I/O停止。Torch196.3MB已实际下载完成约4.4MB/s；官方PyPI 256KiB range206/2.854s，比旧probe11.2s改善，不能据此宣称整镜像PASS。native domain fallback尚未执行，重试优先。

## 正式镜像重试成功与G1实际验收
- 用户授权新retry实际退出0，493.5s；镜像newshub:local-09c991f148ce63dea639ecb561c54fab7d6583b2，ID sha256:34edcb7f6fc7a7f76ab723c932b1ccafe8dab35c76f489ee785662f55d58b20a。image inspect0，Config.User10001:10001/revision精确匹配；实际network-none/read-only容器id10001:10001、dist index存在/149文件/145 assets核验0。原失败确有网络因素，此次未更改依赖/registry。
- volume R2两P2修复45定向/compile0，1288c0b提交；High增量复审无新增P0/P1/P2，前后HEAD/两文件hash/diff一致，diff SHA256 7184e5d45f26b14ff8f24f57d7579bd9c797b8170dc8dd6f16579ed5c7395cef。实际volume仍待执行。
- 为把最后runner修复纳入同SHA镜像，domain进行1288c归档cached rebuild。监控器初次IO类型错误无candidate；第二次归档普通文件0664对比成功归档0644，COPY模式变化造成npm/pip cache MISS（内容SHA同），6秒内停止pip metadata后exit130无wheel。主控定位并冻结仅自建context使用同tarfile data filter归一化644/755，再试缓存；未改Dockerfile/源/依赖/用户DB。这不影响已成功09c镜像。
- domain实际04B/域名/卷将仅用完成的1288候选和自建资源。native替代fixture没有启动，无需借其冒充容器验收。用户9527与DB始终不迁移、不停止。
- G2-CHAT已按ADR021派发独立源码准备，Base1288c；测试只archive+owned overlay、新HOME/临时DB/无继承Keys。G1 runtime继续冻结1288 archive，未来G2改动不会混入；G1整体仍DOING，G2整体未REVIEWED。

## 生产运行通过，实际验收发现的新增问题
- 1288c候选正确archive模式命中pip/npm缓存，正式production构建退出0/3.364s；image ID sha256:ff3f46904421d8d40d3b2c42554580c46b78dbad01c715316d45d7bcf4f6d36e，UID与revision精确匹配。
- 04B真实独立随机Compose项目：migrate0，app/crawler/indexer UID10001且healthy；仅loopback19527临时入口，read_only查询/capabilities/research403/CSRF Secure host-only/trustedHTTPS检查通过；六卷可写、重建后合成DB与deployment ID保留、SQLite integrity ok。全部自身项目资源已清理，用户9527未操作。报告 /tmp/newshub-g1-runtime-1288c0b5-rxfztgbl/runtime-ad896d18ed/runtime-report.json。
- 正式Nginx模板与模拟既有default_server实际共载nginx-t退出1 duplicate default server:80，报告 /tmp/newshub-nginx-coexist-probe-e4p4tze1/report.json。已冻结G1-NGINX-COEXIST，仅移除news模板全局默认入口、在自身server内拒绝未知/缺Host，不改真实Gitea；待真实共存与域名验收。
- volume runner首次真实执行metadata阶段Docker125：安全shim重复注入--network=none并保留--network none。没有创建卷/容器，cleanup PASS；失败报告 /tmp/newshub-volume-1288c0b5-ff9cc7d78a/report.json，精确诊断 diagnostic/result.json。主控已核实诊断owner名称无残留，冻结G1-VOLUME-ARGV-R3；尚未恢复通过，不跳过该门槛。
- G1整体仍DOING，本地域名完整浏览器/SSE与真实备份恢复尚未PASS；生产DNS/证书/上线仍EXTERNAL_BLOCKED。G2-CHAT独立源码准备继续，未提交以保留纯G1候选归档。

## Nginx共存实际闭环与Chat安全切片
- coexist模板4定向PASS/scoped diff-check0，385f098提交，仅news vhosts自身Host拒绝，不声明全局default。实施fixture先后暴露entrypoint/key映射、只读root缺Nginx临时目录、公开fixture权限及HTTPS444 curl返回码断言错误；这些失败报告均保留，未用语法检查冒充运行通过。
- Sol接管已保留harness，依据镜像实测pid/temp路径只挂tmpfs /run和/var/cache/nginx，公开fixture0755/0644，使用真实proxy snippet；CA校验HTTPS200后444实际curl56/000无HTTP响应，限定HTTPS断连判断52/56而非忽略TLS。真实三配置nginx-t0、bootstrap503/未知缺Host、productionHTTPS200/redirect/未知缺Host、existing Git HTTP/HTTPS defaults及news两协议分别路由全部PASS。报告 /tmp/newshub-nginx-coexist-primary-r2-v4wylwtn/report.json，cleanupPASS，主控postowner无剩余容器；真服务器未操作。正式domain helper相同52硬编码需G1-TLS-CLOSE-ASSERTION最小修正，完整browser仍待验。
- Chat九文件离线准备35定向/3 context回归、makemigrations/check/compile/diff-check均0。独立High切片无P0/P1/P2，前后九源hash/scoped diff相同58f214169f88b117065f444ac95714b486eaff2f234bb6a4005d86a47e1b581b；HEAD因G1无共享文件提交改变，代码未变。预hash /tmp/newshub-g2-chat-audit-pre.json，日志 /tmp/newshub-g2chat.rsGBRS/owned-tests.log。此为Chat切片，不等于G2整体验收；源尚未提交。
- ADR021允许同隔离规则串行推进G2-ACCOUNTS源码准备，不触碰用户DB/开公共开关；G1最后runner/域名helper整改并行仅deploy文件，最终G1构建仍git archive纯G1提交候选。

## G1本地域名与恢复门槛通过，G2集成验证
- R4 High新八文件增量无P0/P1/P2，pre/post源hash及diff9e3941096ebd4ed67d4dd5b9bc3339682ba8fdfa1c1b0f82e84546e76e5aae04一致；真实Host/mixedcase/标准端口/Git共存fixture全部PASS。R5 actual发现BufferedReader错误与Chrome socket长路径，精确三文件修正110定向/compile/diff0；R5 High无新问题，未放宽TLS/trust/sandbox或跳case。
- 为不混入已提交G2，主控从3c141d9独立worktree/branch feat/news-g1-runtime-final-b5836608，仅cherry-pick R5三文件得到纯G1 91dc86b6a5dd212ea29d17f2692888be77e7b254，明确无migration27/28；metadata /tmp/newshub-g1-r5-candidate-77tc8r8e/metadata.json。正式production cached build0/5.824s，image ID sha256:d070c99142e8a8f90079353c00ce60e9b0c538bbd05737003ae4a2b59f13c2e0，UID/revision一致；archive/build记录 /tmp/newshub-g1-r5-build-awwifcv7/。
- G1-FINAL真实volume exit0/全部12checks PASS（private A backup/latest AB prior restore、stale/wrong prior/running mount/tamper拒绝并保持数据、fresh UID10001/integrity、cleanup）；报告 /tmp/newshub-g1-r5-runtime-26a9410d2c72/volume-report/report.json。
- 同91dc86b真实domain exit0/status PASS/cleanup PASS：bootstrap/prod nginx-t、migrate/readiness/static、严格CA未信任拒绝与信任HTTPS200/错误SAN、首页/新闻深链/Mermaid/匿名只读/private无API/CSRF Secure/伪造转发/绝对URI Host拒绝、fake SSE首帧6ms/终帧1007ms与proxy echo通过。正式截图mermaid-g1.png主控已人工检视，节点文字居中可读；报告 /tmp/newshub-g1-r5-runtime-26a9410d2c72/newshub-local-domain-report-91dc86b6a5dd212ea29d17f2692888be77e7b254.8CZwHg/report.json。随机项目/卷/network/profiles/CA均精确清理。真实Django REMOTE_ADDR直接观察NOT_RUN，不将fake echo当该观察。公网DNS/正式证书/真服务器仍EXTERNAL_BLOCKED，未上线；G1本地门槛REVIEWED，继续G2。
- G2 Chat+Accounts19文件944e3c3提交，Frontend实际15文件f7419d7提交，定向39与type/lint0；invite wire canonical invite_token已修正25PASS。Accounts首轮High仅NFKC校验顺序P2、R5无问题，pre/post16文件与scope6d066f13899bff54f88b4fe029d425d127a4b2e0e6de612f5cdb0d7a7de45157一致。G2-ACCOUNT-REVIEW-R1修正先canonical校验与独立子进程legacy迁移，91定向/compile/diff0，8be4f9d提交。旧全量610PASS/2FAIL来自旧默认DB逆迁不可逆并污染schema，已保留失败日志 /tmp/newshub-g2-backend-integrated-w99kgvo6/pytest.log，不修改生产迁移或假reverse。
- 8be4f9dd7fa8f03e9779b8ec35085538b03032d4全新archive/env-i/HOME/绝对临时DB集成后端616PASS/3已知warnings退出0，日志 /tmp/newshub-g2-integrated-final-b87_3y_h/pytest.log；前端65files/453PASS及typecheck/lint/build全0，日志 /tmp/newshub-g2-frontend-integrated-ec_1oiv2/。不读取/hash/迁移用户DB或WAL，未继承keys/.env。G2最终Frontend/R1 High和actual domain stage2仍待验；LOCAL-DOMAIN-G2-IMPLEMENT精确合同已准备，G3仍TODO。

## G2 最终复审：定向整改，未通过整体门槛

候选66a15233f1b95ff6bcdc64c372821bdf487e32f9：独立High确认18文件hash与两scoped diff和pre一致，账户NFKC及旧迁移测试隔离整改闭环；Frontend发现1P2：挂起登录期间accounts关闭→重开，旧finally调用旧refresh，身份generation过期导致本地持续匿名。无新增P0/P1。已签发G2-FRONTEND-REVIEW-R1，只修两文件与deferred回归；G2仍DOING，不声称REVIEWED。616后端/453前端集成PASS仍是整改前证据。

账户R1实施日志补充：archive源f7419d705f0d68f6b36b59b6e6341ec66538b746，仅overlay三owned文件；临时目录/tmp/newshub-g2-account-review.Ots2mT，组合日志/tmp/newshub-g2-account-review-acceptance.log，单独迁移日志/tmp/newshub-g2-account-review-migration-verified.log。最终整合8be4f9d的主控616用例独立复核已通过。

G3在实施前已冻结ADR-024：单SSE record按完整UTF8 wire精确限制16KiB，text增量2048bytes分片，terminal只含状态，完整私有结果由owner GET读取；解决64KiB翻译结果与事件上限冲突。此项仅合同设计，G3仍未实施。G2域名harness源码准备继续，实际运行等High/固定镜像。

## G2 Frontend P2 修复与增量 High 闭环

源提交b2e982d1848a768c7ff03bc77dcb0557883f24da，只AuthContext与races两文件；generation layout ref捕获/提交检查、最新refresh ref收尾，保留旧login epoch隔离。可靠分turn baseline red9PASS/1FAIL，/tmp/newshub-g2-front-review-repro-confirmed-red.log；整改15定向PASS/typecheck/lint0。独立High原P2closed、无新增P0/P1/P2，pre/post两physicalhash与scoped diff一致，摘要ab708b1f88d452e2ec40d9db325fe8e553f457db0d5c41f5f91b9cf8a97520a7，/tmp/newshub-g2-front-review-r1-{pre,post}.json。

主控新归档b2e982d（exclude用户DB/env，独立HOME）前端65文件454PASS/build0，/tmp/newshub-g2-front-r1-integrated-4cxjaflg/{test-run.log,build.log,report.json}。后端与先前8be4f9d的616PASS源完全相同，不重复后端全套。G2源码审查门槛已闭环；G2整体仍DOING：本地域名harness源码准备及真实账户browser/限速/owner验收尚未完成。G3仍未实施。

## G2 审核后正式镜像构建

纯G2业务源b2e982d1848a768c7ff03bc77dcb0557883f24da通过High后，以git archive排除backend/db.sqlite3*、统一源目录0755/文件0644或可执行0755构建未改Dockerfile production target，network host、RELEASE_SHA固定；退出0，9.585秒。镜像newshub:local-b2e982d1848a768c7ff03bc77dcb0557883f24da，ID sha256:313890d46a8fee650b2dd2b06759782d89ff158863ccacce452b3a8f95dea581，User10001:10001/revision准确。证据/tmp/newshub-g2-reviewed-build-_hykdser/{metadata.json,build.log,result.json}。无G3代码、无用户数据库或真实env写入镜像；本次build不是上线。

域名harness为宿主脚本，不COPY入生产image；账户验收将分别记录固定app SHA b2e982d及另行提交/审查的runner SHA。runner当前仍准备，实际G2 domain NOT_RUN。后续业务变更不得替换这份已冻结G2候选。

## G2 域名harness源码与High：六P2整改中

930cfddaf8ddbe3ae4660adf8788065de4e73884仅七harness文件，1936新增/86删除。初次36项与shell/mock/compile是在workingtree的临时HOME/绝对DB环境，未证明无dotenv读取，不能称archive隔离；随后固定930cfdd git archive排除DB/.env，env-i最小环境/独立HOME/绝对DB补证36PASS及shell/mock/compile0：/tmp/newshub-g2-archive930-evidence.PImrNY，pytest-env-i.log、env-i-proof.log、shell-syntax-exact.log、shell-mock.log、pycompile.log。早先工作树日志/tmp/newshub-g2-offline-evidence.3VFvqY仅保留为历史，不替代隔离证据。

独立High无P0/P1但六P2 BLOCK：async browser coroutine未await、GET null body、G2 fixture缺共享Mermaid、G2 SSE argv缺账户参数、真实app/gateway身份/自有DB mount未在凭据stdin前核验、sidecar超时按name删除无exactID台账。七physicalhash及scoped diff前后一致，706ea88c407d15eaefe52344db527e9c6129cf158e66852a8e2f002f853d4354；/tmp/newshub-g2-domain-audit-{pre,post}.json。已签发LOCAL-DOMAIN-G2-REVIEW-R1冻结六项修复与有意义回归，源码测试PASS不等于实际G2验收。实际domain仍NOT_RUN，固定app b2e982d镜像保持不变；G2整体DOING。

## 用户范围更新：取消AI费用平台

用户最新明确不要AI费用与用量控制，改以各用户自己的ChatGPT订阅使用。原G3费用/Site API代码未实施，旧五合同停止派发，TASKS标NOT_RUN（用户取消），不算完成代码。保留账户/凭据/缓存隔离、登录/注册安全限速、域名验收与现有长任务恢复，后者另立无费用专项合同。实际官网客户端/订阅授权仍缺，当前合法可做的NH-PUB-08骨架继续；不共享管理员订阅、不自动退回站点付费API。ADR-025为最新范围权威，原GOAL文件保持用户原文。官方文档核实路径见ADR-025。

被取消设计的独立High记录：1P1（收费启动标记必须先提交后网络IO）与4P2（多轮ceil报价、业务DTO、terminal事件容量、inactive后台fence）；五physicalhash前后一致/tmp/newshub-g3-design-review-{pre,post}.json。这不是代码验收，费用问题不再实施整改；恢复相关状态一致性在新专项中保留，不声称旧设计REVIEWED。

G2 harness R1源e45779bcd6644974b37c5d726df9b38b10285710，隔离64PASS及shell/Node真实JS/SSEargv/compile0，/tmp/newshub-local-domain-g2-r1-8tmbe_5y/validation-results.json。High原六项闭环四项，仍2P2：accept额外源码bind mount、start后CID file丢失可跳清理报成功；已签发LOCAL-DOMAIN-G2-REVIEW-R2。pre/post sevenhash一致/diff0d1c3b7d9ca5540274b01ac6f8636108abc15bf0c3db4fe38b008c81446f0992，/tmp/newshub-g2-domain-r1-{pre,post}.json。实际G2 domain仍NOT_RUN，固定app b2e982d不变。


## G2 harness R2 独立复审闭环

c59e6a507362ad281dbc5e7442bacf1c5bdbb8ba 五文件整改，隔离archive/env-i 77PASS及shell/mock/compile0，证据 /tmp/newshub-local-domain-g2-r2-final.ADvu26/。High两剩余P2closed、无新增P0/P1/P2，五physicalhash与scoped diff前后一致d11244b0740c2dcd7e2c3de340875b7216e2bcb6135abbc0baacf16c1230085b；/tmp/newshub-g2-domain-r2-{pre,post}.json。固定b2业务image与c59独立runner可派实际G2域名验收，未执行前仍NOT_RUN。NH-PUB-08按ADR025补充：迁移0029、当前session/user回调绑定、协议快照与模式禁网，绝不恢复费用平台。


## G2 首次实际运行：seed失败，未进入账户browser

固定runner c59/app b2与三个image通过核验，/tmp/newshub-g2-runtime.I9aZYI/。nginx-t/migrate/app-gateway启动PASS，21秒exit2，fixture seed失败；browser/accounts/TLS/SSE后续NOT_RUN，report目录为空（setup异常在main try外，临时stderr被trap删除）。精确随机project容器/网络/卷无残留cleanupPASS。主控定位rendered program缺DJANGO_SETTINGS_MODULE，image没有该ENV，start_waitress设置仅自身进程；env-i django.setup最小重现ImproperlyConfigured于LOGGING_CONFIG、尚无DB访问。签发R3仅fixture bootstrap和脱敏失败报告，实际第二次验收等源High。未读取用户DB/env或触9527/公网。


## NH-PUB-08 离线准备与并发测试诊断

Luna按完整合同实施mode禁网、attempt快照/0029、callback当前session/user与交换紧前fence、cookie及本地凭据清除；尚未提交/High。首轮75PASS/2FAIL分别测试session绑定fixture错和historical model读取当前字段，修正后77PASS。新增fence负例三项PASS；完整扩展轮86PASS/1FAIL是两线程一次消费测试，使用pytest共享内存SQLite（file:memorydb_default?mode=memory&cache=shared、uri=true、timeout30），出现table lock；原日志 /tmp/newshub-nhpub08-final.VZrf1u/acceptance-r3.log 与race-diagnostic2.log保留（后者1成功1OperationalError，非两成功）。权威真实文件子进程forward0029、两独立连接/FakeOAuth证实1成功1SubscriptionError且exchange1次/completed，standalone-race.log退出0。将主回归改为真实文件子进程，不skip或降低断言；最终事务首写CAS和仅存储busy安全503按主控冻结整改中，不能重试授权网络。公共middleware已有chatgpt_auth_disabled早期HTTP码保留，服务直接调用subscription_disabled码分测。无用户DB/.env/真实OAuth/付费调用。


## G2 seed R3 High闭环与第二次实际验收准备

bf24244七文件提交，隔离83PASS/bash/mock/compile/diff0；/tmp/newshub-g2-seed-r3-final-tqdmlm2h/。独立High无新增P0/P1/P2，七physicalhash及scoped diff前后一致2dc5c786ea246267ca868e094b3dd8da9e1994150e221d44ea46e4c8db19892a；/tmp/newshub-g2-seed-r3-{pre,post}.json。新runner固定bf24244、app仍b2精确ID；允许此次整改后仅一次真实重试，不把83单测算账户browserPASS。NH08最终隔离91PASS/三既有warnings及migration/compile/diff0，/tmp/newshub-nhpub08-final2.NIyOyr/，七业务源冻结独立High待审，真实OAuth/网站调用仍未运行。


## NH-PUB-08 首次High：目标删除P2整改

完整七源（含三新文件）独立High无P0/P1，但1P2 BLOCK：target_connection SET_NULL后callback跳过target分支并可重建已删除的重授权连接，交换前及保存前均有此竞态。pre/post七physicalhash及combined diff一致b1a9e39052709061e5f7bcedc157b6c37e2de96c7e5cbbe90b2d3e5dc53132a1，/tmp/newshub-nhpub08-review-{pre,post}.json。复用真实create target_attempt_generation>=1与new=0标识，exchange前和最终事务均拒绝positive generation且targetID为空；补删除在交换前0exchange/交换后1exchange但无新连接/凭据保存两回归。91PASS只源码证据，NH08仍DOING，不称REVIEWED。
