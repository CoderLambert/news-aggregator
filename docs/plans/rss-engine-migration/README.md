# NewsHub RSS 引擎迁移：合同、实现与验收入口

> 当前文档对应开发集成分支 [PR #78](https://github.com/CoderLambert/news-aggregator/pull/78)，不是生产发布记录。
> 规划合同来自 [PR #77](https://github.com/CoderLambert/news-aggregator/pull/77)，审计基线为 main@878b690。
> **唯一实时执行来源是 [EXECUTION-STATUS.md](EXECUTION-STATUS.md) 与各任务 report.md；[TASKS.md](TASKS.md) 是依赖/交付清单，不代表生产门禁已通过。**

## 已实现的开发候选

Miniflux 2.3.3 + PostgreSQL 17.6 的受控引擎、轻量同步进程、来源映射与权限隔离、正文转换/存储、关键词目录、网址发现、直接订阅、OPML、个人阅读状态、AI/TTS/research 读取及合成迁移/恢复工具已经进入 PR #78。

最新 PR #78 已有 2,401 个后端测试通过（16 个 opt-in live skipped），591 个前端测试通过；隔离 G1 smoke、完整镜像构建通过。测试的确切 SHA/工作流见 PR checks。**开发集成通过不等于真实来源/真实业务库验收或生产部署成功。**

## 尚未解除的发布阻塞

1. **自动网页全文：** `RSS_FULL_CONTENT_ENABLED=0` 必须保持生产默认关闭；Miniflux 转跳目标域名策略没有经公网受限环境验证。原生 RSS 内容仍可正常同步；不能把开启开关当成修复。
2. **RSSHub：** 本地模拟 TLS/认证/拒绝跳转测试通过，但真实 DNS/TLS、凭据、公共路由尚未验收。
3. **真实业务库：** T24/T26 尚无被授权的数据库一致性副本及完整 Docker 卷回滚链，不能进行线上迁移。
4. **真实正文质量：** Julia Evans 受测原生全文通过；Martin Fowler 的 Readability 提取缺失部分外围内容、顺序变化；Uber 样本失败；未核验来源没有整体成功率。
5. **退出旧栈：** T29/T30/T31/T33 的生产来源迁移、停旧服务、删旧代码、最终单栈发布尚未开始；不得提前进行。

## 阅读顺序

1. [设计权威](ARCHITECTURE.md)、[决议](ARCHITECTURE-DECISIONS.md)、[接口](INTERFACE-CONTRACTS.md)；
2. [当前执行状态](EXECUTION-STATUS.md)、[任务/依赖](TASKS.md)、[验收门禁](ACCEPTANCE-MATRIX.md)；
3. [来源与数据迁移](DATA-MIGRATION.md)、[备份/回滚](ROLLBACK.md)、[运维证据](OPERATIONS-AUDIT.md)；
4. [T18 网关](tasks/T18/report.md)、[T24 来源盘点](tasks/T24/report.md)、[T26 迁移恢复](tasks/T26/report.md)、[T27 浏览器及公网正文质量](tasks/T27/report.md)。

不允许以本目录中较早的「NOT_STARTED」「仅规划」历史文档覆盖新开发事实；也不允许将开发事实作为生产验收依据。原规划 PR #77 的历史记录保留原貌，执行后的状态以本分支为准。
