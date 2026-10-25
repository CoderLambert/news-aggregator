# CI 持久缓存生命周期

当前状态：本地实现与合成定向验证已完成；真实 Runner 卷、镜像构建、G1 和远端 CI 均未运行，等待用户本地验收后再进入远端交付。

阅读顺序：

1. [完整方案](完整方案.md)
2. [任务执行计划](任务执行计划.md)

目标是让首次 Runner 初始化、安装中断、普通重试和 Docker 构建都复用同一套可诊断缓存，并提供空闲态、定向、可预览的回收入口。

实现入口：

- `bash ops/ci/manage.sh cache-status`
- `bash ops/ci/manage.sh warm-cache`
- `bash ops/ci/manage.sh cache-gc`（默认 dry-run）
- `bash ops/ci/manage.sh cache-gc --execute`（空闲检查后执行）
