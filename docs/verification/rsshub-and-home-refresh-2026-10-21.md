# 本地 RSSHub 订阅与首页刷新验收记录

本轮交付为本地可用版本，Twitter 按用户要求跳过。未部署生产、未提交或推送 Git；此前未提交工作保留。

候选：隔离分支 `task/channel-recovery-20261021`，HEAD `887194ab1ad4bd2421e824045f5885a90622b73d` + 工作区改动；产品基线 `b03a3dfb41911b06dfb24c31074f4faf60fe8845`。运行镜像 `newshub:rsshub-2cc5a9fad61d`；源文件与镜像清单逐项匹配，具体文件摘要见 [candidate.json](rsshub-and-home-refresh-20261021/candidate.json)。不能把此脏工作区的本地结果等同于远端 SHA 的 CI。

## 本地实际结果

| 来源/功能 | 结果 | 实际证据 |
| --- | --- | --- |
| `rsshub://github/issue/DIYgod/RSSHub/open` | PASS | 真实 RSSHub → 原 Miniflux → Feed13 → 私人来源74 → 1篇最近七天内容；连接已完成 |
| 首页来源与分类 | PASS | 我的订阅显示新来源；`source=74&category=4` 显示1篇；个人分类“软件工程”，原文章分类保持“科技” |
| Twitter | SKIPPED | 用户明确要求先跳过；配置中没有 Twitter 路由或能力，没有请求真实 Twitter |
| 其他 RSSHub 模板 | NOT_ENABLED | 当前只开放已验收的公开 GitHub issue 模板与 DIYgod/RSSHub 仓库；不代表任意 RSSHub 路由都已支持 |
| 已有数据 | PASS | 一致 SQLite backup + integrity_check=ok；0078/0079迁移前后89张原表所有原字段/原行相同；旧11个Feed ID2–12保留 |
| 引擎身份 | PASS | 仍为 `3580d422-9b94-44db-a834-ca1255e00eb2`，账号2，没有重建数据库、账号或初始化已有内容 |

用户入口：`http://127.0.0.1:18080/channels` → 添加频道 → 粘贴上述别名 → 选择个人分类 → 确认。连接成功后即可私用；公开推荐另行审核。调试入口 `http://127.0.0.1:1200` 仅绑定回环地址。站点网关域名 `rsshub.newshub.example` 是 Docker 内部 TLS 服务名，不是公网实例地址。

本地项目 `newshub-local-uat` 增加 RSSHub、Nginx 网关与只允许单一 CONNECT 目标的 Squid。配置与部署说明位于 [ops/rss/local](../../ops/rss/local/README.md)。前端始终访问同域 `/api/`。原生 Feed 不获得 RSSHub 代理；Miniflux `FETCHER_ALLOW_PRIVATE_NETWORKS=0`，TLS 校验仍开启，CA仅挂载给引擎。

第一次本地真实连接遇到出口 DNS/IPv6 TLS 连接异常并超时，操作正确进入未知结果，没有循环重新创建。保留原错误，通过停止专用 Worker、重启同一 Miniflux 容器并记录先后时间的维护凭据，解决2条旧操作的阻塞；重新提交后 Feed13 真正连接成功。没有把旧操作改为成功，也未重置其尝试次数。旧操作与恢复依据留在数据库。当前绑定显示成功来自新操作最终响应。

Docker 默认地址池已耗尽；仅本项目使用独立子网，出口复用已经清理的专用测试网络所释放的网段。没有全局清理、修改 Docker 默认池或宿主代理设置。只在 RSSHub Node 命令上优先 IPv4 并关闭地址族自动选择，以绕开本机容器 IPv6 TLS 重置；未关闭证书校验。

## 验证范围

| 验证 | 结果 | 命令/范围 |
| --- | --- | --- |
| 后端定向回归 | PASS 732 | `sh .superpowers/sdd/2026-10-21-rss-self-service-and-review/pytest.sh backend/api/tests/rss backend/api/tests/test_channels.py backend/api/tests/test_smart_channel_workspace.py backend/api/tests/test_tts_endpoint.py scripts/deploy/tests/test_rss_channel_recovery.py`，Docker Python3.12，隔离SQLite，无网络 |
| 前端完整 Vitest | PASS 726 | Node22，`npm --prefix frontend run test:run` |
| 类型检查 | PASS | `npm --prefix frontend run typecheck` |
| lint | PASS，1条既有warning | `npm --prefix frontend run lint`，既有 `useSuggestedQuestions` warning未扩大 |
| 构建 | PASS | `npm --prefix frontend run build`；运行清单确认当前前端产物匹配交付镜像 |
| 迁移图/格式 | PASS | 候选镜像 `manage.py makemigrations --check --dry-run` 返回No changes；`git diff --check` |
| 真实隔离引擎 | PASS | 固定RSSHub镜像 + Miniflux2.3.3 + 临时PostgreSQL/SQLite/合成账号；[原始结果](rsshub-and-home-refresh-20261021/isolated-real-result.json) |
| 真实本地站点 | PASS | 浏览器实际提交，Feed13/来源74/1篇文章；保留现有站点、账号和数据 |
| CI / 完整后端仓库套件 / 生产 | NOT_RUN | 本轮没有推送或触发远端CI；732条只代表列明的定向范围 |

隔离验收覆盖别名与HTTPS复用1个Feed、七天下界、私人内容不可被其他用户看到、个人分类隔离、Feed-only策略，以及四个安全负例。负例严格检查 Miniflux `ServerError` 的具体原因：原生内网为 `refusing to access private network host`；代理其他主机为Forbidden；网关未开放路径403；上游跳转502。超时或认证失败不计为安全拒绝。上游跳转另有精确HTTP502检查。

前一轮功能最终复核为Critical0/Important3，三项均已回归修复：HTTPS网关本地识别、配置撤销后已确认的暂停结果提交、筛选状态下行消失仍刷新首页。另修复非文章路由策略与新绑定七天下界。此次新增本地网络配置单独复核，Critical0/Important0；其关于负例宽泛异常可能假阳性的Minor意见已通过上述严格错误断言修复并重新完成真实隔离验收。没有反复复核同一旧范围。

原始日志：[后端](rsshub-and-home-refresh-20261021/backend-local-final.log) · [前端](rsshub-and-home-refresh-20261021/frontend-delivery.log) · [类型](rsshub-and-home-refresh-20261021/typecheck-final2.log) · [构建](rsshub-and-home-refresh-20261021/build-final.log) · [本地服务状态](rsshub-and-home-refresh-20261021/local-runtime.json)。前端环境有既有 `Window.scrollTo` 未实现提示，测试退出码0；不将其当作真实浏览器结论。

## 浏览器结果

- 桌面：实际添加别名、选择个人分类、连接成功、来源立即出现在首页，组合筛选显示真实文章。
- 窄屏：实际CSS视口412px，页面文档393px（滚动条除外），无横向溢出；添加对话框可完成，首页来源筛选可用。浏览器临时尺寸已恢复。
- 键盘：Escape关闭添加窗口，焦点回到“添加频道”。
- 合成账号切换：B将个人分类改为医疗健康，退出后A仍显示人工智能；真实用户会话没有被退出。
- 冷却倒计时/迟到响应/筛选行消失由自动化回归覆盖；本次未另制造浏览器冷却失败场景。

[桌面实际结果](rsshub-and-home-refresh-20261021/local-home-desktop.png) · [412px添加](rsshub-and-home-refresh-20261021/local-add-412.png) · [412px连接成功](rsshub-and-home-refresh-20261021/local-connected-412.png) · [412px首页](rsshub-and-home-refresh-20261021/local-home-412.png) · [账号切换](rsshub-and-home-refresh-20261021/isolated-account-a-category.png)。

## 回退与限制

已保留升级前镜像 `newshub:rss-self-service-66246c23b204`，以及受保护卷中的一致备份。回退先关闭新恢复入口/暂停相应RSSHub采集，再将应用与Worker一起切回旧镜像；保留新增迁移和审计数据，不删数据库或卷。当前本地配置存放于原UAT运行目录，以新增覆盖层追加，不改写旧覆盖层；TLS私钥不入仓库。

RSSHub依赖上游可用性，公开GitHub API可能限流；不可声称任意来源均可连接。Twitter和其他需要认证或额外审查的路由未启用。只交付本地服务，没有公网DNS/TLS或生产发布。两组具名隔离测试服务已清理，正式本地RSSHub及应用、引擎、Worker继续运行。
