# 本地域名 HTTPS 验收

本地域名验收是后续开发的固定验收项。涉及代理、路由、账户、Cookie、CSRF 或 SSE 的改动，必须在对应功能完成后，通过 `news.lambert.host → HTTPS → Nginx → 前端/API` 的实际浏览器链路验证，再进入上线检查。单元测试、模板检查或脚本准备完成不能代替该项验收。

| 阶段 | 必须验证 | 当前状态 |
| --- | --- | --- |
| G1 只读站点 | 域名解析、证书信任与 SAN 负例、首页/深链接、缓存、只读权限、代理头、SSE 首帧 | 脚本与离线检查完成；实际隔离栈 NOT_RUN |
| G2 账户功能 | 登录/退出、会话生命周期、Secure/HttpOnly/Host-only Cookie、CSRF 写请求及拒绝负例、匿名和 A/B 用户隔离 | 待账户功能完成后扩展并执行；NOT_RUN |
| G3 任务功能 | 已登录任务创建、SSE 重连/取消、权限及配额失败；使用离线 Fake Provider | 待任务功能完成后扩展并执行；NOT_RUN |

每次实际验收保存源码 SHA、镜像 revision、命令退出码、浏览器报告/截图及资源清理结果。公网 DNS、真实证书签发、安全组和外网访问另在正式上线时验收；本地通过不能替代这些现场结果。

`local-domain-smoke.sh` 用 Docker 网络别名在本机验证正式主机名 `news.lambert.host`，不查询公网 DNS，也不修改 `/etc/hosts`、系统证书库、浏览器全局配置或服务器。默认调用是 dry-run；只有显式传入 `--execute` 才会检查并启动本地隔离栈。

阶段 A 的离线检查：

```sh
PYTHONPATH=backend:crawler RUN_MAIN=true backend/venv/bin/python -m pytest scripts/deploy/tests/test_nginx_templates.py -q
PYTHONPATH=backend:crawler RUN_MAIN=true backend/venv/bin/python -m pytest scripts/deploy/tests/test_local_domain_acceptance.py -q
bash -n scripts/deploy/local-domain-smoke.sh scripts/deploy/tests/test_local_domain_args.sh
bash scripts/deploy/tests/test_local_domain_args.sh
backend/venv/bin/python -m py_compile scripts/deploy/local_domain_acceptance.py
```

执行 G1 前，需要已构建且本地存在与源码 SHA 一致的 production image，以及本地 Nginx image。smoke 不会执行 `docker pull`。默认 Nginx image 是 `nginx:stable-alpine`，可用 `--nginx-image` 或 `NGINX_IMAGE` 选择已存在的镜像；若镜像缺失会返回 `NOT_RUN` 并提示显式预载。阶段 B/CI 可使用已经验证过的 `nginx@sha256:0985e772fb9f729e6fa0980da05fca5d9c468e870eed43071545afa9d2e27d94`，该测试镜像报告版本为 1.30.5。正式服务器版本须在发布现场单独运行 `nginx -t` 核验；本地镜像版本不代表服务器版本。

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

G2 登录、session 生命周期、已登录 CSRF 写操作和 A/B 用户隔离尚未实现，当前 `--stage g2` 固定返回 `NOT_RUN`，不得把 G1 结果表述成 G2 通过。阶段 B 尚未执行前，也不能把本地模板、镜像或域名链描述为生产验收通过。
