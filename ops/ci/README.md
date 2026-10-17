# NewsHub 自托管 CI：Omarchy + Docker

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
bash ops/ci/manage.sh uninstall
~~~

- doctor 仅检查本机 Docker 和 Compose 配置，不创建容器。
- install 可重跑，分别检查两个 Runner 的持久身份；如果此前已安装过单 Runner，会保留原后端 Runner 并新增前端 Runner。
- stop 只停止 newshub-ci 项目；uninstall 只移除该项目的容器和网络，不删除 Runner 身份、Docker 数据卷，不操作其他 Docker 项目，也不从 GitHub 自动注销 Runner。
- 永久删除 Runner：在 GitHub 仓库设置中先手动删除两个对应 Runner，确认无需旧缓存后再有针对性地删除明确命名的 newshub-ci 卷。禁止全局 prune。
- 同时启动两个 Runner 后，GitHub 的 frontend 和 backend-and-release-gates Job 在**同一次 PR CI 内并行执行**；只有同类多个 PR 同时提交时，同一 Runner 对应的任务才需要排队。

## 3. 仓库启用和验收步骤

1. **先在 Omarchy 安装并确认 omarchy-newshub 与 omarchy-newshub-frontend 都是 Online**。
2. 当前 PR **保持 Draft**，因此两项 CI 暂时显示 Skipped（不是通过）。两个 Runner 均 Online 后，将 PR 标记为 Ready for review，触发前后端并行自托管 CI；若任一 Runner 离线，只有相应 Job 会等待。
3. 检查隔离 daemon、共享文件路径、Python/Node、Chromium、前后端测试、生产 Docker 构建及 G1 浏览器烟测。
4. 所有必要检查通过，才将本 PR 合并 main；随后可手动运行已添加的 smoke 工作流。

~~~bash
gh workflow run ci-runner-smoke.yml --repo CoderLambert/news-aggregator --ref main
gh run list --repo CoderLambert/news-aggregator --workflow ci-runner-smoke.yml --limit 3
~~~

注意：新建的 workflow_dispatch 工作流通常必须存在于仓库默认分支上，才能按文件名手动触发。PR 阶段先用其自动 CI 测试，不要为了触发手动 smoke 提前绕过审核合并。

现有 CI 工作流调整为：PR（同仓库、非 Draft）、main Push、手动 dispatch。移除了其他分支 Push 造成的 PR/Push 双重运行；更新提交时会取消过时 CI；工作流中没有 GitHub 托管 Runner 的回退标签。

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

Runner Online 后，PR 保持 Draft 时两项 CI 会被 Skipped。改为 Ready for review，再检查 PR 的两个 Job 是否实际运行；此时重点核对前端 Node 工具链、后端 DinD/共享 TMPDIR/Playwright、整套测试的真实结果。仅当全部通过才合并。

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
- `ops/ci/cache-summary.sh` 在工作流结束时输出后端缓存占用和 DinD BuildKit 占用概要，仅用于诊断；执行超时也不阻断业务检查。
- 首次部署锁文件会出现一次正常 `MISS`（缓存键升级），以后 `HIT`。**不自动清理任何 Docker 镜像或卷，不触碰生产数据**。
- 依赖升级流程：在隔离环境中明确升级并运行全套检查后，重新生成 `pip freeze`，同步到 CI lock 并审核变更差异；不要自动选择最新的 `>=` 范围版本。

## CI 性能调优基线（2026-10-17）

PR #81 自托管 Runner 的一次热缓存验收中，后端 pytest 测试为 2408 passed / 16 skipped / 264 秒。CI 仍完整执行三个测试根目录、生产镜像构建和 G1 Smoke，没有降低合并门槛。

- 实际 pytest 运行已包含三个根目录的收集过程，移除单独的重复 `--collect-only` 步骤；缺失任何显式目录仍会使 pytest 失败。
- 测试输出保留 `--durations=40 --durations-min=0.5`，按 setup/call/teardown 排序显示慢用例，便于持续排查。
- RSS EngineAdapter 本地 HTTP server 的测试关闭轮询由默认 0.5 秒降为 0.02 秒，仍使用真实 HTTP 和标准 `shutdown()`。
- 全文 Worker 的 SQLite 迁移只在模块级子进程执行一次，各测试通过独立临时数据库副本运行，不共享数据库、锁、心跳或持久进程。
- 暂不默认启用 `pytest-xdist`。SQLite 事务测试、心跳/锁、端口和 subprocess 测试并行安全性需单独审核及重复验收；不能仅为速度跳过测试。

## 6. 长期持久缓存

本 PR 在独立 Runner 工作卷与 DinD 数据卷中保存缓存，重启和 GitHub checkout **不会删除**。安装器不会每次重建 Runner 镜像；依赖无变化时不必重新下载大型 Python wheels、PyTorch 和 npm 包。

| 缓存 | 命中条件 | 命中后行为 |
|---|---|---|
| 前端 node_modules | package.json、package-lock.json、Node/npm 版本、CPU 架构指纹一致且 npm ls 验证通过 | 直接复用完整已安装目录，**不运行 npm ci** |
| npm 下载缓存 | npm integrity cache，随 frontend-work 卷保留 | 首次缺包时 npm ci --prefer-offline，已有 tarballs 不重复下载 |
| 后端 Python venv | requirements.txt 内容、Python ABI、架构、PyTorch 2.14.1+cpu、Playwright 1.62.0 指纹一致且 pip check 通过 | 直接复用 venv，**不重复执行 pip install** |
| pip 下载缓存 | 持久 PIP_CACHE_DIR | 首次/依赖变化时尽量重用 wheels 和包元数据 |
| 浏览器 Chromium | 在自定义 Runner 镜像的构建阶段安装 | 后续 CI 直接使用，无需每次 playwright install |
| Docker build 镜像层 | 独立 DinD 的 docker-data 卷 | 未修改的生产构建层复用；不需要每次完整下载/构建 |
| Nginx smoke 镜像 | DinD 本地镜像存在 | 检查 image inspect；首次才 docker pull |

首次冷启动或锁文件发生变更仍可能下载依赖。**后端 requirements.txt 中有不少 >= 范围依赖**，相同内容指纹会复用首次解析的已安装版本；需要有意识地升级依赖时，运行 install-backend-deps.sh --refresh 或提高 CI_BACKEND_CACHE_REV，并建议后续补严格 lock 文件以提升可复现性。缓存命中始终进行结构及依赖检查，而不是无条件跳过验证。

缓存不会自动无限清理其他项目；用下面的只读命令查看大小：

~~~bash
docker exec newshub-ci-runner-1 du -sh /ci-work/_work/.cache
docker exec newshub-ci-runner-frontend-1 du -sh /ci-frontend/_work/.cache
docker exec newshub-ci-docker-1 docker -H unix:///ci-docker/docker.sock system df
~~~

**不要**在 Job 正在运行时删除缓存，不要使用 docker system prune、docker volume prune 或删除 newshub-ci 的状态卷。缓存需要回收时先确认 Runner 空闲，删除指定过期的 keyed cache 目录，并保留当前使用的条目。

## 7. 环境和故障

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
