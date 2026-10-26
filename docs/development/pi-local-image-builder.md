# Pi 原生本地镜像代理

入口：`.pi/extensions/newshub-image-builder/index.ts`。这是 Pi 项目扩展，不依赖 OMP，也不注册宿主的 `delegate_task` 模板。固定 `openai-codex/gpt-6-luna`（不是其他 provider 的同名模型）及 `xhigh`；模型、授权或推理等级不可用时阻断，不自动降级。

## 加载与调用

从项目根目录启动已信任本项目的 Pi，或在现有 Pi 中执行 `/reload`。项目扩展是否加载由宿主的资源加载器及 trust 决定；文件存在不代表当前 Web 会话已经热加载。无需改全局 settings、安装包或复制 OMP 配置。

加载后，模型可调用 `newshub_image_builder`：

```json
{"action":"status"}
```

只有用户再次明确授权构建时，才能调用：

```json
{"action":"start","sha":"bfe2a6ad9331af0fbc5c7f7a26411079c8608cc1","authorized":true}
```

启动返回 `jobId`（结果中的 `id`），不是构建成功证据：

```json
{"action":"status","jobId":"<id>"}
{"action":"wait","jobId":"<id>","waitSeconds":30}
```

`wait` 最多等待 60 秒；超时返回真实的 `running`，可继续等待。取消等待不取消构建。终态为 `succeeded`、`blocked`、`failed` 或 `cancelled`。查询/等待同时返回有界 `diagnostics`：是否调用 `build_image`、安全的构建错误码/退出码、准备阶段及安全错误码/退出码、子 Agent 的 stop reason 与脱敏错误分类、取消/超时状态及是否取得镜像证据。provider 常见 HTTP/网络故障只返回固定分类，不回传任意原始文本。具体构建工具错误优先于模型的后续总结；provider 原始错误、URL、凭据和 prompt 不会返回。`succeeded` 仅表示私有 DinD 中的 builder image 已校验且代理正常终结；结果明确带有 `hostRuntime.status=transfer-required`，不表示宿主运行时镜像已就绪。

任务及独立上下文在当前 Pi 扩展会话内可查询；不是跨重启任务服务。关闭或 reload 会取消并等待本扩展的工作，随后丢弃内存记录。公共 Git 目录的 `newshub-pi-image-builder.lock` 阻止不同 Pi 会话/工作树重复构建；崩溃留下的锁不会自动抢占，需先人工确认没有运行中的构建。它不能约束不使用此锁的外部构建工具。

## 执行边界

- 代理只有一个无自定义参数的 `build_image` 工具，不继承父会话、shell、文件工具、MCP 或其他扩展。每项任务只允许一次构建尝试，最多四轮、30 分钟；未经实际构建验证不能以模型文字声称成功。
- 当前仅授权 `main@bfe2a6ad9331af0fbc5c7f7a26411079c8608cc1`，并验证该 SHA 是本地 `main` 历史的祖先；HEAD 可包含不改变已接受源码的配置提交。上下文始终从该 SHA 的安全 Git blob 导出，绝不以其他字节使用该标签。工作区 dirty 文件不混入镜像。文件名过滤发生在读取 blob **之前**；排除 SQLite/WAL、`.env`、密钥、媒体及 Agent 目录，拒绝符号链接。
- 按[构建合同](../../ops/ci/build-release-policy.md)保留本地开发兼容语义：使用 Dockerfile 的 `development` target，通过后置 `--label org.opencontainers.image.revision=<SHA>` 记录精确来源，标签为 `newshub:dev-<SHA>`。不改 Dockerfile、依赖或 cache ID。现有本地环境以 root 访问原数据及 `/root/.cache/huggingface`；误用 production/non-root 会破坏数据写权限和模型缓存复用。此选择仅适用于已接受的本地开发环境，不改变 production target 的非 root 发布门禁，也不修改用户数据/缓存的属主或权限。
- 只通过宿主 Docker 编排唯一命名的临时 client 容器；client 使用本地已校验 image ID 的 `docker:29-dind` 镜像、`--pull=never`、`--entrypoint docker`、UID 1001/GID 121、无额外 capabilities，以及无凭据的私有 `/tmp` tmpfs HOME/DOCKER_CONFIG。client 仅加入已验证的 `newshub-ci_default` 网络，并以只读方式挂载 sanitized context 与 Compose 标记匹配的 `newshub-ci_runner-socket` 到 `/ci-docker`。Docker CLI 的 `DOCKER_HOST` 只在 client 内指向该 socket；绝不挂宿主 daemon socket，也不在宿主 daemon 上构建。先检查 Compose project/service labels、DinD 健康状态、真实 volume/network/image 元数据，并用 `docker top` 确认两 Runner 均无 `Runner.Worker`；任何检查不完整即阻断。已有 DinD/Redis 等服务保持复用，容器存在本身不表示 Runner 忙碌；记录 `preservedBuilderContainers`，不停止、替换或删除这些服务。不会进入服务 Runner、挂载 Runner 注册/state/work 卷、创建替代 DinD 或改全局设置。
- 不启动应用容器、不运行 Compose、迁移、健康探测、部署或重启，不访问 `newshub-local-main` / `127.0.0.1:19527`，不读取真实 `.env` 或 `backend/db.sqlite3`，不推送镜像/Git、不触发 CI、不清缓存。构建任务会启动并清理其自有临时 Docker CLI client 容器；BuildKit 也可能运行内部构建容器，因此不声称“没有启动容器”。本地 builder image 仍在私有 DinD 中，宿主运行时 transfer 未实现，不会声称已就绪。
- 输出私有 builder image 的真实 image ID、digest（本地构建可能为空）、平台、revision、退出码及有限 BuildKit marker 计数，并明确 `hostRuntime.status=transfer-required`、`ready=false`。计数不代表下载缓存命中或性能提升。保留任务自己的临时源码上下文以便审查；client 清理只匹配本任务 UUID/label，不清理其他容器、镜像、网络或缓存。
- 复用 Pi 已配置的 provider 认证进行代理推理，不输出或复制认证；构建 client 仅获得最小环境、无凭据的私有 `/tmp` tmpfs HOME/DOCKER_CONFIG；宿主编排环境仍使用不存在的 HOME/DOCKER_CONFIG。构建本身仍可能访问公共 registry/软件源。扩展与 Dockerfile 不是 OS 沙箱，仅加载可信项目。

## 离线检查

既有 CI unittest 入口会发现 `ops/ci/tests/test_pi_image_builder.py`。使用 CI Node 22；不安装依赖，不调用模型或 Docker。离线回归直接覆盖 worker 注入边界、工具错误传播、provider/EOF/取消/超时及无证据失败：

```bash
node --test .pi/extensions/newshub-image-builder/tests/offline.test.mjs
python3 -m unittest discover -s ops/ci/tests -p 'test_pi_image_builder.py'
```

真实 Pi loader 的额外离线 smoke（传入本机已安装 SDK 的目录，不是 CLI 文件）：

```bash
node .pi/extensions/newshub-image-builder/tests/load-smoke.mjs /path/to/@earendil-works/pi-coding-agent
```

它只注册工具、查询状态并验证缺失模型时阻断，零推理、零镜像构建。离线回归覆盖 Compose/socket-volume discovery、client 参数隔离与 host-runtime transfer-required 状态，不证明真实 Docker 构建成功。本任务不启动构建、不改全局配置；回滚仅撤销本轮扩展实现、离线测试和本说明的对应变更，保留既有 OMP 任务及数据库改动。
