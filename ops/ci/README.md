# NewsHub 自托管 CI：Omarchy + Docker

> **开发/合并双阶段 CI**：Draft PR 的每次提交只跑按增量选择的快检（前端 TypeScript/Lint，后端 Python/少量关键回归）；Ready for review 后按整个 PR 累计差异执行完整 Vitest/pytest、生产镜像和隔离 G1，`merge-gate` 汇总结果。main Push 与 `workflow_dispatch` 保留完整检查。批准的文档/非运行时白名单零 Runner。规则详见 [CI 双阶段分流说明](change-routing.md)。`SKIPPED` / `NOT_RUN` 均不得冒充 PASS。

状态：**仓库配置已准备；尚未在用户 Omarchy 主机部署或实际验收**。不会修改新闻网站或生产数据库。无需 KVM 和虚拟机。

## 设计与边界

- 为同一私有仓库配置**两个独立 GitHub Runner**，自动并行领取工作：
  - 后端：omarchy-newshub，标签 newshub-ci，负责 Python/Django/生产镜像/G1 烟测；沿用旧版单 Runner 的 runner-state/runner-work 数据卷，避免意外重注册。
  - 前端：omarchy-newshub-frontend，标签 newshub-frontend，负责 Node/TypeScript/Lint/Vitest/build。前端完全不挂载 Docker socket、后端工作目录或后端 Docker 镜像缓存。
- Ubuntu 24.04 Runner 镜像固定为 myoung34/github-runner:2.337.0-ubuntu-noble；预装 Python 3.12、Node 22、Docker/Compose、Playwright Chromium。
- 单独运行 docker:29-dind，以私有 Unix socket 通信。不挂载 Omarchy 宿主 /var/run/docker.sock；不发布 DinD 端口。
- 后端 runner-work 卷同时挂在后端 Runner 和 DinD 中的 **相同绝对路径** /ci-work/_work。这是为了让原有 Docker bind mount、Compose 和 G1 浏览器烟测正确找到工作目录。
- 前端的 frontend-work 卷仅挂在前端 Runner 中，路径为 /ci-frontend/_work；两个 Job 分别 checkout，互不覆盖。
- G1 HTTP/浏览器/SSE 探针：CI 从 `ops/ci/g1-probe.Dockerfile` 构建并在 DinD 持久卷中缓存专用 Chromium + Playwright 镜像；设置 `LOCAL_DOMAIN_G1_PROBE_IMAGE=newshub:ci-g1-probe` 时，所有 G1 网络请求通过 `--network container:<gateway-id>` 在网关命名空间内运行，不需对外发布端口，也不向探针提供 Docker socket。探针仅挂载测试 CA（只读）和本次报告目录（可写）；未设置变量则保留原有本地直连模式。
- TMPDIR=/ci-work/_work/.ci-tmp 同样共享，避免源目录只存在于 Runner 容器而 DinD 看不到。
- runner-state 和 frontend-state 分别保存两个 Runner 的 GitHub 注册身份；docker-data 保存后端 DinD 构建缓存；状态和缓存均与其他 Docker 项目隔离。
- 默认资源：后端 Runner 3 vCPU/6GB、前端 Runner 2 vCPU/4GB、DinD 2 vCPU/5GB。三者各有资源上限，峰值总计上限约 15GB，CPU 约 7 vCPU。一个 Runner 只执行一个 Job，但**两个 Runner 同时执行两个 Job**。对于目前可用内存约 20GiB 的 Omarchy，建议先保持这些保守限额，观察高峰资源。

**安全提醒：DinD 容器使用 privileged，并不提供虚拟机级安全隔离。** 不允许把它用于不可信 fork 或公开仓库，不应授予它生产凭据或其他项目目录。自托管 Runner 的文件/缓存会跨 Job 保留。此方案比直接暴露 Omarchy 宿主 Docker socket 降低直接访问面，但绝不等于无风险。

## 1. 在 Omarchy 安装

前置条件：已有 Docker + Docker Compose v2 + GitHub CLI (gh)，GitHub 登录账号对仓库拥有足够的 Runner 管理权限。

~~~bash
# 如果已在 NewsHub 仓库中，请跳过 clone。
git clone https://github.com/CoderLambert/news-aggregator.git
cd news-aggregator
git fetch origin
git switch feat/docker-self-hosted-actions-20261017

gh auth status -h github.com
bash ops/ci/manage.sh doctor
bash ops/ci/manage.sh install
~~~

安装命令会使用 gh API **分别为两个 Runner 获取一次性注册 Token**，不要求复制长期 PAT，也不会把 Token 写入 Compose Environment。临时 Token 分别存于宿主机私有文件 registration-token 和 registration-token-frontend，两个 Runner 注册成功后均清空。已注册的 Runner 复用原身份，重复安装不会额外注册同名实例。如果你已装过单 Runner，此次只会为新增的前端 Runner 注册。

首次镜像构建会下载 Chromium、Python/Node 依赖，可能耗时。安装输出没有实际 Online 状态时，打开 https://github.com/CoderLambert/news-aggregator/settings/actions/runners 查看 Runner 状态。不要把注册 Token、PAT 或 .runner/.credentials 文件发给任何人。

## 2. 运维命令

~~~bash
bash ops/ci/manage.sh status
bash ops/ci/manage.sh logs
bash ops/ci/manage.sh stop
bash ops/ci/manage.sh start
bash ops/ci/manage.sh update
bash ops/ci/manage.sh cache-status
bash ops/ci/manage.sh warm-cache
bash ops/ci/manage.sh cache-gc
bash ops/ci/manage.sh cache-gc --execute
bash ops/ci/manage.sh uninstall
~~~

- doctor 仅检查本机 Docker 和 Compose 配置，不创建容器。
- install 可重跑，分别检查两个 Runner 的持久身份；如果此前已安装过单 Runner，会保留原后端 Runner 并新增前端 Runner。
- install、start 和 update 会先用 maintenance 容器预热前后端及 BYOK T00 依赖缓存，全部成功后才启动 Runner listener；预热失败不会让 Runner 上线领取任务。T00 复用现有 cache-backend 容器和 runner-work 卷，不新增维护服务。
- cache-status 只运行安装器的只读状态检查，输出 `CACHE_KIND`、`STATUS`、`KEY` 和 `ROOT`。`HIT` 表示环境完整且校验通过，`PARTIAL` 表示同 key 安装曾开始但尚未完成，`MISSING` 表示该 key 尚无缓存目录。
- warm-cache 在确认两个 Runner 空闲后暂停 listener，以 `--cache-only` 填充持久卷，不在源码 checkout 创建 `backend/venv` 或 `frontend/node_modules` 链接。
- cache-gc 默认只预览；只有显式添加 `--execute` 才会持锁删除过期的 64 位十六进制 keyed 目录。它保留 `.current-key`、最近两个成功条目、下载缓存、锁和未知目录，不使用任何全局 prune。
- stop 只停止 newshub-ci 项目；uninstall 只移除该项目的容器和网络，不删除 Runner 身份、Docker 数据卷，不操作其他 Docker 项目，也不从 GitHub 自动注销 Runner。
- 永久删除 Runner：在 GitHub 仓库设置中先手动删除两个对应 Runner，确认无需旧缓存后再有针对性地删除明确命名的 newshub-ci 卷。禁止全局 prune。
- 两个 Runner 的快检或完整任务均可并行；Draft 每次修改**不跑完整测试/构建/G1**，Ready 才对同一 PR 启动完整前后端检查；同一 Runner 仍只能同时处理一个 Job，排队由 GitHub 控制。

## 3. 仓库启用和验收步骤

1. **先在 Omarchy 安装并确认 omarchy-newshub 与 omarchy-newshub-frontend 都是 Online**。
2. 开发中的 PR **保持 Draft**，只运行按影响范围选中的 `dev-frontend` / `dev-backend` 快检；未选中业务 Job 显示 Skipped **不是全量通过**。实现/专项测试准备好后转换为 Ready for review，自动运行原前后端完整 CI 与 `merge-gate`；任一 Runner 离线会导致对应 Job 排队。
3. 检查隔离 daemon、共享文件路径、Python/Node、Chromium、前后端测试、生产 Docker 构建及 G1 浏览器烟测。
4. 所有必要检查通过，才将本 PR 合并 main；随后可手动运行已添加的 smoke 工作流。

~~~bash
gh workflow run ci-runner-smoke.yml --repo CoderLambert/news-aggregator --ref main
gh run list --repo CoderLambert/news-aggregator --workflow ci-runner-smoke.yml --limit 3
~~~

注意：新建的 workflow_dispatch 工作流通常必须存在于仓库默认分支上，才能按文件名手动触发。PR 阶段先用其自动 CI 测试，不要为了触发手动 smoke 提前绕过审核合并。

现有 CI 工作流调整为：**同仓库 Draft PR 仅快检**，Ready PR / main Push / 手动 dispatch 全检；外部 fork 不领取自托管 Runner。移除了非 main 分支 Push 造成的重复 PR/Push CI；新提交取消过时检查。为保持效率，完整检查阶段出错后需继续修复时，先将 PR 改回 Draft，再提交迭代，最后再次 Ready。没有 GitHub 托管 Runner 的回退标签。

## 4. 安装完成后的实际验收

先不要凭 `The runner has already been configured` 判断成功。旧版配置曾缺少显式 Listener CMD，导致 `gosu user-spec command [args]` 循环、3 分钟超时。已在修复提交中为两个 Runner 均补充 `./bin/Runner.Listener run --startuptype service` 并添加静态回归测试。

在 Omarchy 上执行：

~~~bash
git fetch origin
git switch feat/docker-self-hosted-actions-20261017
git pull --ff-only
bash ops/ci/manage.sh install
bash ops/ci/manage.sh status
docker logs --tail 100 newshub-ci-runner-1
docker logs --tail 100 newshub-ci-runner-frontend-1
~~~

请使用 `bash ops/ci/manage.sh status` 检查 Compose 状态；它会自动设置 `CI_DATA_DIR`。

**通过标准**：两个 Runner 都显示 Online，前后端 Runner 日志分别出现类似 `Listening for Jobs` 的就绪信息，而不是不断重启；`docker` sidecar 健康。单靠注册文件存在不代表 Runner 在线。

Runner Online 后，Draft 仅执行轻量 `changes` 与受影响的 `dev-frontend` / `dev-backend`。将 PR 改为 Ready for review，再检查 `frontend`、`backend-and-release-gates` 和 `merge-gate` 的实际结果；重点核对 Node、DinD/共享 TMPDIR/Playwright、整套测试是否针对最新 head SHA。任一选中 Job 非 SUCCESS 不得合并。

## 5. 开机恢复及健康自愈

**已集成开机用户级 systemd 定时器**。首次成功执行 manage.sh install、且 GitHub 确认两个 Runner Online 后，安装脚本自动尝试启用 newshub-ci-watch.timer。可手动重新启用： 监控程序会被单独复制到私有目录 `$CI_DATA_DIR/bin/watch.py`（默认 `~/.local/share/newshub-ci/bin/watch.py`），并通过 Docker Compose 项目标签发现容器，因此切换 Git 分支后**仍可在开机时运行**。更新监控程序时重新执行 `enable-watch` 即可刷新这份副本。

~~~bash
bash ops/ci/manage.sh enable-watch
systemctl --user list-timers newshub-ci-watch.timer
bash ops/ci/manage.sh watch-logs
~~~

若想 Omarchy **开机但尚未登录桌面**时也运行定时器，额外执行一次（需要 sudo）：

~~~bash
sudo systemctl enable --now docker.service
sudo loginctl enable-linger "$USER"
~~~

如果不启用 linger，用户 systemd 通常仅在用户登录后启动，不能保证登录前恢复。执行命令前确认自己允许 user manager 后台常驻。本仓库代码不会静默打开 linger，也不会修改其他 systemd units。

定时器启动时等待约 2 分钟，然后每 5 分钟检查：

- 宿主 Docker daemon 是否可用、两个 Runner 是否存在及运行状态、独立 DinD 是否健康。
- 能访问 GitHub API 时核对两台 Runner 的 Online/Busy 状态；容器还在运行时用 docker top 查验有无 Runner.Worker。
- GitHub 报告 Busy、检测到本地工作进程、或无法确定是否安全时，**不重启运行中的 CI**；只在明确无活动作业时尝试恢复异常容器。
- 同一服务的恢复间隔至少 15 分钟，每 6 小时最多主动尝试 3 次；连续处于 Docker Restarting 状态且无活动作业时，二次检查后停止崩溃循环容器，留下日志，避免无休止重启。
- 如果 GitHub API 不可用，运行中的 Runner 不被强制重启；恢复采取保守策略。判定错误/无法访问不能自动“修复”注册身份和 GitHub 付款限制。

手动管理：

~~~bash
bash ops/ci/manage.sh status
bash ops/ci/manage.sh watch           # 立即执行一次检查，可能对明确异常的空闲容器恢复
bash ops/ci/manage.sh watch-logs
bash ops/ci/manage.sh stop            # 会拒绝在 Busy 时停止，且放置手动停止标记
bash ops/ci/manage.sh start           # 移除手动停止标记
bash ops/ci/manage.sh disable-watch   # 只停用本项目的 user timer，不改 linger
~~~

请注意：重启过程中**已经在执行**的 Job 不能从中断处恢复，只能在 GitHub 重新运行。系统自启/自动恢复不等于测试自动续跑。若检测到手动 stop 标记，watchdog **不会自动启动** Runner。

## 锁定 CI Python 依赖与监控（CI-P04）

- `backend/requirements-ci.lock` 锁定 CPython 3.12 / Linux x86_64 的完整解析结果（包含传递依赖），来源为首次成功的真实 CI 安装记录。与生产 `backend/requirements.txt` 分离，不更改生产发布依赖。
- `ops/ci/check-backend-lock.py` 检查重复/未锁定项目、直接依赖覆盖和缓存环境内 158 个版本。PyTorch CPU 固定版本仍先从官方 CPU Index 安装。
- `ops/ci/install-backend-deps.sh` 的缓存指纹同时包含 `requirements.txt` 和完整的 CI lock。修改任一文件才会自动重建环境；日常代码提交仍复用已安装依赖。
- `ops/ci/cache-summary.sh` 在工作流结束时输出安装器状态和 DinD BuildKit 占用概要，不遍历或打印缓存内容；执行超时也不阻断业务检查。
- 首次部署锁文件会出现一次正常 `MISS`（缓存键升级），以后 `HIT`。**不自动清理任何 Docker 镜像或卷，不触碰生产数据**。
- 依赖升级流程：在隔离环境中明确升级并运行全套检查后，重新生成 `pip freeze`，同步到 CI lock 并审核变更差异；不要自动选择最新的 `>=` 范围版本。

## PR 快速反馈（CI-P03）

- 前端 Runner 在依赖缓存检查之前执行 Python `compileall` 与 shell `bash -n`，不接入 DinD 或后端数据卷。
- 后端 Runner 在完整回归测试之前执行一组安全/部署关键用例，并使用 `--maxfail=1` 快速暴露失败。
- 现有的 Python 全量测试、前端 typecheck/lint/Vitest/build、Docker 生产镜像和 G1 Smoke **全部保留**。快速用例可能在全量阶段再次运行，这是有意的早期反馈，不是减少门禁。
- 新步骤只检查源码，不能访问生产服务、生产数据或任何秘密。

## CI 性能调优基线（2026-10-17）

PR #81 自托管 Runner 的一次热缓存验收中，后端 pytest 测试为 2408 passed / 16 skipped / 264 秒。CI 仍完整执行三个测试根目录、生产镜像构建和 G1 Smoke，没有降低合并门槛。

- 实际 pytest 运行已包含三个根目录的收集过程，移除单独的重复 `--collect-only` 步骤；缺失任何显式目录仍会使 pytest 失败。
- 测试输出保留 `--durations=40 --durations-min=0.5`，按 setup/call/teardown 排序显示慢用例，便于持续排查。
- RSS EngineAdapter 本地 HTTP server 的测试关闭轮询由默认 0.5 秒降为 0.02 秒，仍使用真实 HTTP 和标准 `shutdown()`。
- 全文 Worker 的 SQLite 迁移只在模块级子进程执行一次，各测试通过独立临时数据库副本运行，不共享数据库、锁、心跳或持久进程。
- 默认 CI 后端测试使用受限混合并行。T31 退役旧采集实现后，`test_smart_channel_workspace.py` 和 `test_channels.py` 继续串行；其余三测试根目录通过固定 `pytest-xdist==3.8.0` / `execnet==2.1.1`、`-n 2 --dist=loadfile --max-worker-restart=0` 执行。每轮按实际收集结果对账全部执行身份，检查 JUnit 零失败并保留原 skip 审计，不固定 passed 总数，不把失败改成跳过。主 CI `CI_XDIST_REPEATS=1`，独立实验仍重复 3 次。完整 CI、镜像与 G1 的实际结果须绑定对应提交；文档不能替代发布或生产验收。

## 6. 长期持久缓存

本 PR 在独立 Runner 工作卷与 DinD 数据卷中保存缓存，重启和 GitHub checkout **不会删除**。安装器不会每次重建 Runner 镜像；依赖无变化时不必重新下载大型 Python wheels、PyTorch 和 npm 包。

| 缓存 | 命中条件 | 命中后行为 |
|---|---|---|
| 前端 node_modules | package.json、package-lock.json、Node/npm 版本、CPU 架构指纹一致且 npm ls 验证通过 | 直接复用完整已安装目录，**不运行 npm ci** |
| npm 下载缓存 | npm integrity cache，随 frontend-work 卷保留 | 首次缺包时 npm ci --prefer-offline，已有 tarballs 不重复下载 |
| 后端 Python venv | requirements.txt 内容、Python ABI、架构、PyTorch 2.14.1+cpu、Playwright 1.62.0 指纹一致且 pip check 通过 | 直接复用 venv，**不重复执行 pip install** |
| pip 下载缓存 | 持久 PIP_CACHE_DIR | 首次/依赖变化时尽量重用 wheels 和包元数据 |
| BYOK T00 SDK/Proxy + Prisma | 两份 pinned lock、prepare_proxy.py、Python/Node 版本及架构一致，pip/包元数据、生成客户端和 Prisma 文件校验通过 | 仅复用依赖；协议、权限、流式终止和 Django 合成集成验证每次仍执行 |
| 浏览器 Chromium | 在自定义 Runner 镜像的构建阶段安装 | 后续 CI 直接使用，无需每次 playwright install |
| Docker build 镜像层 | 独立 DinD 的 docker-data 卷 | 未修改的生产构建层复用；不需要每次完整下载/构建 |
| Docker BuildKit 下载缓存 | RSS pip、frontend npm、runtime Torch pip 各有独立 `sharing=locked` cache id | 构建步骤失败或上层缓存失效后仍复用已下载 wheel/tarball |
| Nginx smoke 镜像 | DinD 本地镜像存在 | 检查 image inspect；首次才 docker pull |

首次冷启动或锁文件发生变更仍可能下载依赖。**后端 requirements.txt 中有不少 >= 范围依赖**，相同内容指纹会复用首次解析的已安装版本；需要有意识地升级依赖时，运行 install-backend-deps.sh --refresh 或提高 CI_BACKEND_CACHE_REV，并建议后续补严格 lock 文件以提升可复现性。缓存命中始终进行结构及依赖检查，而不是无条件跳过验证。

首次部署会产生一次正常冷安装。普通源码 checkout、Runner 重启和失败重试会继续使用相同命名卷；只有依赖指纹、Python/Node ABI 或显式 cache revision 变化才产生新 key。中断的后端环境显示 `PARTIAL`，下次安装会原地 `RESUME` 并复用 pip 下载缓存；前端失败重试会复用 npm integrity 下载缓存。

缓存维护统一使用下面的入口：

~~~bash
bash ops/ci/manage.sh cache-status
bash ops/ci/manage.sh warm-cache
bash ops/ci/manage.sh cache-gc             # 仅预览
bash ops/ci/manage.sh cache-gc --execute   # 空闲检查、持锁、定向删除
~~~

T00 使用同一维护合同：`--status` 只读，`--cache-only` 无须 GitHub Outputs；成功条目写 `.newshub-ready`，根目录写 `.current-key`。旧 `.ready` 只有经过依赖/生成客户端校验后才迁移，不为改标记而重复安装。Prisma manifest/schema 还校验内容摘要，损坏时重建对应 key。

T00 根为后端工作卷的 `.cache/newshub-t00-venvs`。统一 GC 默认仅预览，执行后保留最近两个成功条目加当前条目（最多三个不同 key），不删除下载缓存；两次显式维护之间仍可能积累新 key，这不是按字节自动限额。按锁文件更新频率通过上述入口定期预览和维护，不额外创建后台清理任务。维护命令继续执行双方 Runner 空闲检查并暂停 listener；T00 协议步骤还在完整消费者生命周期内共享 `.install.lock`，安装/GC 必须取得排他锁，因此不能删除运行中的环境。

**不要**在 Job 正在运行时删除缓存，不要使用 docker system prune、docker volume prune 或删除 newshub-ci 的状态卷。安装器会优先尊重显式 `PIP_CACHE_DIR` / `npm_config_cache`；未设置时下载缓存仍回退到对应持久 cache root 内，不应改为 checkout 临时目录。

## 生产镜像构建输入与耗时诊断（CI-BUILD）

生产 Dockerfile 固定到 CI #1036 已解析并成功构建过的 Python、Node 和 Dockerfile frontend digest，避免浮动标签更新在普通源码提交中隐式重建依赖链。基础镜像的安全更新仍需维护：显式修改 digest，核对 Python/Node 版本与架构，并在获准后执行完整镜像/G1 验收；固定 digest 不代表可以永久停止更新。npm/Torch/pip 下载缓存 ID 和安装指令保持不变，减少缓存方案自身造成的再次冷启动。

`.dockerignore` 排除本地 `.worktrees/`、Agent 产物、文档和明确的测试目录，避免将嵌套工作树传给 Docker，或仅测试修改使 `COPY backend/`、`COPY frontend/` 的层失效。测试仍从 CI checkout 全量执行；迁移、模板、静态资源、应用代码和 `scripts/deploy/local_domain_fixtures.py` 保留。此规则也作用于根上下文的 development/rss 镜像，因此镜像自身不携带被排除的测试目录；开发源码 bind mount 和 CI checkout 仍包含它们。

生产非 root 用户/目录创建位于 `ARG RELEASE_SHA` 之前。只有发布身份校验/标签依赖当前 SHA；每次构建仍验证完整 SHA，并以 `newshub:ci-<SHA>` 标记，G1 继续验证该镜像与同 SHA 静态资源。不按测试结果、缓存命中或源码指纹跳过正式镜像构建。

CI 的生产镜像步骤调用：

```bash
python3 ops/ci/build-production.py --sha "$RELEASE_SHA" --image "$NEWSHUB_IMAGE" \
  --report "$RUNNER_TEMP/production-build-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}.json"
```

该入口只允许 CI 私有 Docker socket 和与 SHA 一致的 CI tag，始终执行原来的 `docker build --target production`，增加 `--progress=plain`。实时输出原构建日志；JSON 与 GitHub Step Summary 记录 wall time、逐层执行/命中/失败状态、依赖层命中数。摘要只保存固定类别和耗时，不保存 RUN 输出、任意命令或下载 URL。构建退出码原样保留；摘要写入失败不能覆盖原构建错误，信号转发给构建进程组。该入口不安装依赖、不清理缓存、不重试失败构建，也不重启 Runner。

**衡量方式**：BuildKit 并行层耗时不能相加；总时间使用 wrapper 的 wall time。`Using cached` wheel 是下载命中，只有 BuildKit 的 `CACHED` 才是安装层命中。要评估稳定提速，必须在获准后比较相同依赖/基础镜像和缓存条件下的完整成功运行，并至少覆盖纯测试改动、应用源码改动与依赖改动。109 秒冷层重建与 5 秒热层命中不是公平 A/B；本地离线回归也不代表已实测生产镜像时间。

## 7. 环境和故障

### GitHub Runner TLS 超时与项目级 Bridge MTU

2026-10-19 Omarchy 实证：两个 Runner 同时 Offline，TCP 443 通而 api.github.com 的 TLS 握手在项目 Bridge MTU=1500 下超时。同一 Runner 镜像在 Host 网络正常；临时将两个容器的 eth0 调整到 MTU=1280 后 HTTPS 返回 200、Runner 恢复 Online 并领取排队 CI。此结果**支持 MTU/PMTU 路径问题**，尚未确定具体的丢包设备。

按用户要求，Compose 将 **newshub-ci 项目自身**的默认 Bridge 网络及 DinD 内部默认 Bridge **固定为 MTU=1200**，移除 `CI_BRIDGE_MTU` 覆盖入口，避免重启后回到旧值。不改宿主机 Docker 全局设置，不授予前端 Runner Docker socket，也不自动改动现有正在运行的容器。仓库配置更新后旧网络不会自动应用新 MTU。

2026-10-20 补充实证：外层容器调整后，DinD 默认内层网络仍为 1500，同一 Python 镜像访问 PyPI TLS 超时；内层 host 网络返回 200/0.622 秒，独立 MTU=1280 bridge 返回 200/0.758 秒。`dockerd --mtu` 使后续默认容器及 BuildKit 网络使用相同 MTU；现有用户自建网络不自动变化。此对照支持内层 MTU/PMTU 故障，不证明具体丢包设备。刷新时须保留注册、工作卷和下载缓存，不预先删除镜像或缓存。

仅在**当前 PR/main CI 全部完成**、两个 GitHub Runner Online/Idle 且本地没有 Runner.Worker 时，才在 Omarchy 上运行：

~~~bash
git fetch origin && git switch main && git pull --ff-only
bash ops/ci/manage.sh status
# stop 使用 GitHub Busy 和本地 Worker 双重保护；失败就不要 down。
bash ops/ci/manage.sh stop || exit 1
export CI_DATA_DIR="${CI_DATA_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/newshub-ci}"
# 仅删除该 CI 项目容器和网络；不加 -v，保留注册身份、工作卷和 DinD 缓存。
CI_DATA_DIR="$CI_DATA_DIR" docker compose -p newshub-ci -f ops/ci/compose.yaml down || exit 1
bash ops/ci/manage.sh start
bash ops/ci/manage.sh status
docker exec newshub-ci-runner-1 cat /sys/class/net/eth0/mtu
docker exec newshub-ci-runner-frontend-1 cat /sys/class/net/eth0/mtu
~~~

通过条件：两个 Runner 的 eth0、DinD 的 eth0/docker0 及新建默认容器均为 1200，GitHub 两个 Runner 均 Online，随后适用的精确 PR head CI 实际运行成功。若需要回退，须审核修改 Compose 的外层及 `dockerd --mtu` 两处固定值，再在空闲状态按同一受保护流程重建网络；1500 可能重新触发本故障。不得在 CI Busy 时执行 down，不使用全局 prune，不删数据卷。

- Runner 与 DinD 都需要联网拉镜像和工具；不需要公网入站端口。
- 预装 Chromium，后端 venv 仍安装原工作流指定版本 playwright==1.62.0。
- 若 docker compose 无法启动 DinD，请检查当前 Omarchy 的内核、cgroup/overlay2、iptables 和资源。不要未经审核直接改为挂宿主 Docker Socket。
- 如果 DinD 内的 Docker bind mount 找不到 NewsHub 工作目录，检查后端 Runner 和 DinD 挂载的 /ci-work/_work 路径一致及 TMPDIR 是否共享；前端 Runner 不需要 DinD 或共享后端目录。
- 如果两个 Runner 在 GitHub 注册页 Online 但任务一直排队，确认仓库 Actions 仍有调度权限（账单/预算限制可能独立阻断任务），并检查 PR 是否仍为 Draft；Draft 的 CI 会 Skipped，不能当成测试通过。
- 你当前 Omarchy 可用内存约 20GiB。本配置两 Runner + DinD 默认 6GB+4GB+5GB，避免长期工作时抢占其他开发程序内存；内存峰值需实际测量。
- 自托管计算分钟通常不按 GitHub-hosted Runner 计费，但工件/缓存可能产生其他使用费。如果 GitHub Billing 全局限制阻止调度，需要单独处理，本脚本不修改预算或支付方式。
- CI 只处理仓库合成环境，绝不接入生产 SQLite、PostgreSQL、Gitea 或 Tailscale 服务。

## 8. 首次真实 CI 发现的 DinD DNS 问题

首次并行验收：[GitHub Actions #38957249484](https://github.com/CoderLambert/news-aggregator/actions/runs/38957249484)。
前端全部通过（Node/缓存恢复/类型/Lint/Vitest/Build）；后端在独立 Docker 预检首次拉取 alpine:3.22 时失败：

~~~text
lookup registry-1.docker.io on 127.0.0.11:53: server misbehaving
~~~

说明 DinD 本身 healthy、Docker CLI 可连接，但 **Docker Hub 外部域名解析尚不可用**，不能把它当作应用代码测试失败。本分支已为独立的 DinD 服务及其子容器添加可配置 DNS，默认 1.1.1.1 与 8.8.8.8；不修改 Omarchy 宿主 Docker DNS 或其他 Compose 项目。Docker Compose 支持服务级 dns，Docker Engine 支持 dockerd --dns 设置默认容器 DNS。

从本分支更新，并在**两个 Runner 都空闲**时刷新当前容器配置：

~~~bash
git fetch origin
git -c merge.autoStash=false merge --ff-only origin/feat/docker-self-hosted-actions-20261017
bash ops/ci/manage.sh update
bash ops/ci/manage.sh status

# DNS 必须在 DinD 容器内测试，不是在 Omarchy 宿主上。
docker exec newshub-ci-docker-1 nslookup registry-1.docker.io

# 测试独立 Docker daemon 镜像拉取；首次下载后会缓存。
docker exec newshub-ci-runner-1 docker pull alpine:3.22
~~~

如果默认公共 DNS 在本地网络被阻断，应先确认 Omarchy 可使用的真实上游 DNS，再设置可访问的地址。例如（只是语法示例，**不要猜测内网 IP**）：

~~~bash
CI_DIND_DNS_PRIMARY=1.1.1.1 CI_DIND_DNS_SECONDARY=9.9.9.9 bash ops/ci/manage.sh update
~~~

仍失败时检查：`docker exec newshub-ci-docker-1 cat /etc/resolv.conf`、`nslookup`、网络策略、Clash/Tailscale/UDP 53 是否可达以及 DinD 日志。Compose 自定义网络容器内部可能仍显示 127.0.0.11；这是 Docker 嵌入式转发器，**要以 nslookup/pull 实际结果判断**。仅改 DNS 不保证公司/家庭网络上的外部网络策略全部通畅。切勿直接改为挂载宿主 `/var/run/docker.sock` 绕过限制。

在以上检查通过后，将 PR 从 Draft 改为 Ready for review 再次运行完整 CI。**不要**为了跳过 DNS 问题而删除 Docker 构建、浏览器烟测或其他验收步骤。

## 9. 第二轮 CI：非 root Runner 的 Docker Socket 权限

在 DinD 网络修复后，用户本机已通过以下检查：

- `docker exec newshub-ci-docker-1 nslookup registry-1.docker.io`：解析成功（代理可能使用 198.18.0.0/15 Fake-IP）。
- `docker exec newshub-ci-runner-1 docker pull alpine:3.22`：镜像下载成功。

但是该 `docker exec` 默认以容器配置的 **root 用户**运行，与 GitHub Job 通过 `gosu runner` 启动的 **UID 1001 / GID 121** 不同。因此此命令不能证明正式 CI 的 Docker 权限。

[第二轮 CI #38959085183](https://github.com/CoderLambert/news-aggregator/actions/runs/38959085183) 后端日志：

~~~text
permission denied while trying to connect to the docker API at unix:///ci-docker/docker.sock
~~~

原因：运行中的 DinD 尚未应用 Compose `$group` 转义修复，Daemon 可能以不匹配的 Socket 组创建 `docker.sock`。在仓库中新补齐的解决方案：

1. Compose 命令使用 `--group="$group"`，使容器 Shell 收到 `--group="$group"`，并指向 GID 121 对应的组。
2. Runner healthcheck 和安装等待检查以 `/usr/sbin/gosu runner docker info` 运行，避免 root 正常而 GitHub Job 无权限的假阳性。
3. GitHub CI 预检查会记录实际 Job `id` 和 Socket 的数字 UID/GID/权限（不打印凭据），出错时给出准确诊断。

**两个 Job 空闲后**，在 Omarchy 拉取当前分支并使用 `update` 重新创建 DinD：

~~~bash
git fetch origin
git -c merge.autoStash=false merge --ff-only origin/feat/docker-self-hosted-actions-20261017
bash ops/ci/manage.sh update
bash ops/ci/manage.sh status

# 核实 Unix Socket 权限以及实际非 root CI 用户访问：
docker exec -u runner newshub-ci-runner-1 id
docker exec -u runner newshub-ci-runner-1 ls -ln /ci-docker/docker.sock
docker exec -u runner newshub-ci-runner-1 docker info --format '{{.ServerVersion}}'
~~~

最后一条以普通用户打印 Docker Engine 版本即证明授权成功；若仍 `permission denied`，不要执行 chmod 666，也不要把宿主 Docker Socket 挂进来。检查 DinD daemon 命令、Socket GID 与 Runner 的组，并提供日志定位。

检查都通过后，再将 PR 标记为 Ready for review。完整后端 CI 仍需实际运行并通过才能合并。注意：2026-10-16 第二轮前端 Job 因后续推送触发的并发取消机制中断，**不能将取消当作通过**；之前第一轮前端完整通过的结果仍有效，但最终必须核查当前 HEAD。

## English quick reference

Install **two repository-scoped Docker self-hosted Runners** on Omarchy without mounting the host Docker socket. Run bash ops/ci/manage.sh doctor and bash ops/ci/manage.sh install. Confirm **both** backend and frontend Runners are Online in GitHub runner settings, review concurrent PR checks, then merge. The separate privileged DinD daemon shares a CI-only workspace for the real NewsHub Docker/browser smoke test. Do not run untrusted pull requests or unrelated repositories on this persistent Runner. Deployment and GitHub CI verification are pending until this configuration is executed on the user host.

### Private translation Redis tests

The full backend hybrid runs through `with-translation-redis.sh`. It starts the
pinned image from `compose.translation.yaml` without a network or TCP listener,
using an authenticated Unix socket in a fresh shared `$TMPDIR` directory. This
also works across the runner/private-DinD boundary. Tests receive only
`TEST_TRANSLATION_REDIS_SOCKET`; neither the live application's Redis URL nor
production data is used. The wrapper keeps the test command's failure status
and removes its exact disposable container/directory on exit. The existing
skip budget and collection/coverage reconciliation stay unchanged.
