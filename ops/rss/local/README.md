# 本地 Docker RSSHub 通用接入

在原 NewsHub/Miniflux 项目追加本覆盖层；不用于生产。使用用户输入的通用 `rsshub://namespace/path?query`，无需为每个来源添加代码或逐条放行。普通原生HTTPS RSS仍按原流程。

通用层支持无参数路径、数字开头命名空间、中文和编码路径参数、常用查询参数。只拒绝结构错误、路径穿越、控制字符、地址凭据、服务端保留选项与非Feed服务端点。Twitter按用户要求保持暂停。路由是否存在、参数是否满足、是否需要认证、源站是否可用，由实际RSSHub/Miniflux结果决定。通用支持不代表上游所有路由均可用。

用户入口：`http://127.0.0.1:18080/channels`；本地调试入口：`http://127.0.0.1:1200`，由固定上游网关提供。浏览器只访问同域`/api/`，不需要用户登录Miniflux或配置RSSHub实例。

RSSHub只连接内部sandbox网络；强制通过专用Squid访问公网HTTP(S)80/443，无法直接出网。出口拒绝私有、回环、链路本地、元数据、保留/Fake-IP网段和IPv6字面地址。DNS使用固定AdGuard dnsproxy镜像，通过TLS校验开启的DoH获得实际A记录，避免本机Fake-IP环境。此配置不支持IPv6-only上游或非80/443端口。DNS/代理不开放宿主端口；不修改宿主机DNS、代理或防火墙。

Miniflux仍保留`FETCHER_ALLOW_PRIVATE_NETWORKS=0`，仅对RSSHub绑定使用原专用CONNECT代理，只允许精确TLS网关主机443。网关的Host、上游服务和认证转发规则不由用户输入决定；不转发Cookie/Authorization，拒绝上游30x。RSSHub没有服务Token、浏览器或Redis，未启用不安全域名开关。

运行前准备原有本地TLS证书和CA包，并设置Compose要求的配置/TLS目录、3个不冲突私有子网、DNS在sandbox/egress网络中的固定地址。将`egress.conf`中的`@RSSHUB_DNS_EGRESS_IP@`替换为该部署的DNS出口地址。本轮运行目录沿用原UAT目录，sandbox为10.203.27.32/28，DNS内部地址10.203.27.36、出口192.168.176.4。不要将此本机网段原样用于其他主机。

`gateway.json`启用generic模式；旧字段仅为保留已存在Feed13的旧准入哈希。新的命名空间不依赖旧字段白名单。新绑定按`generic_version`和暂停名单进行配置隔离，使用Feed-only/摘要策略与七天下界。源站认证与网站完整正文不是本次通用路由准入授予的权限。原公开推荐审核和个人分类独立保留。

回退配置、旧镜像及一致SQLite备份已保存在原本地UAT受保护目录；回退应同时恢复应用/Worker镜像与该覆盖层，暂停新通用绑定并保留其审计/数据，不删除卷或重建账号。运行版本和未完成验证见本轮交付记录。
