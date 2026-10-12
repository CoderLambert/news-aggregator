# G2 固定候选实际本地域名验收

- Task ID / Depends on / Base HEAD / Goal：LOCAL-DOMAIN-G2-RUNTIME；G2业务及harness High已闭环；runner 62cd633f9b2e1811999dd677c9b212f6835b013a，app b2e982d1848a768c7ff03bc77dcb0557883f24da。运行真实Docker/Nginx/TLS/Chromium账户验收，不修改源码。
- Owned files / Read-only references：仅新建独立0700 /tmp/newshub-g2-runtime-* 证据、HOME、TMPDIR及其随机owned Docker项目/volumes/network/精确container IDs；只读固定git archive的deploy scripts/模板、现有绝对venv Python、预加载image inspect。不是唯一工作者，不改工作树、不commit、不派生。
- Decision frozen：app必须 sha256:313890d46a8fee650b2dd2b06759782d89ff158863ccacce452b3a8f95dea581，User10001:10001/revision b2e982d；Nginx固定 nginx@sha256:0985e772fb9f729e6fa0980da05fca5d9c468e870eed43071545afa9d2e27d94；curl sha256:d9b4541e214bcd85196d6e92e2753ac6d0ea699f0af5741f8c6cccbfcf00ef4b。runner git archive 62cd633f9b2e1811999dd677c9b212f6835b013a排除backend/db.sqlite3*、**/.env*，模式0755可执行/目录0644普通文件。env -i PATH=/usr/bin:/bin HOME新私有目录 TMPDIR新私有目录 PYTHON_BIN=/home/lambert/githubRepos/lambert/news-aggregator/backend/venv/bin/python CHROMIUM_EXECUTABLE=/usr/bin/chromium LOCAL_DOMAIN_CURL_IMAGE=上述exactID。只用synthetic新DB/邀请/用户，不碰9527、用户DB、公网、系统hosts/CA/NSS或真实key。harness随机internal network/无宿主端口，浏览器私有CA/profile保持原严格校验。
- Implementation steps：1记录runner/app SHA与三个image inspect UID/revision/ID；2archive排除DB/env并生成source manifest；3env-i bash scripts/deploy/local-domain-smoke.sh --execute --stage g2 --image 上述appID --sha b2完整SHA --nginx-image 上述digest --chromium-executable /usr/bin/chromium，日志0600；4保留所有失败report，不跳case、不改脚本，失败返根因给主控；5核对report、browser截图/账户/真实IP限速/CSRF/Owner/SSE/TLS；6在自身project/ID清理后只读核对无残留，记录退出码/耗时/cleanup。
- Acceptance tests：真实G2矩阵全部PASS+exit0+cleanupPASS，A/B邀请注册、登录注销刷新缓存/延迟身份切换、匿名/普通/active与inactive管理员拒绝、owner private内容隔离、登录CSRF/邀请负例、真实来源IP限速及伪造XFF无绕过、CA信任/错误SAN/Host/static/深链/Mermaid/fake SSE全部按冻结脚本检查。无AI网络请求。截图可供主控人工检视。状态非全部PASS不得标整体PASS。
- Negative tests：保留invalid invite、跨用户/匿名、CSRF缺失、重复登录限速、forward spoof、untrustedCA/wrongSAN/恶意Host，不能用unit或fake echo冒充真实账户/IP验收。失败仍清理所有自建resources，无法确认cleanup明确FAIL。
- Forbidden：源码修改/pytest workingtree/读取或hash用户DB及env/真实订阅调用/收费/公网部署/DNS/系统CA/daemon/用户9527/宽泛Docker prune或按猜测name删容器。此前c59 seed失败、bf HTTP失败、928 logout屏障失败均已精确清理；此R5新候选最多执行一次完整验收，失败先报告，禁止自主修复/重试。
- Return format：runner/app/imageID、完整实际cmd/env/exit/耗时、0700 evidence与report路径、checks PASS/FAIL/NOT_RUN、截图路径、精确自建project/container/network/volume清理证据、失败根因，公网仍未上线。

- 预检须分镜像字段：app核验ID/User10001/revision，Nginx只ID/RepoDigests（不存在app User/revision字段不代表image不可用）；curl只ID/RepoDigests。源归档按tracked path list排除DB/env后才archive，不继承工作树0030准备。

- R5 logout 屏障三文件冻结哈希与审查前一致，97项隔离单测通过，High无P0/P1/P2；source commit 62cd633。当前本次runtime为NOT_RUN，不继承此前局部PASS为整体PASS。
