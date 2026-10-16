# 回滚、暂停与灾难恢复的执行合同

状态：待审核/未演练；本轮没有生产授权或数据操作。原main基线878b690不是已证明可读available的回滚目标。

## 兼容基点

现有rollback.sh要求数据库migration集合与目标manifest完全一致，release_manifest还会无条件启动crawler。T03必须扩展版本化角色/严格schema校验工具并实测，不能用“additive所以安全”放宽为任何旧migration子集。

T03不产出可上线回滚基点；T25完成所有旧入口fence后，由独立T36封存并验证。T26/T28以前必须取得T36真实SHA/digest/manifest。

默认选最后一个与当前库schema相同、能读available和新权限字段且保留owner fencing的过渡镜像作为回滚目标；记录SHA/digest/manifest/schema集合/测试证据。T05后原则上冻结DDL；后续新增DDL必须再建立受测兼容基点。计划中的目标占位不算可用恢复点。

## 分级动作

| 场景 | 首选动作 | 数据处理与限制 |
| --- | --- | --- |
| 新引擎/API故障 | 暂停相关操作/同步，缓存继续读 | 不清正文/译文、不恢复旧Spider |
| 单源质量/政策错误 | owner→paused，epoch递增并fence晚写 | 保存当前内容和候选；只暂停目标源 |
| 某任务应用缺陷 | 关新增入口或回退到已测兼容镜像 | 不reverse migration、不整库回放 |
| 来源切换失败 | 暂停新owner，保留新数据 | 旧支持来源经单独批准可回legacy；新Feed只能暂停 |
| 旧进程复活 | 立即停止继续迁移并停该入口 | 找出宿主cron/systemd/override实际根因，修复/重启验收 |
| schema/实例身份不符 | 关闭写入，停止自动恢复 | 独立ADR/恢复工单；禁止按数字ID猜绑定 |
| 存储损坏/灾难 | 单独批准两库恢复 | 明确恢复点/RPO和恢复点之后损失，不称零丢失 |

## 普通回滚步骤

1. 验证精确故障/受影响source_id、当前SHA/epoch、已批准目标兼容manifest；缺兼容证明即BLOCKED，先暂停。
2. 拒绝新控制请求；暂停相关sync/owner；排空或fence在途API/旧任务。涉及应用版本时停所有SQLite writer/任务线程并留当前一致性备份。
3. 检查目标schema/角色及config兼容，启动已验收过渡版。保留新增News、译文历史、用户关系与新表，不恢复数据库。
4. 校验列表/直接ID/搜索/AI/个人来源权限及available内容可读；核对owner及进度。继续使用Miniflux或保持paused，是否恢复旧调度需独立批准。
5. 固定本次SHA/manifest/工单/时刻/数据不变量和测试输出，后续开发依赖队列冻结直到批次重新通过。

发布者提取失败/未支持来源不能通过回滚改变已锁架构；临时回legacy只用于已批准迁移事故恢复，最终版本仍须删除旧体系。

## 灾难恢复步骤（另需批准）

1. 标明两个备份恢复点、manifest/版本/实例/映射hash、已知RPO。停止app写入口、所有legacy/新sync/indexer/channel-worker/后台线程及Miniflux写入。
2. 先验证SQLite snapshot sidecar、PG dump及受保护secret备份完整性；留当前目标库受控prior backup。禁止复制活动SQLite主文件忽略WAL。
3. 恢复对应版本的PG与NewsHub一致性快照；恢复顺序为数据服务但保持采集/同步关闭→校验两库身份→启动兼容app只读→校验绑定→开启sync对账→恢复获批写入口。
4. 不一致备份对不得直接开sync；引擎UUID/account/feed/entry核对不通过则阻塞，提交受控重绑定方案。
5. 全保留条目对账完成、用户FK/hash/权限/译文检验通过后恢复正常运行。保留期外且源Feed已滚动删除的记录不承诺补回。
6. 输出真实恢复耗时/RPO、缺口、批准、SHA和完整性证明。OPML仅订阅清单，不能替代正文/用户/研究双库备份。

禁止将down -v、全库覆盖、reverse migration或生产批量回填作为普通回滚默认动作。没有真实演练的backup/restore脚本不能放行迁移。
