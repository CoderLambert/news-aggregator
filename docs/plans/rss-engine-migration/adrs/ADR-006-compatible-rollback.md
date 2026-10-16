# ADR-006：以受测兼容 schema 和角色定义回滚

状态：PROPOSED，待本规划PR独立审核及T03真实演练。

## 问题与证据

现有rollback要求migration exact-match，manifest无RSS角色且会启动crawler；additive并不能证明旧镜像可回滚。

证据：[BASELINE-AUDIT.md](../BASELINE-AUDIT.md)、[OPERATIONS-AUDIT.md](../OPERATIONS-AUDIT.md)、[UPSTREAM-VERIFICATION.md](../UPSTREAM-VERIFICATION.md)。原始方向见[ARCHITECTURE.md](../ARCHITECTURE.md)，不改变Miniflux/PG/RSSHub分工。

## 决议与影响

T05集中DDL；T03只扩展工具/严格版本化角色，不产出可用回滚SHA。T25完整旧入口fence完成后，T36封存同schema、能读available/新ACL/fence的过渡镜像并实测；T26必须依赖T36。禁止把旧迁移集合子集当兼容证明。

回滚保留新数据/新表；普通回滚只回应用与owner，不做全库恢复。未来DDL重新批准兼容基点。

## 验收与回滚

故障回滚/恢复真实演练；schema不符拒绝、writer失败关闭、不会复活旧进程；旧main基线不自动成为回滚点。

对应任务与合同见[ARCHITECTURE-DECISIONS.md](../ARCHITECTURE-DECISIONS.md)、[INTERFACE-CONTRACTS.md](../INTERFACE-CONTRACTS.md)。任何新的架构变更须另立ADR审核；本ADR不授予生产修改、数据删除或批量回填权限。
