# 规划 PR 的证据、审核结论与未决门禁

日期：2026-10-16。审计代码基线：`878b69081f8d5b3ae965bcf1c855390b059caa33`。交付状态：规划待用户审核；没有进入连续开发。

## 交付与范围

按用户确认原文新增ARCHITECTURE.md（578行，SHA256 `a4614cd812d5e0d66a9211e88ecf72500513d0ccafce3aeb046633f2abee99e1`），以及七份核心合同、三份证据审计、七份独立ADR、37项主任务的111份task/tests/report、逐来源工单模板及校验说明。T29是汇总门禁，实际N份单源工单必须T24在授权副本盘点后生成并另行审核；最终37+N，不猜测生产来源数量。

所有改动位于docs/plans/rss-engine-migration/。原工作区本地SQLite与未跟踪文件未暂存；本轮不修改产品功能、模型、迁移、线上配置，不执行数据回填/来源切换。规划文档提交SHA/PR以本分支Git历史及关联PR元数据为准，避免自引用SHA。

## 已执行证据与静态校验

git fetch origin、status、rev-parse origin/main和ls-remote核实基线；git/源码/CI定义和官方上游资料已读取。原文cmp字节一致。完整可重复检查命令见[VALIDATION.md](VALIDATION.md)：任务数量和文件、依赖表/各任务/图的一致性与无环、全部本地链接和C01–C11锚点、架构hash、纯Markdown范围、diff whitespace。实际执行退出码0，37个主节点、111份任务文档、369个本地链接通过，依赖无环且表/图/任务一致；G0后初始队列为T00/T15/T24。静态校验PASS不覆盖任何产品运行门禁。

GitHub保护与rules查询实际HTTP403，不能确认必需检查/保护配置；没有更改或绕过它们。关联PR的CI状态以GitHub当前结果为准，未完成时不称已通过。

## 独立审核与修复

三个独立审核Agent分别检查数据/用户兼容、部署回滚、上游契约。首轮未通过，发现的规划P1已全部修复后复核通过：

| 问题 | 实际修复 | 复核 |
| --- | --- | --- |
| 私网防护措辞反向 | 明确FETCHER_ALLOW_PRIVATE_NETWORKS=0，禁止私网访问且防护启用 | 数据/运维/上游通过 |
| G0要求T00运行结果导致闭环 | G0条件批准验证方案，G1冻结运行字段 | 数据/上游通过 |
| 轻量runtime拖到迁移后 | 新增T35，T08前置该任务 | 运维通过 |
| 回滚fence隐含循环 | T03仅工具，T25后新增T36封存，T26依赖T36 | 数据/运维通过 |
| 运维CLI/多候选选择未定义 | C09完整签名及拒绝语义，逐候选user-bound token | 数据/运维通过 |
| SDK总期限/响应预算与H入口缺失 | 受限transport、绝对deadline、wire/decoded预算、read_upper_bound | 上游通过 |
| 网关凭据范围/超限恢复不完整 | 精确origin/route禁跳转；身份不明时保留cursor并BLOCKED | 上游通过 |

审核身份：audit_data、audit_operations、verify_upstream；它们未编写主控七份合同和任务设计，独立检查后报告修复关闭。它们分别编写过对应的事实审计文档；本轮复核结论仅针对规划一致性，不是产品代码独立审核或实际验收。

## 未通过的实际门禁

T00/T01真实引擎/安全/网关、T24实际数据副本盘点、T26/T27迁移与浏览器、T33资源/最终回归均未运行。网关DNS/证书/公网回流、GitHub路由Token、实际源可用性/字段、版本/digest和模型状态须实测。产品报告全部NOT_STARTED/NOT_RUN，所需环境缺失标BLOCKED。

生产迁移/批量回填/来源切换/宿主停运/数据恢复/最终发布均没有本轮授权；须精确工单批准。本PR只供规划审核，不合并、不执行后续开发。

## 建议队列

规划审核后：T00/T15/T24（证据）；T00验收后：T02/T04/T06首组实现候选。最多3项，公共schema/文件严格串行。T05统一DDL，T35轻量runtime在worker前，T36完整fence兼容基点在迁移演练前。详细图见[DEPENDENCIES.md](DEPENDENCIES.md)。
