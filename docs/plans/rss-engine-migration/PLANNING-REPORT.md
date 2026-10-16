# 规划修订、审核问题处理与验证记录

日期：2026-10-16。代码基线：878b69081f8d5b3ae965bcf1c855390b059caa33。被审核规划：514410b；关联 [PR #77](https://github.com/CoderLambert/news-aggregator/pull/77)。状态：修订后待审核，未开始产品实现。

## 本次范围

用户要求按上一轮“修改后批准”的意见修订对应文档和 PR。所有修改限定本规划目录；原工作区 backend/db.sqlite3 和两份未跟踪文档未纳入。没有读取业务行、修改产品、执行迁移/恢复/来源切换或合并 PR。

ARCHITECTURE.md 为用户确认原文，578 行、SHA256 a4614cd812d5e0d66a9211e88ecf72500513d0ccafce3aeb046633f2abee99e1，字节保持。原 T00–T36 保留引用，26 个有效单元、11 个合并索引；111 个任务文件仍存在，其中索引只跳转，不重复交付。

## 审核问题与修订

| 审核问题 | 对应修订 |
| --- | --- |
| 关联/读取/主写权及共享 Feed 切换不完整 | C02/C11、T05/T07/T09/T25：主写版本与来源 epoch 分离，旧正文接管不改 provenance，成员查询明确，共享旧来源按最小组切换 |
| history_only 混入可见性 | C02/DATA-MIGRATION：public/personal 不变，paused+原因表达停更 |
| 已有 Feed 无配置更新路径 | C03/C05/T04/T08：update_feed_policy、GET 核对、政策版本/旧操作失效 |
| 旧兼容字段译文可能丢失或错配 | C02/C04/T07/T14：LegacyTranslationSnapshot、替换前事务归档、当前 hash 校验和旧任务 CAS |
| 文章元数据职责遗漏 | C04/T09：source/category/title/summary/time/comments/索引及译文更新权表 |
| transport 过度建设 | ADR-007/C03：最小 SDK 参数扩展保留，取消通用 transport/精确取消框架；成熟 HTTP 和有证据的小型响应边界 |
| 人工 verified、固定阈值与通用测试过重 | C04/T06/T07/验收矩阵：unknown 可读，有限人工抽样，阈值可配，测试对应真实风险 |
| 重复审批与逐源三文件膨胀 | C09/C11/T29：已有部署授权+明确批次，统一来源 manifest/逐源结果，特殊情况才独立工单 |
| 全量 DDL 冻结及假依赖 | T05 只核心；领域 DDL 随功能，T03 不等 ACL、T14 不等 UI/对账、T25 合成开发提前 |
| 封存/恢复交付重复 | T26 合并 T36，候选先演练再封存；T29 生产前要求受测基点 |
| OPML 预览绑定尚未提交选择 | C05/T21：预览绑定 user/file/expiry，确认保存选择/组与幂等 hash |

旧事实审计保留代码/上游证据，并注明旧流程建议的版本效力。514410b 报告中的“三个独立 Agent 已通过”和旧静态计数仅属于旧规划历史，不是本次修订的独立复核；本次未启动子 Agent，不宣称已经获得新批准。

## 验证记录

修订静态校验已实际执行，退出码 0：26 个有效单元、11 个合并索引、111 个任务文件、44 条 DAG 边、553 个本地链接全部通过；依赖表/任务/图一致且无环，原文 hash、纯 Markdown 范围及 whitespace 检查通过。命令见 [VALIDATION.md](VALIDATION.md)，覆盖任务/别名/表/DAG、链接、原文 hash、纯 Markdown 范围和 whitespace。

产品测试、真实引擎/网关、数据副本迁移/恢复、浏览器、性能和生产操作全部 NOT_RUN。真实条件缺失按具体运行门禁标 BLOCKED，不能用文档检查替代。

修订前核对 514410b 的 [CI 运行 38876447321](https://github.com/CoderLambert/news-aggregator/actions/runs/38876447321)：frontend 通过；backend-and-release-gates 为 1792 passed、2 failed，均在 tests/crawler/test_crawl_all_serialization.py 经 runtime_registry 访问数据库时缺 pytest-django 数据库许可。本次不修改该既有代码/测试。新提交的 CI 另以 GitHub 实际结果为准，不继承旧 PASS/FAIL，也不预先称全部通过。既有保护 API 403 是旧审计事实，不推断目前没有保护、不绕过门禁；本次不合并 PR。

## 后续入口

规划复核后首组 T00/T06/T16，T05 尽早进入下一组；T24 缺副本不阻塞其他独立开发。按 [TASKS.md](TASKS.md) 区分开发、集成和上线；生产切源、恢复及发布仍需针对实际范围的授权。
