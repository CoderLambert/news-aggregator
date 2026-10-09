# NewsHub 公网架构与 P00 决策

基线/当前 HEAD：`8c2823e1fcf8cbea38e9bb7c4e98a33232025fbd`（2026-10-10 fetch 后 origin/main 相同）。执行合同：根目录 GOAL.md。未发现仓库及父目录适用 AGENTS.md。用户已有 backend/db.sqlite3 改动禁止覆盖、迁移或提交。

## ADR-001：部署与阶段
保持 React/Vite、Django/DRF、Waitress、SQLite、Scrapy、Chroma 和单机 Docker Compose；Nginx 专属 news.lambert.host 虚拟主机提供版本化静态产物，/api/ 保留路径转发 127.0.0.1:9527。开发 compose.yaml 保留；生产独立 compose.prod.yaml。P00 → G1 → G2 → G3 → 条件 G4。公网写操作、付费 API、真实 OAuth 均未获授权。

## ADR-002：生产 fail-closed 与代理
新增 DJANGO_ENV=development|production，缺省 development 保留本地兼容；production 明确拒绝 DEBUG=1、任意 Host 和不稳定密钥。生产唯一 Host news.lambert.host，CSRF origin https://news.lambert.host；Cookie Host-only、Secure，Session HttpOnly，CSRF 可读。生产 CORS 禁止 allow-all。PUBLIC_SITE_MODE 默认 read_only；PUBLIC_SIGNUP_ENABLED、PUBLIC_AI_ENABLED、CHATGPT_PLAN_USAGE_ENABLED 默认 0；CHATGPT_AUTH_MODE 默认 disabled，website 在未批准前始终拒绝。
Waitress 清除不可信代理头，仅信任显式的单个 Nginx→容器来源 IP；实际源地址须隔离部署验证，禁止猜测或 trusted_proxy=*。Django 仅依据 Waitress 清洗后的 scheme 判定 HTTPS，禁止直接信任任意 X-Forwarded-Proto。HTTPS 强制跳转只允许精确 live/ready 探针路径豁免。

## ADR-003：G1 API 边界
服务端按解析后的 URL 名称及方法显式白名单，不允许所有 GET。read_only 对未放行的已知 API 返回 403 / public_read_only，在视图执行前拒绝；未知 API 保持 404。只允许 GET/HEAD news-list、news-detail、category-list、source-list、capabilities、health-live、health-ready、auth-csrf。news-list mode 仅 keyword；semantic/hybrid 返回 403 / semantic_search_disabled，不调用 embedding。HTTP 边界不干扰独立 crawler/indexer 命令。

| route names（backend/api/urls.py） | 既有身份边界 | G1 分类/处理 |
| --- | --- | --- |
| news-list/news-detail/category-list/source-list | 无显式权限（公开） | public_safe_read；仅 GET/HEAD，关键词检索 |
| news-chat (GET/POST/DELETE) | permission_classes=[]；news 唯一 ChatSession | blocked_in_read_only；G2 改 user+news |
| news-translate/news-suggested-questions/news-tts | 无显式权限；TTS GET 可调用网络 | blocked_in_read_only |
| news-fetch-full | IsAuthenticated | blocked_in_read_only |
| provider-comparison-list/detail/retest | IsAuthenticated，需进一步验证归属 | blocked_in_read_only |
| favorite-list/destroy/check、blocked-list/check | IsAuthenticated，user queryset | auth_private；G1 blocked_in_read_only |
| research-create/session-list/session-detail/chat/stream/results | IsAuthenticated，user queryset，CSRF 跳过 | auth_private；G1 blocked_in_read_only |
| chatgpt-subscription-* | 多数已登录；handoff/callback公开 | blocked_in_read_only；模式另加 fail-closed |
| crawler-admin-*、search-index-admin-* | IsActiveSuperuser | admin_only；G1 所有方法 blocked_in_read_only |
| auth-register/login/logout/me | register/login公开；logout/me已登录 | G1 blocked_in_read_only，G2 CSRF/限速 |
| auth-csrf | AllowAny | public_safe_read；必要 CSRF 初始化 |
| capabilities/health-live/health-ready（待添加） | 公开、无敏感详情 | public_safe_read |

## ADR-004：后续决策边界
G2 保留旧无主 ChatSession 为管理员隔离归档，禁止自动认领；迁移与 SQLite 并发协议需完整专项合同后实施。G3 必须替换公网 Coding Plan 端点；标准 API 明确授权、用户/IP/全站原子预算与任务持久租约需先冻结专项 ADR。已有 crawler_control、search index Worker、shared_translations 租约优先复用，禁止第二套通用平台。G4 只做合法 disabled/website fail-closed 骨架；正式批准前无真实订阅测试。

## 现有证据与风险
settings.py 默认 DEBUG=1/ALLOWED_HOSTS=*、CORS allow-all；start_waitress.py 会读取本机 Hermes Key；compose.yaml 挂载 backend 整目录，entrypoint 每个 Web 启动 migrate；Docker 已有 Node 构建阶段，但生产数据路径/非 root/受控迁移待验收。views.py Chat GET/DELETE 无归属；research_views.py 的 CsrfExemptSessionAuthentication 明确跳过 CSRF；llm_translator.py 两个端点均为 coding；MermaidBlock.tsx securityLevel=loose。测试必须使用测试数据库，禁止触碰当前运行数据。

## 测试环境
codex-cli 0.161.0，goals/multi_agent enabled；原生 spawn 工具已发现 implementer=gpt-6-luna/max 和 security_reviewer=gpt-6.1-sol/high，使用对应 role 而非提示词伪装。项目配置主模型 gpt-6.1-sol/medium；运行时主模型标识未提供查询接口，不能仅据 TOML 宣称已验证。子 Agent 禁止再派生。backend/venv/bin/python、frontend/node_modules 存在，Docker daemon 29.7.2 可用；dig/nginx 当前不在 PATH。
后端命令：PYTHONPATH=backend:crawler RUN_MAIN=true backend/venv/bin/python -m pytest tests/backend/ backend/api/tests/ tests/crawler/。前端命令：cd frontend && npm run typecheck && npm run lint && npm run test:run && npm run build。生产 check 使用无真实 Key 的隔离配置；Docker/Nginx smoke 用独立 project/端口/临时卷。

## ADR-005：NH-PUB-03 精确配置合同
DJANGO_ENV 枚举 development|production，development 为兼容默认；production 不加载工作树 .env，也不读 Hermes，避免隐式凭据。生产 DEBUG 默认0且禁止1；布尔仅0/1；Host固定news.lambert.host，CSRF trusted固定HTTPS origin。PUBLIC_SITE_MODE=read_only|full（生产默认read_only，开发full）；四个功能开关生产0，开发保留1；CHATGPT_AUTH_MODE=disabled|local_oss|website（生产disabled，开发local_oss），production禁止local_oss；website 保持 fail-closed 至08合同落实。SECRET_KEY生产必须显式配置、至少50字符/5种不同字符，拒绝dev-only-/django-insecure-前缀。WAITRESS_TRUSTED_PROXY生产必填单个合法IP，禁止*、网段、列表、主机名；开发无代理信任。可信头仅x-forwarded-proto/x-forwarded-for，count=1、clear_untrusted_proxy_headers=True。SECURE_PROXY_SSL_HEADER=None；WSGI scheme由Waitress改变，Django不二次接受原始头。HSTS3600秒，includeSubDomains/preload=False，仅本域试运行；check --deploy 的W005/W021为已解释的保护其他站点/避免未验证预加载策略，不消音。Session/CSRF Cookie Secure、Host-only；CSRF仍可由SPA读取。探针精确路径豁免HTTPS redirect；live不读DB，ready仅SELECT1，异常503 {status:unavailable}，不暴露异常。

## ADR-006：NH-PUB-05 精确门禁与能力协议
使用 Django process_view 中间件，按 resolver_match.url_name 在任何视图/DRF认证执行前判定；只处理 /api/ 已解析路由，不拦截管理命令，未知 /api/ 保持404。read_only只允许GET/HEAD白名单；其他已知路由一律403，error_code=public_read_only。news-list 的mode缺省或keyword通过；任何其他mode（即使无search）403/semantic_search_disabled。full模式仍独立检查signup、AI和ChatGPT开关；signup关闭403/signup_disabled；AI关闭时拦截 POST news-chat/news-translate/news-suggested-questions/research-create/research-chat、GET/HEAD news-tts 及provider-comparison-list POST/provider-comparison-retest POST（比较链可用付费抓取），403/ai_disabled；不因AI关闭拒绝个人历史GET/DELETE。ChatGPT全部route prefix在disabled下403/chatgpt_auth_disabled，website未获官方批准503/hosted_integration_unapproved；local_oss仅开发允许；plan usage为0时models及订阅推理不得访问上游，403/chatgpt_plan_usage_disabled。生产full时无AI授权仍0。
GET/HEAD capabilities输出 {site_mode, chatgpt_auth_mode, features}；features中 news、keyword_search、semantic_search、accounts、signup、favorites、blocked_news、chat_history、fetch_full、translation、chat、suggested_questions、tts、research、provider_comparisons、admin、chatgpt_subscription，每项{enabled:boolean,reason:null|固定error_code}；私有功能enabled仅表示站点功能开关，现有身份鉴权仍必须执行。read_only news/keyword_search true，其余false/public_read_only；full signup依signup flag，昂贵功能依AI flag，subscription依auth mode/usage与批准(website始终false)，其余true。admin enabled仅full时可用，不能透露登录管理员信息。响应Cache-Control:no-store；不泄露Key、provider endpoint、数据库路径或proxyIP；中文error消息与code统一。schema无需新增HTTP鉴权方式/数据库迁移。前端收到无法解析或请求失败的能力一律保守关闭私有功能。

## ADR-007：生产代理来源可验证的单机网络
Linux生产app使用network_mode:host，Waitress仅绑定127.0.0.1；宿主Nginx到API的来源因此在隔离集成测试中验证为127.0.0.1，不依赖Docker NAT网关猜测。WAITRESS_TRUSTED_PROXY仍必须显式配置，不自动信任任何来源；workers可用普通Compose网络且不映射端口。WAITRESS_PORT合法1..65535，默认9527；隔离本地smoke使用19527避开现有127.0.0.1:9527，真实模板上游仍9527。开发绑定0.0.0.0保持现有端口映射。生产SECRET还拒绝change-me/replace-me明显占位。此决定不修改宿主现有Nginx/9527服务。

## ADR-008：S05 不可信图表与抓取输送
前端Mermaid采用strict、htmlLabels=False，渲染后DOMPurify SVG profile再次净化；禁止foreignObject/script/iframe/object/embed/style/a/image/use及href/xlink:href/事件属性，不执行bindFunctions。最大图表输入20k字符、maxEdges=500，security配置不得被Mermaid directive覆盖；保留懒加载。DOMPurify使用已有锁文件版本3.4.7并声明直接依赖，不任意升级。Markdown明确skipHtml，维持react-markdown URL转换和noopener/noreferrer。
后端生产所有真实抓取使用同一有界、DNS解析后固定实际IP的HTTP/HTTPS GET输送。仅http/https，禁止凭据/控制字符/反斜线/zoneID与非80/443端口；解析全部地址均须全球可路由且非多播，每次重定向(最多3次)重做验证和IP固定；TLS按原host验证SNI/证书，Host仍原域名，忽略环境代理。单次总时限15秒、最大解压后2MiB，禁止压缩响应绕过上限(请求identity且拒绝非identity编码)；不直接信任DNS第一次检测后再由urlopen解析。Production Jina代理与Scrapy subprocess无法保证实际目标/每跳约束，明确返回unsafe_transport_disabled并从默认生产链剔除；GitHub/HN/RSS/直连保留。开发既有链可兼容，公众HTTP仅在生产模式验收；后续G3研究网页/翻译候选抓取同样必须使用安全输送，不能因为G1禁用就认为其最终安全。
