# NewsHub 自托管 CI：Omarchy + Docker

状态：**仓库配置已准备；尚未在用户 Omarchy 主机部署或实际验收**。不会修改新闻网站或生产数据库。无需 KVM 和虚拟机。

## 设计与边界

- 仅用于私有仓库 CoderLambert/news-aggregator 的 Repository Runner，名称 omarchy-newshub，自定义标签 newshub-ci。
- Ubuntu 24.04 Runner 镜像固定为 myoung34/github-runner:2.337.0-ubuntu-noble；预装 Python 3.12、Node 22、Docker/Compose、Playwright Chromium。
- 单独运行 docker:29-dind，以私有 Unix socket 通信。不挂载 Omarchy 宿主 /var/run/docker.sock；不发布 DinD 端口。
- runner-work 卷同时挂在 Runner 和 DinD 中的 **相同绝对路径** /ci-work/_work。这是为了让原有 Docker bind mount、Compose 和 G1 浏览器烟测正确找到工作目录。
- TMPDIR=/ci-work/_work/.ci-tmp 同样共享，避免源目录只存在于 Runner 容器而 DinD 看不到。
- runner-state 保存 GitHub 注册身份；docker-data 保存 DinD 构建缓存；状态和缓存均与其他 Docker 项目隔离。
- 默认资源：Runner 3 vCPU/6GB、DinD 2 vCPU/5GB；这是各自的上限，不是对整个项目严格保证的统一总配额。单个 Runner 一次只运行一个 Job。

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

安装命令会使用 gh API 获取**一次性注册 Token**，不要求复制长期 PAT，也不会把 Token 写入 Compose Environment。Token 只短暂保存于宿主机私有文件，注册成功后清空。已注册则复用保存的身份，不会重复注册。

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
- install 可重跑，若持久身份存在则跳过注册。
- stop 只停止 newshub-ci 项目；uninstall 只移除该项目的容器和网络，不删除 Runner 身份、Docker 数据卷，不操作其他 Docker 项目，也不从 GitHub 自动注销 Runner。
- 永久删除 Runner：在 GitHub 仓库设置中先手动删除该 Runner，确认无需旧缓存后再有针对性地删除明确命名的 newshub-ci 卷。禁止全局 prune。

## 3. 仓库启用和验收步骤

1. **先在 Omarchy 安装并确认 omarchy-newshub 为 Online**。
2. 在本 PR 等待 frontend 和 backend-and-release-gates 自托管检查通过。Runner 未注册之前 Job 会一直排队，不是代码测试成功。
3. 检查隔离 daemon、共享文件路径、Python/Node、Chromium、前后端测试、生产 Docker 构建及 G1 浏览器烟测。
4. 所有必要检查通过，才将本 PR 合并 main；随后可手动运行已添加的 smoke 工作流。

~~~bash
gh workflow run ci-runner-smoke.yml --repo CoderLambert/news-aggregator --ref main
gh run list --repo CoderLambert/news-aggregator --workflow ci-runner-smoke.yml --limit 3
~~~

注意：新建的 workflow_dispatch 工作流通常必须存在于仓库默认分支上，才能按文件名手动触发。PR 阶段先用其自动 CI 测试，不要为了触发手动 smoke 提前绕过审核合并。

现有 CI 工作流调整为：PR（同仓库、非 Draft）、main Push、手动 dispatch。移除了其他分支 Push 造成的 PR/Push 双重运行；更新提交时会取消过时 CI；工作流中没有 GitHub 托管 Runner 的回退标签。

## 4. 环境和故障

- Runner 与 DinD 都需要联网拉镜像和工具；不需要公网入站端口。
- 预装 Chromium，后端 venv 仍安装原工作流指定版本 playwright==1.62.0。
- 若 docker compose 无法启动 DinD，请检查当前 Omarchy 的内核、cgroup/overlay2、iptables 和资源。不要未经审核直接改为挂宿主 Docker Socket。
- 如果 DinD 内的 Docker bind mount 找不到 NewsHub 工作目录，检查两个容器挂载的 /ci-work/_work 路径一致及 TMPDIR 是否共享。
- 你当前 Omarchy 可用内存约 20GiB。本配置默认 6GB+5GB，避免长期工作时抢占其他开发程序内存；内存峰值需实际测量。
- 自托管计算分钟通常不按 GitHub-hosted Runner 计费，但工件/缓存可能产生其他使用费。如果 GitHub Billing 全局限制阻止调度，需要单独处理，本脚本不修改预算或支付方式。
- CI 只处理仓库合成环境，绝不接入生产 SQLite、PostgreSQL、Gitea 或 Tailscale 服务。

## English quick reference

Install a repository-scoped Docker self-hosted Runner on Omarchy without mounting the host Docker socket. Run bash ops/ci/manage.sh doctor and bash ops/ci/manage.sh install. Confirm Online in GitHub runner settings, review PR tests, then merge. The separate privileged DinD daemon shares a CI-only workspace for the real NewsHub Docker/browser smoke test. Do not run untrusted pull requests or unrelated repositories on this persistent Runner. Deployment and GitHub CI verification are pending until this configuration is executed on the user host.
