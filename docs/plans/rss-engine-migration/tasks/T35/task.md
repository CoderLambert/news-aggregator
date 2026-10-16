# T35：交付轻量同步运行时并验证无模型预加载

状态：PLANNED / 等待规划审核；未实现。目标合同：[INTERFACE-CONTRACTS.md](../../INTERFACE-CONTRACTS.md) C01、C03。架构目标：轻量运行及安全兼容回滚。

## 目标与技术方案

在任何worker运行验收前交付rss-sync独立轻量target及依赖锁，不继承含Torch/Scrapy的runtime-base。NEWSHUB_RUNTIME_ROLE=rss_sync仅启动ORM/SDK/转换所需模块，AppConfig不预加载embedding；服务默认不激活，T08命令实现后才运行worker。

范围：Dockerfile rss-sync target；独立锁依赖；AppConfig runtime-role；ops/rss同步profile。前置：[T00](../T00/task.md)、[T04](../T04/task.md)、[T05](../T05/task.md)。必须从已验收合并SHA建独立分支 `rss/t35`，不依未合并接口。资源锁：compose、dependency-manifest、runtime-config；共同文件串行，最多3项开发，不修改T05所有的DDL。

## 验收与阻塞

1. 实际构建镜像且包清单无Torch/embedding/Scrapy/feedparser/browser。
2. 隔离启动Django ORM及EngineAdapter，sys.modules/运行日志证明未加载模型。
3. 角色不继承BYOK或无关卷/凭据，数据库路径与lease实例配置正确。
4. 现有app/indexer/channel-worker照常加载其所需功能；T08可直接复用此镜像。

缺隔离镜像/实际运行证据即BLOCKED，不以单测或mock代替。先确认tests.md，独立审核无P0/P1、CI/PR/证据齐全再DONE。report.md填写真实SHA和输出；当前NOT_RUN。出现新合同问题先ADR审核。

回滚：停新增运行入口或使用已测兼容版本，保留数据；不reverse migration、不自动恢复生产库。详见[ROLLBACK.md](../../ROLLBACK.md)。
