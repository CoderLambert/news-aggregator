# 生产容器与静态发布

生产镜像使用 `Dockerfile` 的 `production` target。默认 target `development` 继续以 root 运行并使用 `/root/.cache/huggingface`，以兼容 `compose.yaml` 对工作树 `backend/` 的开发 bind mount。生产 target 则要求构建时提供与源码提交一致的 40 位十六进制 `RELEASE_SHA`，镜像标签记录在 `org.opencontainers.image.revision`；运行用户固定为 `10001:10001`，模型缓存位于 `/var/lib/newshub/model-cache`。

Docker build context 会由 `.dockerignore` 排除任意层级的 `.env`、证书和密钥、`auth.json`、数据库、`.runtime`、`.cache`、`logs`、日志文件及整个 `backend/media/`。不要用宽泛的 `token*` 规则过滤文件名，以免把正常源码排除。`tests/backend/test_docker_context.py` 用合成文件和 `FROM scratch` 实际构建临时上下文，检查这些文件没有进入镜像，同时确认普通 Python/前端源码仍在镜像内；该检查不会读取项目里的环境文件或数据库。

先创建 `.env.production`，用随机生成的 50 字符以上密钥替换空的 `DJANGO_SECRET_KEY`，填入经部署拓扑验证的 `WAITRESS_TRUSTED_PROXY` 和不可变 `NEWSHUB_IMAGE`。默认 `NEWSHUB_ENV_FILE=.env.production`；若环境文件存放在其他位置，把它改成绝对路径。生产 Compose 操作都显式传入同一个环境文件，不依赖仓库根目录 `.env`。

生产镜像必须按本次提交构建，再以同一个不可变引用运行：

```sh
RELEASE_SHA=$(git rev-parse HEAD)
NEWSHUB_IMAGE="newshub:${RELEASE_SHA}"
docker build --target production --build-arg "RELEASE_SHA=${RELEASE_SHA}" -t "$NEWSHUB_IMAGE" .
```

将 `NEWSHUB_IMAGE` 写入 `.env.production` 后，可先验证 Compose 配置：

```sh
docker compose --env-file .env.production -f compose.prod.yaml config --quiet
```

`docker compose up` 不能代替生产发布维护窗口：它不会核对当前镜像与旧 manifest、停止所有旧 worker 后为当前 schema 生成新快照，也不会等待新 app/worker 健康后再切换静态版本。生产首次部署和后续升级统一使用 `scripts/deploy/deploy.sh`；命令默认只验证并打印计划，审阅后才显式添加 `--execute`。已有数据必须提供当前与目标 manifest、匹配项目的数据库卷和全新备份输出路径：

```sh
scripts/deploy/deploy.sh \
  --env-file /secure/path/.env.production \
  --project newshub-site \
  --sha "$RELEASE_SHA" \
  --image "$NEWSHUB_IMAGE" \
  --root /srv/newshub \
  --manifest /secure/path/target-release.json \
  --current-manifest /secure/path/current-release.json \
  --db-volume newshub-site_db-data \
  --backup-output /secure/backups/newshub-before-release.sqlite3
```

首次空库只能使用同一脚本的 `--fresh` 路径；脚本必须确认项目没有旧 app/worker 容器且卷内尚无 `db.sqlite3`。直接运行 Compose 不能绕开这些检查。完整维护窗口顺序和失败恢复方式见 [`release-gates.md`](release-gates.md)。

`migrate` 是一次性服务，在 SQLite 所在目录创建独占非阻塞 flock，并持锁运行 `manage.py migrate --noinput`。应用和保留的 Worker 只有在迁移成功后才启动；索引与频道 Worker 还等待应用健康。生产应用入口不会自动迁移，开发入口仍保留原有自动迁移行为。新数据库只在专用持久卷中创建，不从 Git LFS 复制数据库。

生产 Compose 使用 host 网络，Waitress 只监听 `127.0.0.1:9527`。安全默认值为 `PUBLIC_SITE_MODE=read_only`、signup/AI/订阅及 indexer 自动任务关闭，认证模式为 `disabled`。这些值可在显式传给 Compose 的环境文件中配置；在 G2/G3 获批前不要设置 `full` 或开启相应开关。Compose 命令必须继续显式指定 `--env-file`，不会从仓库根目录 `.env` 自动读取这些策略值。索引 Worker 使用现有 `embedding_healthcheck` 检查心跳；缺少或过期的心跳会使对应容器变为 unhealthy。

发布清单 schema v4 显式记录 crawler、正文和频道 Worker 能力；新镜像的前两项为 false。兼容读取 v1–v3，但只有显式恢复历史能力清单时才加载 `compose.legacy-workers.prod.yaml`，默认部署不重启旧采集角色。`deploy.sh` 和 `rollback.sh` 只要在当前或目标清单中发现频道 Worker，就自动加载固定的 `compose.workspace.prod.yaml`：维护窗口会先停止 `channel-worker`，目标版本支持时再启动并等待其健康检查。无需也不得用发布脚本之外的临时 Compose 命令补启动该 Worker；回滚到确实不支持频道 Worker 的旧清单时只停止、不重启。

数据分别存放在数据库、Chroma、TTS、runtime、model-cache 与 logs 命名卷。容器不挂载源代码或宿主 `frontend/dist`；app 从显式 `.env.production` 读取应用配置，Worker 只接收必需的 Django 设置与密钥，不继承 Provider/OAuth 环境变量。

启用 RSS 的项目在 `deploy.sh` / `rollback.sh` 中还须显式添加 `--with-rss`，并在受保护的 `--env-file` 中设置 `NEWSHUB_RSS_IMAGE` 为独立构建、与目标应用同 SHA 的完整标签或 digest。脚本复用 `compose.rss.prod.yaml`，先核对 RSS 镜像 revision、非 root 用户和同步命令，以及同项目已运行且健康的 Miniflux；不负责创建或升级 Miniflux/PostgreSQL。未选择该参数却发现已有 `rss-sync` 容器时，在停止任何 writer 前退出，避免维护后漏恢复同步进程。选择后会恢复并检查 `rss-sync` 的独立镜像和健康状态，通过后才切换静态版本；失败则保持项目 writer 停止。回退若显式指定 `--worker-services`，必须包含 `rss-sync`，例如 `indexer,rss-sync`。引擎首次配置仍遵循 RSS T18，生产执行仍需批准窗口与恢复点。 两库恢复后若按 T03 只恢复应用读取，由 `recovery.py rollback` 显式传入 `--leave-rss-stopped` 和原 worker 子集；现有 RSS 容器必须已停止，不能与 `--with-rss` 混用。该路径不恢复 RSS/Miniflux，继续遵循恢复对账后再恢复同步的顺序。

静态导出助手默认只打印 dry-run 计划，不连接 Docker。生产发布流程由 `deploy.sh` 在当前数据库快照、迁移、app 与 worker health checks 全部通过后调用它。不要单独执行导出并切换生产静态版本。每个 release 只包含自己的真实静态文件与 asset 硬链接，公共目录/文件权限固定为目录 `0755`、文件 `0644`；共享旧资源不会进入其他 release 的摘要。同名资源内容不一致时拒绝覆盖。`current` 和 `previous` 通过同目录临时 symlink 原子替换，旧 release 不删除。

真实 Docker build 与隔离卷 smoke 属于阶段 B，须在阶段 A 提交并收到固定新 HEAD 后执行。阶段 B 使用独立 Compose project、专用命名卷和 `WAITRESS_PORT=19527`，不得占用宿主现有 9527 服务；生产镜像的 revision 必须对应该阶段固定 SHA。
