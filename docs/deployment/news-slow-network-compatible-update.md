# 新闻列表慢网：部署兼容修复与更新草案

本兼容分支以精确部署提交 `34bbe2b0f101a9c8423d66a5e296c223fc1d7d52` 为基线，仅移植已审核 `cd3d3329b479f69909611c915478286503787d4b` 与 `9cae3c82be7d64db3b9f73e087a8b7291bbfcceb` 的慢网修复语义。不能在服务器切换到main：核查时main为 `f32aafacecffc39dde89a37f3b76162276142d90`，与部署线共祖8c2823e1，相对部署ahead3/behind151。

分支：`fix/news-deployment-slow-network`。基线远端分支为 `fix/news-g2-shared-browser-diagnostics`，创建前核实其SHA精确等于34bbe2b0。使用本次审核提供的固定完整HEAD更新，不跟随浮动main或其他BYOK分支。

## 范围与兼容性

- 默认 `/api/news/` 与显式 `representation=summary` 只返回summary/summary_zh，各最多300个Unicode字符，不包含content/content_zh/full_content/full_content_zh。其他representation返回400；完整正文继续通过详情获取。所有前端列表入口迁移到摘要，详情类型/解析与列表缓存分离。
- 列表view仅允许JSONRenderer，匿名/合成会话的Accept:text/html返回406 JSON，format=api返回404 JSON；本地Nginx四项探针均不返回/压缩HTML，未泄露CSRF模板或用户名。原gzip_types不能禁用默认text/html，因此这是已修正的范围缺陷，未证明可利用攻击；全局renderer、详情renderer与鉴权未改。
- 列表请求单独30秒，其他请求时限与取消保持原行为。仅精确 `/api/news/` 开启JSON gzip，其余API不继承压缩；SSE设置、反代头、缓存头不变。
- 采用局部hunk移植，保留NewsCard屏蔽能力开关、LocalSearch语义能力开关、api.ts能力解析器和views.py既有认证/聊天/SSE行为。Django已有ValidationError仍用于注册校验，新增DRF异常明确命名ApiValidationError。
- Dockerfile、production target、compose.prod.yaml、入口/迁移脚本、发布/备份/回滚/manifest脚本不变。33个api迁移文件（含__init__.py）与34bbe2b0逐字节一致，保留0032_research_queued_input；没有新增迁移。
- 数据库查询仍读取正文后在serializer截断，本修复减少网络响应载荷；没有引入逐条详情请求或N+1。

## 本地验证

- 193项适用后端/配置回归通过，包括31项摘要测试（含部署read-only默认摘要/详情及AI屏障）、搜索、公共策略、生产配置、账号安全、聊天/迁移、全文、翻译/SSE、数据路径和发布manifest契约。3条既有警告（依赖弃用与Category/Source分页顺序）。
- 前端66文件469项通过，typecheck/lint/build通过。
- 原发布/回滚/备份脚本、静态导出、local-domain参数测试通过，Docker/curl/browser等均替身；没有连接Docker daemon或修改任何现有容器。
- 使用合成值的production `manage.py check --deploy` 成功，有既有HSTS子域和preload两条警告，未改全域TLS策略。
- 临时SQLite已应用完整迁移至0032，makemigrations --check --dry-run无模型变更。普通列表1条/20条均2次查询，语义2次、混合3次（索引/向量替身，无模型调用）。
- 独立用户态Nginx1.28.0在随机loopback端口测试受管配置；nginx -t、gzip头、Vary/no-store、解压一致及详情/模拟SSE/模拟私有JSON不压缩均通过。
- 20篇大量重复英文/中文合成文章：旧正文重建载荷513,599字节 → 默认摘要37,599字节 → 实际gzip1,152字节。压缩率不代表真实新闻。
- 20,480 bytes/s、100ms latency真实Axios/Vite/Nginx/Django：旧正文替身10.001秒超时；默认摘要10秒identity客户端1.935秒成功；前端30秒摘要identity 1.976秒、gzip0.219秒；额外12秒上游延迟12.157秒成功。
- 测试启动前显式设置PYTEST_CURRENT_TEST、NEWS_CRAWL_ONLY=1、RUN_MAIN=true与HF_HUB_OFFLINE=1/TRANSFORMERS_OFFLINE=1；慢网脚本在django.setup前禁止EmbeddingService.preload、model属性与encode调用，启动/结束均断言零调用。此兼容任务没有加载模型、调用真实模型或读取用户Key。
- 首轮浏览器harness入口超时，清理后复跑通过；没有作为成功结果计入。最终机器可读证据：verification/news-slow-network-compatible.json。

NOT_RUN：腾讯/SSH/生产URL、真实生产镜像构建与Docker容器运行、完整后端套件、生产文章压缩率、生产证书/配置、完整SPA在慢网下的冷启动。现有端口5173/9528/9527/4000、BYOK预览、tmux和Docker网关均未改动。以下服务器命令只是供主线程审核的草案，本任务未执行。

## 先由用户做最小只读核对

在服务器已有终端执行。第一条列出app候选，然后把确认的NewsHub容器ID填入NEWS_EXISTING_APP_ID；不遍历或打印容器Env，不读取Provider Key。

```sh
docker ps --filter label=com.docker.compose.service=app --format 'table {{.ID}}\t{{.Names}}'
: "${NEWS_EXISTING_APP_ID:?填入确认的NewsHub app容器ID}"
docker inspect --format '{"name":{{json .Name}},"image":{{json .Config.Image}},"revision":{{json (index .Config.Labels "org.opencontainers.image.revision")}},"project":{{json (index .Config.Labels "com.docker.compose.project")}},"working_dir":{{json (index .Config.Labels "com.docker.compose.project.working_dir")}},"compose_files":{{json (index .Config.Labels "com.docker.compose.project.config_files")}},"env_file_label":{{json (index .Config.Labels "com.docker.compose.project.environment_file")}},"mounts":{{json .Mounts}}}' "$NEWS_EXISTING_APP_ID"
sudo nginx -T 2>/dev/null | sed -nE '/^[[:space:]]*(server_name|root)[[:space:]]/p'
```

需要核实原Compose项目名、实际env文件绝对路径（label可能缺失，此时从原部署记录核对，不输出内容）、db-data卷名、静态root、实际启用的news vhost配置路径、旧镜像、旧manifest路径及可用备份目录。未知值不得采用本文中的假设；revision若不等于34bbe2b0，应停止并重新核查适用性。static root/manifest不能仅从Docker标签推断。

## 审核后更新计划（现有数据库，禁止--fresh）

主线程应将以下变量绑定到只读核对结果，并把NEWS_TARGET_SHA固定为本兼容分支审核后的40位完整HEAD。目标镜像必须为该SHA不可变标签/摘要。

```sh
set -eu
: "${NEWS_TARGET_SHA:?本次审核提供的固定40位HEAD，禁止取main}"
: "${NEWS_UPDATE_CHECKOUT:?新的独立源码目录，不能覆盖现有工作树}"
: "${NEWS_PROJECT:?现网原Compose项目名}"
: "${NEWS_ENV_FILE:?现网原env文件绝对路径}"
: "${NEWS_DB_VOLUME:?已核实的原project_db-data卷}"
: "${NEWS_STATIC_ROOT:?已核实的原静态root}"
: "${NEWS_OLD_IMAGE:?已核实的原不可变镜像}"
: "${NEWS_CURRENT_MANIFEST:?已核实的旧release manifest绝对路径}"
: "${NEWS_TARGET_IMAGE:?固定NEWS_TARGET_SHA的production镜像引用}"
: "${NEWS_TARGET_MANIFEST:?全新目标manifest绝对路径}"
: "${NEWS_BACKUP_OUTPUT:?源树与static root之外的全新sqlite3备份绝对路径}"
NEWS_OLD_SHA=34bbe2b0f101a9c8423d66a5e296c223fc1d7d52
```

先在新的源码目录固定该提交。若已有一个经确认的repo，可用git worktree add --detach；否则在不存在的NEWS_UPDATE_CHECKOUT克隆独立checkout。不要重置当前用户工作树、不要切main：

```sh
git clone --no-checkout https://github.com/CoderLambert/news-aggregator.git "$NEWS_UPDATE_CHECKOUT"
git -C "$NEWS_UPDATE_CHECKOUT" checkout --detach "$NEWS_TARGET_SHA"
cd "$NEWS_UPDATE_CHECKOUT"
test "$(git rev-parse HEAD)" = "$NEWS_TARGET_SHA"
git merge-base --is-ancestor "$NEWS_OLD_SHA" HEAD
test -z "$(git diff --name-only "$NEWS_OLD_SHA" HEAD -- backend/api/migrations Dockerfile compose.prod.yaml scripts/deploy/deploy.sh scripts/deploy/backup.sh scripts/deploy/rollback.sh scripts/deploy/release_manifest.py scripts/docker-migrate.py)"
```

保留原镜像、旧manifest、静态旧release和原env；另备份原env与实际news vhost到受限目录，不输出密钥。按production target构建，而非默认development：

```sh
docker build --target production --build-arg "RELEASE_SHA=$NEWS_TARGET_SHA" --tag "$NEWS_TARGET_IMAGE" .
python3 scripts/deploy/release_manifest.py validate --manifest "$NEWS_CURRENT_MANIFEST" --image "$NEWS_OLD_IMAGE" --sha "$NEWS_OLD_SHA"
python3 scripts/deploy/release_manifest.py describe --image "$NEWS_TARGET_IMAGE" --sha "$NEWS_TARGET_SHA" --output "$NEWS_TARGET_MANIFEST"
python3 scripts/deploy/release_manifest.py validate --manifest "$NEWS_TARGET_MANIFEST" --image "$NEWS_TARGET_IMAGE" --sha "$NEWS_TARGET_SHA"
NEWSHUB_IMAGE="$NEWS_TARGET_IMAGE" NEWSHUB_ENV_FILE="$NEWS_ENV_FILE" docker compose --project-name "$NEWS_PROJECT" --env-file "$NEWS_ENV_FILE" -f compose.prod.yaml config --quiet
scripts/deploy/deploy.sh --env-file "$NEWS_ENV_FILE" --project "$NEWS_PROJECT" --sha "$NEWS_TARGET_SHA" --image "$NEWS_TARGET_IMAGE" --root "$NEWS_STATIC_ROOT" --manifest "$NEWS_TARGET_MANIFEST" --current-manifest "$NEWS_CURRENT_MANIFEST" --db-volume "$NEWS_DB_VOLUME" --backup-output "$NEWS_BACKUP_OUTPUT"
```

若旧manifest缺失，必须先按既有release_manifest.py describe流程用已验证旧镜像生成，并核对它与原静态current一致；不要手填或伪造manifest。上述deploy调用只是dry run。审阅计划后才由用户执行同样命令加--execute：

```sh
scripts/deploy/deploy.sh --execute --env-file "$NEWS_ENV_FILE" --project "$NEWS_PROJECT" --sha "$NEWS_TARGET_SHA" --image "$NEWS_TARGET_IMAGE" --root "$NEWS_STATIC_ROOT" --manifest "$NEWS_TARGET_MANIFEST" --current-manifest "$NEWS_CURRENT_MANIFEST" --db-volume "$NEWS_DB_VOLUME" --backup-output "$NEWS_BACKUP_OUTPUT"
```

原脚本会核对旧镜像/项目/卷/static，停止该项目app/crawler/indexer，确认没有其他卷写入者，生成并校验SQLite在线快照，再运行一次迁移，等待app/worker健康后导出静态并原子切换current。无需新增迁移，但不能绕开备份和manifest检查。失败保持该项目停止，不自动启动旧镜像。不要docker compose down -v、删除卷或手删WAL/SHM。

deploy.sh按--image临时覆盖NEWSHUB_IMAGE，并沿用原env内容。成功后若需持久化后续Compose操作的镜像引用，只更新原env中的NEWSHUB_IMAGE为同一个固定目标引用；其他安全开关、代理、密钥和路径不改。

## Nginx验证与回滚计划

核对实际启用news vhost与基线差异，备份该文件，然后只应用受管news.lambert.host.conf中的gzip差异；保留实际root与路径，不能整套覆盖Nginx或其他vhost。先sudo nginx -t成功再按原服务方式reload。原SSE locations仍gzip off/buffering off，精确列表保持no-store及反代头。实际vhost文件路径与服务名由用户核实后再给完整操作命令。

用户可在服务器本机使用curl --resolve news.lambert.host:443:127.0.0.1并沿用有效TLS证书，检查默认列表JSON无正文、摘要<=300、详情完整、Accept-Encoding:gzip对应Content-Encoding/Vary、搜索/过滤/分页和首页。不得把HTTP200或健康状态当成整个用户流程通过；不要为了验证调用AI。生产真实文章gzip字节应重新测量，不套用合成1,152字节。

本热修复迁移集合未变化，正常代码回滚使用原rollback.sh；它会独立校验数据库迁移集合与旧manifest严格一致。成功更新后回滚的current-manifest应指目标新manifest：

```sh
scripts/deploy/rollback.sh --env-file "$NEWS_ENV_FILE" --project "$NEWS_PROJECT" --sha "$NEWS_OLD_SHA" --image "$NEWS_OLD_IMAGE" --root "$NEWS_STATIC_ROOT" --manifest "$NEWS_CURRENT_MANIFEST" --current-manifest "$NEWS_TARGET_MANIFEST" --db-volume "$NEWS_DB_VOLUME"
```

先审阅dry run，再由用户加--execute。若迁移集合不匹配，保持停止并按既有restore流程恢复经校验的备份，不强制绕过。恢复先前news vhost并nginx -t成功后reload；保留所有新旧镜像、release、manifest和备份用于审计。上述更新/回滚动作均未执行，须主线程复核并由用户操作。
