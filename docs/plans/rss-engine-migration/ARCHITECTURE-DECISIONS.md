# RSS 引擎迁移的架构决议与冻结条件

状态：REVIEW_REQUIRED；固定架构方向已由用户指定，以下开发合同等待本规划PR审核。规划PR不授权产品实现或生产操作。

## 基线与效力

代码基线为 `878b69081f8d5b3ae965bcf1c855390b059caa33`，本轮git fetch与ls-remote结果一致。当前仓库及父目录未发现适用AGENTS.md/CLAUDE.md。原工作区为detached HEAD，修改的SQLite及两份未跟踪文档未纳入暂存。

用户确认将 `docs/NewsHub-RSS-Architecture-Final-2026-10-16.md` 原文复制为 [ARCHITECTURE.md](ARCHITECTURE.md)。该原文578行，保留审核历史；本轮用户要求的plans路径、详细任务及以下获确认ADR优先于原文第12节旧路径/粗粒度T00–T10。没有复制另一套技术架构。

事实以 [BASELINE-AUDIT.md](BASELINE-AUDIT.md)、[OPERATIONS-AUDIT.md](OPERATIONS-AUDIT.md)、[UPSTREAM-VERIFICATION.md](UPSTREAM-VERIFICATION.md) 为证；源码事实、合同提案和实际运行结果分开记录。Miniflux 2.3.3仅为静态审阅及待验证候选，未锁定运行版本或镜像digest。

## 独立 ADR

| ADR | 决策 | 状态 / 批准来源 |
| --- | --- | --- |
| [ADR-001](adrs/ADR-001-plan-authority.md) | 原文入库、plans目录及37项细分任务成为实施入口 | 用户确认原文；本轮明确指定路径；任务拆分待PR审核 |
| [ADR-002](adrs/ADR-002-ai-content-boundary.md) | 翻译/研究只读已保存正文；保留既有联网搜索，未收录网页显示摘要和链接 | 用户本轮Q1明确同意；实现仍待规划审核 |
| [ADR-003](adrs/ADR-003-personal-read-state.md) | ReadingDay保留，单独新增用户已读/未读，不推断回填 | 用户本轮Q2明确同意 |
| [ADR-004](adrs/ADR-004-shared-feed-mode.md) | 共享Feed采集模式由站点政策/管理员决定，V1无个人模式开关 | 用户本轮Q3明确同意；覆盖原文4.1“用户可关闭” |
| [ADR-005](adrs/ADR-005-url-provenance-conflicts.md) | 保留News.url唯一；身份/权限无法证明兼容的冲突隔离 | PROPOSED；待规划PR独立审核 |
| [ADR-006](adrs/ADR-006-compatible-rollback.md) | 兼容schema/manifest明确批准，不放宽成任意migration子集 | PROPOSED；待规划PR独立审核 |
| [ADR-007](adrs/ADR-007-entry-repair-api.md) | 官方SDK最小扩展持久单篇修复，普通刷新与修复分离 | PROPOSED；待T00运行验证和规划审核 |

ADR审核不是执行Agent自行改方向的许可。出现新冲突：独立ADR写问题、证据、受影响合同/任务、替代边界、迁移/安全/回滚影响和验收；主控审核，改变已确认产品语义时由用户决策，更新合同版本后才恢复依赖任务。

## 冻结闸门

G0：用户审核本规划PR，独立审查无P0/P1，技术ADR的设计边界及隔离验证方案获条件批准，C01–C11协议和任务写范围锁定。G0不要求尚未执行的T00运行结论；允许T00/T15/T24证据任务先进行。G1再冻结实际版本、transport可行性及运行参数；验证失败回到ADR而非擅自替代。只有通过G0才启动任务分支；当前均未启动。

G1：T00锁定上游运行合同、版本/digest/依赖及限制；T15确认目录格式/许可证。依赖运行字段的实现不得绕过G1。RSSHub是另一个可选放行闸门T01；失败不阻断native RSS，但保留RSSHub来源必须通过T18实际验收。

G2：T05独占本轮DDL，所有权/唯一键/状态/更新语义符合合同；之后任何新增schema先变更合同和DAG。所有已批准接口的行为由契约fixture固定，不能依赖执行Agent未来“补一个接口”。

G3：预生产真实来源、两库恢复、用户隔离和兼容回滚通过。G4：特定来源生产操作另有明确批准。G5：迁移及真实验收通过后才退出旧服务、删除代码；最终单栈回归后再批准最终生产发布。

接口冻结是审核状态，不等于代码已实现、来源已验证或生产已上线。
