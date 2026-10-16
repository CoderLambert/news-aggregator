# T08：完成报告

日期：2026-10-16。实现READY_FOR_REVIEW；T08专项与真实轻量容器/引擎最小控制集成PASS。完整同步和生产均NOT_RUN，sync_ready始终false。

| 记录 | 结果 |
| --- | --- |
| 实现 SHA / PR / CI | 基线21bbd10；分支task/rss-T08-operations；首个接口提交a331f94；最终SHA按主调度真实Git回执记录。PR/CI未执行 |
| T08-A1 PASS | 20线程/20actor同规范URL和同用户内幂等约束→唯一binding、唯一物理创建；本人操作视图隔离；实际引擎另跑20用户操作（串行入队）→1Feed |
| T08-A2 PASS | 故障注入丢响应只读核对，不见Feed也不重create；取消前不创建、取消中晚创建按最后引用/保留另一引用收敛；不删Feed或历史。未知结果5次后manual_blocked；editorial_pin仅miniflux owner可启动，legacy/paused预配置不采集 |
| T08-A3 PASS | 本地政策先递增并暂停，取消旧待修复；旧source/policy/body-owner/revision/失活用户不执行或不发布；正向BODY_POLICIES拒绝未知策略；引擎配置receipt确认后applied_version追上恢复 |
| T08-A4 PASS | 实际UPDATE claim/lease/token/epoch CAS拒绝旧lease；网络期间另一SQLite事务可写；阻塞控制仍有独立短读容量，各槽无backlog；lease过期不回收线程；进程级stall监督以75退出 |
| 实际命令 | tests.md专项+T02直接回归48 passed in12.56s，退出0；docker build rss-sync退出0；verify_live.py最终退出0；git diff --check退出0 |
| 环境/证据 | 主机专项Python3.12.14/Django6.1.2；实际轻量镜像Python3.12.12；Miniflux2.3.3/PG17.6及基础镜像复用T00/T02固定digest。[实际输出](../../../../../ops/rss/T08/evidence.json)与[说明](../../../../../ops/rss/T08/README.md) |
| 实现评审 | 待主调度/非作者审查；未以自身测试代替独立高风险复核 |
| 资源 | 仅新建newshub-rss-t08-*项目、合成PG/SQLite与测试CA/token。所有本次容器/网络/卷/临时secret已删除；测试镜像及build cache保留复审；未碰用户DB/现有服务 |
| 生产批准/执行 | NOT_RUN；未部署、切源、访问生产秘密或合并main |

真实引擎最终项目newshub-rss-t08-829dfd8e12b0，镜像sha256:d6ebb1e889d6bd4adea17d98ccd3c46c4c62900c8098bd26d9af474e66ed80b1。验证注册、最后引用disabled、双向mode政策核对、refresh、持久refetch后pending_sync且News不变，发现0/1/3及真实上游超时（unknown/upstream_http，不冒充无候选或成功）。实际rss_sync_worker前台daemon可探测，mode=control_worker但full sync未接线。最终owner修正后重新构建并重跑该隔离实验，容器/网络/卷检查均为空。

最小必要修正：真实2.3.3零发现候选为404，官方handler亦明确；T08只对discover的not_found转空候选成功，其他404仍错误。首轮测试发布者把未知path误回200，导致Miniflux常见Feed路径探测出额外候选，修为严格404和独立空主机后通过。测试失败项目均自动清理；fixture从未冒充真实发布者质量或公网安全证据。

下游接口：enqueue_operation返回FeedOperation，get_operation_for_actor返回受控result；safe_input.subscription原样保留。refetch_handoffs提供持久pending_sync，T09重GET并把safe_input.fence/intent_version送T07 CAS；acknowledge_refetch保留entry_id并记录明确sync_status、code/revision，不将引擎succeeded误报正文accepted。ControlWorker.tick/submit_short_read供T09同进程接入，所有DB写在调用线程、网络仅两个独立槽。

边界：只有显式rss_sync_worker或RSS_CONTROL_WORKER_ENABLED=1启用控制，未改Compose/默认T02壳。stall健康失败并不足以重启，runtime默认120秒os._exit(75)触发unless-stopped；远端不宣称已取消。unknown create缺唯一匹配、配置/修复读回不能证明结果时保留manual gate，其他actor/新幂等键不能绕过；解除需要受控诊断与远端静止/身份证据，没有盲清状态端点。T09仍需接入增量/对账、目录调度、读槽监督及正文handoff的实际CAS。生产网关/SSRF完整门禁、丢响应的真实网络故障注入、最终集成schema/发布镜像/负载仍未验证。

配置unknown的具体证据缺口：FeedDTO仅含crawler/disabled，不含blocklist_rules与keeplist_rules，两个flags匹配仍无法证明完整批准配置。T04原请求内可用原始GET逐项确认并返回PolicyReceipt；T08后续只有DTO，不扩SDK、不盲重发，5次只读仍无法证明则manual_blocked。专项覆盖set_enabled/update_feed_policy两种情况：远端flags已一致，仍只GET四次且仅首次update，不推进applied版本。editorial_pin仍独立于link.enabled，但必须owner=miniflux；六种owner/enabled组合确认旧owner绝不注册。

开发完成、集成验收和生产放行分别记录。缺必需运行结果不能标 DONE；其他任务可依已审合同继续开发。详见 [task.md](task.md)、[tests.md](tests.md) 和 [全局验收矩阵](../../ACCEPTANCE-MATRIX.md)。
