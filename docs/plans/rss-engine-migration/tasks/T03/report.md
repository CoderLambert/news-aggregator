# T03：完成报告

日期2026-10-16。实现READY_FOR_REVIEW；隔离真实两库恢复与专项PASS。未执行生产，未封存应用兼容基点。

| 记录 | 结果 |
| --- | --- |
| 实现 SHA / PR / CI | task/rss-T03-recovery；基线1af2f2c，复用主调度0058迁移37b6e03为本地23b0826。仅最终T03提交需集成；SHA以Git回执为准。PR/CI未运行 |
| T03-A1 PASS | 真实PG custom dump与完整0058 SQLite online backup配对；覆盖、重复覆盖、空PG+缺失SQLite恢复均通过；专用非admin账号、feed/entry/URL映射、FK及用户关系保持 |
| T03-A2 PASS | 活跃writer、错engine UUID/schema/hash/prior真实拒绝且两库不变；专项另测未知schema3版本、错project/environment、额外容器、错PG image/API DB指向/SQLite挂载、PG发布端口、host PID重用 |
| T03-A3 PASS（工具路径） | 普通rollback只验证当前安全备份并委托现有rollback.sh；不调用任何DB restore。完整app镜像/静态/ACL兼容往返留T26，非本合成证据 |
| T03-A4 PASS | rollback.sh显式worker-services能力子集及空集合，RSS wrapper只选indexer/channel-worker；不自动启legacy/full-content/rss-sync/Miniflux。5种非法/不支持子集在Docker前拒绝 |
| 命令/结果 | tests.md专项与直接部署回归117 passed in8.36s，退出0；release shell回归PASS；bash -n、git diff --check通过；verify_isolated.py真实演练最终退出0 |
| 环境/证据 | Python3.12.14/Django6.1.2；Miniflux2.3.3/schema132、PG17.6固定digest复用T00。[实际证据](../../../../../ops/rss/T03/evidence.json)、[接口/复现/限制](../../../../../ops/rss/T03/README.md) |
| 实现评审 | 待主调度独立审查；未用作者测试代替恢复风险复核 |
| 未决门禁 | 证据严格到0058，不含随后0059数据迁移；T26须重测最终完整发布schema、受测候选app/static与ACL并封存。无生产副本不影响本合成工具交付，但真实恢复时长/RPO/大库与真实host调度停写尚未验证 |
| 资源/副作用 | 仅新建newshub-rss-t03-*项目、PG卷、临时SQLite/快照/转储/配置；最终57e0c68d02ee项目容器/网络/卷全部清空，临时工件随目录删除。无用户DB、现有服务或生产secret访问 |
| 生产批准/执行 | NOT_RUN；无发布、生产恢复、reverse migration、down-v既有资源或main合并 |

薄CLI默认dry-run，必须environment+target-project+完整allowlist，--execute才变更；--stop-writers仅停止显式六角色/host PID与systemd单元及Miniflux，保留PG供dump。备份输出0700，DB/PG archive/sidecar/pair与显式secret副本0600；secret不输出，也不自动覆盖部署引用。secret文件权限/拷贝有合成文件专项，live使用空secret引用，不宣称生产secret恢复通过。

灾难覆盖要求--replace+匹配两库当前内容的prior pair，fresh要求SQLite/sidecar缺失且目标PG没有public表。先验证hash/完整schema/身份、再PG单事务恢复、再复用SQLite原子替换；跨两库无分布式事务，任何后续失败保持writer停写并保留prior，不自动重启或猜实例。Miniflux保留期已删除的历史entry映射计数并保留本地News。

首次真实演练使用internal Docker网络时没有可达的loopback发布API，断言拒绝后自动清理；改为唯一隔离bridge、API仅127.0.0.1随机端口、PG无ports后通过。末次资源审计发现Compose不列出手动create但未start的fresh容器，已核对并删除其确切ID；harness补仅该ID清理和Docker project-label全量断言，最终重跑57e0c68d02ee项目后容器/卷/网络确实为空。六writer为显式合成sleep容器，真实app进程/宿主scheduler的行为不冒充已验证。最终实际恢复后FK、订阅/分组/收藏/已读/旧中文正文/译文归档/entry_map/幂等operation均核对。

开发完成、集成验收和生产放行分别记录。缺必需运行结果不能标 DONE；其他任务可依已审合同继续开发。详见 [task.md](task.md)、[tests.md](tests.md) 和 [全局验收矩阵](../../ACCEPTANCE-MATRIX.md)。
