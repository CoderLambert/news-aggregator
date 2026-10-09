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
