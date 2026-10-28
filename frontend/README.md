# NewsHub 前端源码开发

日常 UI 开发使用 Vite HMR，不需要构建 Docker 镜像，也不需要重建现有 app。
项目使用 React Compiler、TypeScript、Vite 和现有 npm lockfile。合并／发布门禁不变。

## 前置条件

- Linux、支持 pidfd 的 Python 3（CI 为 Python 3.12）和 **Node 22**。
- 当前 worktree 的 `frontend/node_modules` 已按 `package-lock.json` 准备好。
  启动器不安装 Node、不执行 `npm ci`、不回退到 `npx`。
- `NEWSHUB_DEV_NODE` 可以选择已安装的 Node 22；不设置时检查 PATH 中的 `node`。
  不会自动改变系统运行时，也不会覆盖其他 worktree 的依赖。
- 如果使用共享依赖，先核对 lockfile／运行时兼容性，不要对共享目录重新安装。

下面的命令在**仓库根目录**执行。Node 路径替换为本机已经存在的可执行文件，例如：

```bash
export NEWSHUB_DEV_NODE="$HOME/.local/share/mise/installs/node/22.23.3/bin/node"
test -x "$NEWSHUB_DEV_NODE"
```

## 模式 A：前端源码＋现有本地后端

```bash
export NEWSHUB_DEV_INSTANCE=ui
export NEWSHUB_DEV_PORT=5173
export NEWSHUB_DEV_API_TARGET=http://127.0.0.1:9527
bash scripts/news-dev start
bash scripts/news-dev health
# 浏览器打开 http://127.0.0.1:5173
# 编辑 frontend/src 后由 Vite 热更新
bash scripts/news-dev log       # Ctrl+C 只结束日志跟随
bash scripts/news-dev stop
```

- 默认绑定 `127.0.0.1`，端口默认 `5173`。端口冲突立即失败，不漂移到下一个端口。
- `/api` 由 Vite 代理，保留 SSE 超时和响应头处理；不会为了检查健康调用后端 API。
- `NEWSHUB_DEV_API_TARGET` 仅接受 loopback HTTP(S) origin（`127.0.0.1`、`localhost`、`[::1]`），
  不允许凭据、业务路径、查询或 fragment。通过进程环境设置，不使用浏览器端 `VITE_*` 变量。
- 当前验收环境的 `9527`、`19527` 可能指向同一个 app；不要抢占这些端口或重启该 app。
- **这不是数据沙盒**：前端仍可修改现有后端数据、提交任务或触发收费调用。
  只做获授权的验收操作；新后端源码并不会因此生效。
- 浏览器 origin 必须在后端 CSRF 信任名单内。端口不同不等于 Cookie 隔离；独立后端需独立浏览器配置文件。

## 模式 B：前端源码＋独立的源码后端（后端须另行准备）

```bash
export NEWSHUB_DEV_INSTANCE=isolated-api
export NEWSHUB_DEV_PORT=25173
export NEWSHUB_DEV_API_TARGET=http://127.0.0.1:29527
bash scripts/news-dev start
```

启动器**只管理前端**，不会启动 Django、迁移数据库或创建依赖服务。模式 B 使用前必须完成：

1. 独立、兼容的 Python 3.12 环境和任务专用数据库／缓存／运行目录。
2. 受控环境白名单；不要加载现有根目录或 `backend/.env` 的凭据。
   Django 开发模式会自动读取它们，详见 [`settings.py`](../backend/newsaggregator/settings.py)。
3. 显式设置独立 `DJANGO_DB_PATH`、`CHROMA_DATA_DIR`、`TTS_CACHE_DIR`、deployment-id 路径。
   **不得使用现有 `backend/db.sqlite3` 或复制运行中的 DB/WAL。**
4. 后端监听 `127.0.0.1:29527`，CSRF 信任 `http://127.0.0.1:25173`，使用独立浏览器配置文件。
5. RSS／channel／embedding worker 按需启动，隔离锁、heartbeat、账号及运行状态；源码变化后独立重启。
   Redis／Gateway 在现有 app 网络命名空间内，不代表宿主可以直接连接。

Django `runserver` 有代码重载；`start_waitress.py` 没有。不要向 runserver 预设 `RUN_MAIN=true`，
它是 Django 重载器内部标志。长任务调试可使用受控的 `--noreload` 会话，避免保存代码中断执行。
当前阶段不提供一键后端启动，也不自动开启真实 AI／订阅调用。

## 命令和状态隔离

兼容命令：`start`、`stop`、`restart`、`status`、`health`、`build`、`log`。

| 环境变量 | 默认／说明 |
|---|---|
| `NEWSHUB_DEV_NODE` | PATH 中的 `node`；必须为22 |
| `NEWSHUB_DEV_PORT` | `5173`，允许1024～65535 |
| `NEWSHUB_DEV_API_TARGET` | `http://127.0.0.1:9527` |
| `NEWSHUB_DEV_INSTANCE` | `frontend`；1～48个字母、数字、`_`、`-` |
| `NEWSHUB_DEV_STATE_DIR` | `${XDG_STATE_HOME:-$HOME/.local/state}/newshub-dev`；绝对、非符号链接路径 |

状态目录下以 worktree 绝对路径哈希＋instance 分隔，每个实例独立保存 `process.json`、`vite.log` 和
Vite 缓存。目录0700、文件0600。使用 Vite 的 native ESM config loader，避免向共享 node_modules 写入配置打包临时文件；
配置文件或其导入依赖变化后显式 `restart`，普通应用源码仍使用 HMR。
不同端口的并行会话使用不同 instance；同一实例修改配置后用 `restart`。
保留相同的 instance／state 配置才能操作原会话。

`health` 检查已记录的进程身份和它拥有的 loopback listener，**不证明后端可用**。
停止使用 Linux pidfd、启动时间、boot-id、可执行文件、命令行和 cwd 验证，不用 `pkill` 或进程名匹配。
陈旧／身份不符的记录会拒绝 start/stop/restart；应先人工核对进程，确认后仅移除错误的该实例
`process.json`。旧 `logs/vite.pid` 和 `frontend/.dev-pids` 不会被接管，旧会话需单独核对处理。

`status` 保留原接口（未运行也返回0）；`health` 未运行返回非零。
`build` 仍执行 `vite build` 并保留退出码，仅在需要构建前端产物时显式调用，不作为每次保存代码的步骤。
`restart` 只操作这个实例，不启动或重启任何后端、容器或其他项目。

## 定向验证与交付

```bash
# 标准库合成启动器回归；用已有 Python3.12 环境执行，不加载 Django conftest。
NEWSHUB_TEST_NODE22="$NEWSHUB_DEV_NODE" /path/to/python3.12 tests/backend/test_news_dev.py

# 根据本次行为改动选择前端测试，不默认跑所有测试。
# 从 frontend/、在兼容 Node22 环境中执行：
# npm run test:run -- tests/<受影响测试文件>
```

源码 HMR → 语义影响定向测试 → 本地验收 → 用户授权后 Draft 快检／Ready 完整门禁。
本启动器不推送、不触发 CI，不取代 CSRF、权限、流式终态或镜像／发布验收。

不要将 [`dev-server.sh`](dev-server.sh) 的 build/watch＋preview 当作 HMR 主入口；其宽泛停止逻辑不适合并行任务。
[`local-frontend-preview.sh`](../scripts/deploy/local-frontend-preview.sh) 用于已授权的验收发布，会构建产物并重建 app 网络单元，
也不应在每次保存代码后调用。
