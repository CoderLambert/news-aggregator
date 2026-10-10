# 本地域名 HTTPS 验收

本地域名验收是后续开发的固定验收项。涉及代理、路由、账户、Cookie、CSRF 或 SSE 的改动，必须在对应功能完成后，通过 `news.lambert.host → HTTPS → Nginx → 前端/API` 的实际浏览器链路验证，再进入上线检查。单元测试、模板检查或脚本准备完成不能代替该项验收。

| 阶段 | 必须验证 | 当前状态 |
| --- | --- | --- |
| G1 只读站点 | 域名解析、证书信任与 SAN 负例、首页/深链接、缓存、只读权限、代理头、SSE 首帧 | 候选 `91dc86b6a5dd212ea29d17f2692888be77e7b254` 的隔离 runtime 已通过；公网仍需上线现场验收 |
| G2 账户功能 | 登录/退出、会话生命周期、Secure/HttpOnly/Host-only Cookie、CSRF 写请求及拒绝负例、匿名和 A/B 用户隔离、管理员权限、真实源 IP 限速 | 固定 R4 candidate 的实际 runtime 为 FAIL：账户浏览器阶段的 logout 检查没有等待网络响应完成；后续 B/Owner/管理员/SSE 与限速检查为 NOT_RUN。R5 修复后的 harness 仍需 High 审查和新的完整 runtime 验收 |
| G3 任务功能 | 已登录任务创建、SSE 重连/取消、权限及配额失败；使用离线 Fake Provider | 不属于当前实现范围；NOT_RUN |

每次实际验收保存源码 SHA、镜像 revision、命令退出码、浏览器报告/截图及资源清理结果。公网 DNS、真实证书签发、安全组和外网访问另在正式上线时验收；本地通过不能替代这些现场结果。

`local-domain-smoke.sh` 用 Docker 网络别名在本机验证正式主机名 `news.lambert.host`，不查询公网 DNS，也不修改 `/etc/hosts`、系统证书库、浏览器全局配置或服务器。默认调用是 dry-run；只有显式传入 `--execute` 才会检查并启动本地隔离栈。Compose 在生成时把 app、migrate 和 gateway 镜像都固定到已 inspect 的 immutable image ID；静态导出和 fake SSE upstream 也使用 app image ID。JSON 报告同时保留用户选择的镜像 tag 与实际 image ID。

G1/G2 harness 的离线检查：

```sh
PYTHONPATH=backend:crawler RUN_MAIN=true backend/venv/bin/python -m pytest scripts/deploy/tests/test_nginx_templates.py -q
PYTHONPATH=backend:crawler RUN_MAIN=true backend/venv/bin/python -m pytest scripts/deploy/tests/test_local_domain_acceptance.py scripts/deploy/tests/test_local_domain_fixtures.py -q
bash -n scripts/deploy/local-domain-smoke.sh scripts/deploy/tests/test_local_domain_args.sh
bash scripts/deploy/tests/test_local_domain_args.sh
backend/venv/bin/python -m py_compile scripts/deploy/local_domain_acceptance.py scripts/deploy/local_domain_fixtures.py
```

执行 G1 或 G2 前，需要已构建且本地存在与源码 SHA 一致的 production image，以及本地 Nginx image。G2 还要求预载 `curlimages/curl:8.10.1`（可用 `LOCAL_DOMAIN_CURL_IMAGE` 指定已存在的镜像）。smoke 不会执行 `docker pull`。默认 Nginx image 是 `nginx:stable-alpine`，可用 `--nginx-image` 或 `NGINX_IMAGE` 选择已存在的镜像；若镜像缺失会返回 `NOT_RUN` 并提示显式预载。阶段 B/CI 可使用已经验证过的 `nginx@sha256:0985e772fb9f729e6fa0980da05fca5d9c468e870eed43071545afa9d2e27d94`，该测试镜像报告版本为 1.30.5。正式服务器版本须在发布现场单独运行 `nginx -t` 核验；本地镜像版本不代表服务器版本。

固定候选镜像 SHA 后，阶段 B 的 G1 命令为：

```sh
scripts/deploy/local-domain-smoke.sh \
  --execute \
  --image "newshub:local-${RELEASE_SHA}" \
  --sha "$RELEASE_SHA" \
  --stage g1 \
  --nginx-image nginx@sha256:0985e772fb9f729e6fa0980da05fca5d9c468e870eed43071545afa9d2e27d94
```

smoke 会核对 app image 的 `org.opencontainers.image.revision`，为临时栈生成一次性密钥、测试 CA 和 SAN 证书，并只在 Compose 的 internal network 中启动 Nginx 与 Waitress。app 与 gateway 共享隔离的 network namespace，Waitress 和 Nginx 都使用正式端口 `127.0.0.1:9527`；Compose 不发布宿主端口，因此不会占用宿主现有的 9527 服务，也不需要改写生产模板上游。不会接入 Provider。静态目录从指定镜像导出到新建临时根目录，数据库仅存在于该次 Compose project 的命名卷。

浏览器验收使用 `/usr/bin/chromium`、当前项目 `backend/venv` 中的 Playwright 1.62.0、`certutil` 和 fresh profile。若 Chromium 安装路径不同，可传 `--chromium-executable /绝对路径` 或设置 `CHROMIUM_EXECUTABLE`。浏览器先用无 CA 的 profile 验证证书会失败，再把临时 CA 导入单独的 smoke 专用 NSS 数据库后检查首页、新闻深链、只读能力、CSRF cookie、私有深链不调用 API，以及错误 SAN 被拒绝。新闻 fixture 的全文包含 Mermaid 流程图；浏览器检查 SVG 标签和节点/文字计算填充色，保存成功截图或失败截图以供复核。浏览器拦截发往正式 HTTPS 主机以外的请求；TLS 校验保持开启。

报告和可能的失败截图保存在经过验证的 `TMPDIR` 下新建的 `newshub-local-domain-report-*` 目录，不包含应用密钥。脚本退出时只删除它自己创建的 `newshub-local-domain.*` 工作目录、Compose project/命名卷和 fake SSE 容器；报告目录会保留以供检查。`TMPDIR` 必须是现存、绝对、非 `/` 且位于源码树之外的目录。脚本不接受 `--root`，未知参数会报错。

G1 包含 bootstrap 与 production Nginx `nginx -t`、ACME fixture/HTTP redirect、未知 Host 关闭、HTTPS 首页和深链、关键词搜索、API/cache/header 边界、缺失资源 404、旧哈希资源缓存、临时 CA 信任与 SAN 负例，以及用 fake upstream 验证准确 SSE 路径的首帧先于延迟终帧抵达。HTTPS 代理头负例会把伪造的 `X-Forwarded-Proto: http`、XFF 和 `Forwarded` 系列头送入真实 app 的 `/api/auth/csrf/` 非豁免路径，检查 HTTP 200（无 HTTPS 重定向）和 Secure、host-only CSRF cookie。独立的 fake SSE upstream 会回显它收到的 Host/转发头，以检查 Nginx 覆写协议与 XFF 并清除 `Forwarded`、`X-Forwarded-Host` 和 `X-Forwarded-Port`；这项 fake upstream 证据与真实 Django 请求分开记录。当前验收不读取 Django WSGI `REMOTE_ADDR`，客户端地址观测明确记为 `NOT_RUN`。

news 的 production 模板包含 HTTP 与 HTTPS 两个虚拟主机，bootstrap 模板只包含 HTTP 虚拟主机；它们都不声明 `default_server` 或全局拒绝站点，避免与已有站点争用 Nginx 的默认入口。每个 news 虚拟主机都大小写不敏感地校验实际 `Host` 头，只接受 `news.lambert.host` 以及显式标准端口 `:80` 或 `:443`；空 Host、未知主机、尾随点和其他端口都会被拒绝。校验同时覆盖绝对 URI 请求目标，避免请求目标中的域名掩盖恶意 `Host`。隔离验收会先加载一个模拟既有 Git HTTP/HTTPS 默认站点，再加载 news 配置，验证两组站点可共存且分别返回各自 fixture；这只证明模板在测试配置中的共存行为，不代表改动或验收了真实 Git 服务、全局 Nginx 配置或生产服务器。

浏览器/API/SSE 结果与 app revision、Nginx image ID、RepoDigest 和版本写入 JSON 报告；报告在清理完成后更新 `cleanup_status`。任一步失败都只清理该次任务的资源。

G2 harness 通过真实 UI 预期覆盖匿名私有路由、A/B 邀请注册与注销/刷新、会话和 CSRF Cookie、个人收藏/Chat/Research 权属、延迟 `auth/me` 响应、管理员激活/停用、登录与注册限速、伪造 XFF 负例。G2 每次把私密 fixture 程序送入容器前，都会从本次随机 Compose project 解析完整 app ID，并 inspect 它的 project/service labels、运行状态、image ID、UID:GID 10001 和**唯一**挂载：`/var/lib/newshub/db` 到 `<project>_db-data`。它还 inspect volume 本身，要求 `Driver=local`、`Scope=local`、无 driver options，且 Compose project/volume labels 精确匹配。任何额外的 app、backend、Python runtime 或其他挂载都会在 fixture stdin/exec 前拒绝。gateway 和 internal network 也会按精确 ID、标签、无 host port、namespace 与 `Internal=true` 校验。只有所有检查通过后才对 exact app ID 执行 `docker exec -i ... python -`。当前这些是已实现的验收路径，尚无 G2 实际 runtime 报告；必须等待固定 candidate 后运行 `--stage g2`，不能用离线检查代替。

G2 使用本次 smoke 私有的 0600 fixture bundle 和数据库。host runner 在 Django fixture 初始化前通过 Docker inspect 核对 app 的实际 immutable image ID；fixture helper 在 Django 初始化前核对随机 Compose project、revision 与 image-ID 格式、生产配置、UID 10001 和自有 `/var/lib/newshub/db/` 路径；只有空用户表允许 seed。helper 会拒绝继承到的非空且不匹配 `newsaggregator.settings` 的 `DJANGO_SETTINGS_MODULE`，再显式设置该 settings module 后调用 `django.setup()`。父身份检查和 seed 都写入 report root 内独立的 0600 `setup.json` / `seed.json`；失败只记录固定 check 名和白名单异常类型，不包含 fixture 程序、凭据、traceback、原始 stdout 或 stderr。shell trap 在没有最终 HTTP/SSE 报告时保留该阶段报告，并把失败或清理失败保持为整体 FAIL。A/B 由 SPA 真实邀请注册，个人数据通过一次性合成 owner fixture 附加。登录失败使用真实 `127.0.0.70` loopback 源地址；注册负例分配到 `127.0.0.61`–`127.0.0.65`，第六次请求再附加伪造 XFF 证明它不能绕过限速。每个限速侧车都先以 `docker create --pull=never` 创建并把完整 ID 写入私有 0600 CID ledger，inspect owner/image/user/gateway namespace 后才 `docker start --attach <ID>`；runner 将已核验 ID 保存在内存中，台账丢失或被替换会使验收失败，但 `finally` 仍只 inspect 并清理这个内存中的 exact ID。创建超时后若台账含可核验的自有 ID，会清理该 ID；无可核验 ID 时不按名称删除并记录 cleanup FAIL。侧车复用 gateway network namespace，限制为只读 root、非特权、宿主 UID:GID、内部网络和临时 CA；响应正文和 Cookie 留在私有目录，不写进报告。G2 SSE-only 子命令不需要也不接收账户 fixture 或 Compose 参数，仍执行独立 SSE 验收。

G2 浏览器退出登录检查会在点击前建立同源 `https://news.lambert.host/api/auth/logout/` 的 POST 响应等待，随后等待响应接收并完成，再要求 HTTP 200、登录头像消失、`/api/auth/me/` 返回 403 且浏览器上下文中没有 `sessionid`。非 200 或响应未完成会在 GET `/me/` 前失败；cookie 残留仍单独失败。失败报告只记录固定 browser subcheck、异常类型和受校验的期望/实际 HTTP 状态码，不记录异常文本或账户、邀请、Cookie 值。R4 的浏览器失败来自 harness 在本地 UI 清空后抢先检查会话；该报告不能据此认定业务 logout 接口有缺陷或通过验收。

执行期间保持 `umask 077`。只有公开 fixture 使用明确权限：ACME 目录链 `0755`、challenge 文件 `0644`、legacy asset 和无秘密 fake SSE 脚本 `0644`；smoke/private 根目录仍为 `0700`，fixture bundle、state、compose 环境文件和密钥仍为 `0600`。HTTP 状态断言失败时，G2 报告可记录固定格式的源 check 名及期望/实际整数状态码，不写响应正文、header 或异常文本；传输错误仍按失败处理。

G3 任务/worker 与 Fake Provider 不属于本轮实现，当前状态为 `NOT_RUN`。公网 DNS、真实证书签发、安全组和外网访问也仍需上线现场验收。
