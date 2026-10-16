# T02：完成报告

日期：2026-10-16。实现 **READY_FOR_REVIEW**；隔离运行壳已实测，生产/同步 worker 为 NOT_RUN，不宣称 sync ready 或完整上线验收。

基线1c9e259ee6b149f8f0a7ad83a65338cddb6f8f9b，分支task/rss-T02-runtime，独占worktree `/tmp/newshub-rss-T02`。接口提交27a436c已推送，最终构建/Compose交付提交SHA由主调度记录真实Git回执；PR/CI/独立审查尚未执行。

| 专项 | 结果与实际证据 |
| --- | --- |
| T02-A1 PASS | rss-db无PortBindings，仅Miniflux加入PG内部网络；Miniflux API随机环回hostport，生产overlay默认127.0.0.1:18080；非管理员collector token验证成功 |
| T02-A2 PASS | 实际Docker构建跳过前端和重runtime-base阶段；镜像Python3.12.12/UID10001；重包/爬虫/Feed解析/浏览器/提取器模块与浏览器二进制缺失；MetaPath拦截证明Django及ORM未尝试embedding和URL导入 |
| T02-A3 配置/回归PASS，live NOT_RUN | 可选overlay/profile不替换旧app/crawler/indexer/channel-worker；app仍host/BYOK；现有deploy兼容回归通过。未重新构建/启动完整重镜像或现有服务，不冒充新一轮live全栈通过 |
| T02-A4 PASS | 全新项目独立named volumes/临时合成secrets，SQLite迁移至本次api0054；PG/engine/runtime健康；rss-sync只挂collector token和业务DB/runtime卷；PG/admin secret不挂sync；只读根/UID10001；第二进程flock拒绝；结束后容器/网络/卷全部移除 |

实现范围：独立rss-sync Docker target与固定依赖锁、可选compose.rss.prod.yaml、ApiConfig角色、rss_runtime管理命令/ORM shell、专项及实际镜像验证器。旧应用依赖文件、模型、迁移、主Compose和部署入口保持原样。同步请求/operation执行/目录定时调度由T08/T09接线。

接口：NEWSHUB_RUNTIME_ROLE=rss_sync；命令 `rss_runtime --once` / `--healthcheck` / 无参数前台；所有状态明确mode=orm_shell、sync_ready=false、worker_integrated=false。单SQLite目录锁防重复进程，20秒heartbeat只表示壳存活；管理命令跳过URL checks。四个固定配置值为RSS_ENGINE_INSTANCE_UUID、RSS_ENGINE_ACCOUNT_ID、RSS_ENGINE_BASE_URL、RSS_ENGINE_TOKEN_FILE，细节见 [README](../../../../../ops/rss/T02/README.md)。

实际命令/环境：

- Docker29.7.2/Compose5.5.1，Linuxamd64；主机测试Python3.14.8，镜像内真实Python3.12.12。
- `docker build --target rss-sync -t newshub-rss-t02:isolated-27a436c .` 退出0。实际镜像ID sha256:44b31d66e0d38f3bc6f8670abc27ef87d38dbd197a10f7dd375b6bde99f23718，Docker报告Size58168581字节；固定基础镜像digest在Dockerfile，PG/Miniflux复用T00固定digest。
- `python ops/rss/T02/verify_isolated.py --image newshub-rss-t02:isolated-27a436c --output ops/rss/T02/evidence.json` 退出0，项目newshub-rss-t02-dc695472a62e。真实包清单/schema/角色/清理结果见 [evidence.json](../../../../../ops/rss/T02/evidence.json)。
- T02专项与直接部署兼容回归组合65 passed in14.22s；随后加强独立进程测试，删除继承PYTEST_CURRENT_TEST干扰并确保缺heartbeat反例先建schema，最终T02专项5 passed in5.72s。另3项旧Dockerfile/Compose静态合同直接调用PASS。`git diff --check`退出0。
- 首轮隔离验证器误用token返回字段api_key，已按2.3.3官方模型修为token并复验；失败项目同样自动删除。没有输出/保存真实token值。

资源与限制：仅创建明确T02命名的镜像/项目，未读用户DB/生产secret或操作现有服务；两次项目容器/网络/卷已删除，测试镜像和build cache保留以供复审。T00真实API/90天created_at/refetch证据复用，不重复跑引擎合同。

现有deploy.sh不自动管理RSS可选profile；激活后必须由T03显式writer/manifest工具管理rss-sync与Miniflux的停写/配对备份，不能把旧单库流程当两库恢复保证。collector正式配置/账号初始化、引擎配置校验及并发上限2/短SQLite写事务要在T08/T09真正接线后验证；真实公网网关/SSRF完整门禁、最终集成schema与发布镜像、完整app/indexer/channel-worker新一轮live运行和负载资源门禁仍未验证。未执行任何生产启动、切源、部署或发布。
