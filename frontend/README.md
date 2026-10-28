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

## 模式 B：前端源码＋独立源码后端

在**当前源码 worktree 根目录**执行。后端沿用 `news-server`，但必须显式带 **`dev`**：
旧 `news-server start` 是历史入口，不具备下面的隔离保证。

```bash
# 选择已存在、完整匹配 backend/requirements-ci.lock 的 Python 3.12 环境。
export NEWSHUB_DEV_PYTHON=/path/to/compatible-venv/bin/python
export NEWSHUB_DEV_INSTANCE=isolated-api
export NEWSHUB_DEV_STATE_DIR="$HOME/.local/state/newshub-dev"
export NEWSHUB_DEV_BACKEND_PORT=29527
export NEWSHUB_DEV_FRONTEND_PORT=25173
export NEWSHUB_DEV_PORT="$NEWSHUB_DEV_FRONTEND_PORT"
export NEWSHUB_DEV_API_TARGET="http://127.0.0.1:$NEWSHUB_DEV_BACKEND_PORT"

# 仅首次初始化，或明确要应用新迁移时运行；只操作任务所有的合成数据库。
bash scripts/news-server dev init
bash scripts/news-server dev start
bash scripts/news-dev start
bash scripts/news-server dev health
bash scripts/news-dev health
# 用独立浏览器配置文件打开 http://127.0.0.1:25173
# backend Python 保存后 Django 自动重载；frontend/src 保存后 Vite HMR。

bash scripts/news-server dev log   # 输出最近32KiB，不跟随、不阻塞控制器
bash scripts/news-dev stop
bash scripts/news-server dev stop  # 精确停止本实例父/子进程，保留合成数据
```

### 默认账号和模型候选（仅隔离开发）

`news-server dev init` 迁移完成后，首次创建以下**公开开发默认值**：

| 账号 | 权限 | 初始开发密码 | 私有模型候选 |
|---|---|---|---|
| `admin` | staff + superuser | `12345678` | `deepseek-flash` |
| `user` | 普通用户，无管理员权限 | `12345678` | `deepseek-flash` |

这不是生产账号策略。仅 `newsaggregator.dev_settings`、任务所有的外置 SQLite 和离线边界允许初始化；
不会修改全局密码校验。请勿在生产或对公网开放的环境使用这些弱口令。

两个账号各有独立 `UserAIConnection` 和模型配置，复用 `deepseek_default` 受信路由。
现有 Proxy 对 `deepseek/deepseek-flash` 使用 `https://api.deepseek.com`，不在这里额外拼接 `/v1` 或新建 HTTP 客户端。
连接初始禁用、能力未知，不创建探测成功记录或业务任务默认绑定；**候选已保存不等于模型/Key 可用**。
此模式仍保持 AI/BYOK 和外部 I/O 关闭，AI 设置接口也仍受该开关保护；联网验证、Gateway/Redis 接入及业务启用需另行授权。

普通 `init` 不要求输入 Key：未提供安全输入时，输出每个账号 `key: missing`，完成账号和候选配置即可。
要导入到两个账号，先停本实例，再显式运行隐藏输入：

```bash
bash scripts/news-server dev stop
bash scripts/news-server dev import-key  # 仅交互终端隐藏读取，不在普通 init 自动询问
```

也可由密码管理器/受保护编辑器准备一个**仓库外、本人所有、0600、无软/硬链接**的专用文件，内容只含一行 Key：

```bash
# 变量只保存文件路径，不保存 Key；不要将真实 Key 放入命令行、.env、代码或日志。
export NEWSHUB_DEV_KEY_FILE=/absolute/private/development-key
bash scripts/news-server dev init        # 首次创建时加密导入；已有配置则保留
# 或初始化后只补充仍未修改、从未导入过凭据的候选：
bash scripts/news-server dev import-key
```

入口以私有 stdin 管道传递内容，子进程环境不携带 Key 或文件选择器。
凭据用现有 owner/连接/版本绑定加密存储，两账号密文不同；首次补入旧空候选会推进 credential epoch/version/revision。
现有 Key 即使与输入不同也不覆盖；撤销、删除、改过目标/模型或 epoch 的候选不会自动恢复。
导入源文件由用户保管/移除，启动器不擅自删除；后续开发只需显式提供这个私有路径，仓库不会保存实际 Key。

重复 `init` 不重置密码、提升权限、改名或覆盖模型、凭据、任务偏好。
实例私有的 `defaults.json` 只记录用户/连接/模型身份，不含密码、Key 或密文；同名未知账号、同 owner 的连接冲突、
删除后替换的对象、缺失/不完整回执均拒绝自动接管。初始化中断时保留证据，先检查或使用新的 instance，
不要删除回执来冒充首次初始化。输出 `verification: not_run` 始终不代表真实 provider 验收。

### 后端隔离契约

- `NEWSHUB_DEV_PYTHON` 未指定时仅检查本 worktree 的 `backend/venv/bin/python`。
  每次 init/start 校验 Python 3.12 和完整 CI lock，不回退到宿主 Python，不自动安装。
  兼容环境优先复用；缺失时才在独立/内容寻址环境中按原 lock 一次性准备，不升级依赖或覆盖共享 venv。
- 控制器复用 [`news_dev.py`](../scripts/news_dev.py) 的私有文件、锁、身份和 pidfd 原语。
  后端数据位于同一 worktree-hash＋instance 目录的 `backend/` 子目录；前端状态不会被 stop/restart 接管。
  运行目录必须在 **Git worktree 之外**、无 symlink；目录0700、文件0600，拒绝 hardlink/外来文件。
- `init` 创建所有权标记、独立随机开发密钥和新 SQLite，然后显式迁移；不接管已有未知 DB，
  不读取/复制真实 `.env`、`backend/db.sqlite3` 或 WAL。已有本任务合成 DB 可在停服后显式再次 `init`。
  `start` 从不隐式迁移；迁移失败保留任务证据，不自动清库。
- [`dev_settings.py`](../backend/newsaggregator/dev_settings.py) 在导入普通设置前验证所有权并重建白名单环境。
  不继承 provider、Redis、Gateway、代理或 Python 路径/重载标志；dotenv 在此模式明确禁用。
  **不要给入口传 `DJANGO_DB_PATH`、`CHROMA_DATA_DIR` 等应用数据路径**：误传时拒绝，不会静默访问它们。
  DB、Chroma/TTS/cache、临时目录、锁、heartbeat、deployment-id 均固定到本实例；普通运行设置不受影响。
- 仅绑定 `127.0.0.1` 的指定新端口；冲突拒绝启动，禁止使用9527/19527。
  CSRF 精确信任上述两个 origin，不用通配符；CORS 也限定为这两个 origin。
  会话 Cookie 按实例区分，但 SPA 的 `csrftoken` 仍是 host 作用域：**不同端口不隔离 Cookie，必须使用独立浏览器配置文件**。
- 默认允许本地合成账号/普通页面操作，但 AI/BYOK、订阅连接/推理、语义搜索、TTS、模型预加载及自动内容worker关闭。
  不启动 RSS/channel/embedding worker，也不接入真实 Miniflux/Redis/Gateway；网络连接及非重载子命令会被开发配置拒绝。
  RSS同步、正文抓取等依赖外部服务的路径不可用于真实验收。此保护用于防误操作，不是对抗恶意源码的安全沙盒。
- Django 自己设置 reload-child 的 `RUN_MAIN`；入口不预设它。停止时先验证并暂停重载父进程，
  再逐一校验/用 pidfd 停止子进程，最后结束父进程，不用 `pkill`/`killpg`。
  外来、陈旧或复制自其他实例的记录失败闭锁；先核对具体实例，不用删除目录或杀所有 Python 进程解决。
  外部强杀父进程留下的未知孤儿不被自动接管。

`dev` 支持 `init/import-key/start/stop/restart/status/health/log`。后端默认端口29527、前端受信端口25173；
其他 instance/state 变量与前端一致。配置变更用 `restart`；模型/长任务和依赖服务接入属于另行授权的验收范围。
`health` 只证明本实例进程身份和 listener，不代表全部API、worker、RSS或provider健康。

## 前端命令和状态隔离

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
# 后端生命周期合成进程负例＋真实settings隔离契约，不读取现有数据。
# 使用完整CI-lock环境，避免真实settings用例因缺少Django被明确SKIP。
"$NEWSHUB_DEV_PYTHON" tests/backend/test_news_backend_dev.py
# 真实Django、一次迁移的合成schema及独立SQLite backup；账号/owner/epoch/幂等/脱敏回归。
"$NEWSHUB_DEV_PYTHON" tests/backend/test_dev_bootstrap.py

# 根据本次行为改动选择前端测试，不默认跑所有测试。
# 从 frontend/、在兼容 Node22 环境中执行：
# npm run test:run -- tests/<受影响测试文件>
```

源码 HMR → 语义影响定向测试 → 本地验收 → 用户授权后 Draft 快检／Ready 完整门禁。
本启动器不推送、不触发 CI，不取代 CSRF、权限、流式终态或镜像／发布验收。

不要将 [`dev-server.sh`](dev-server.sh) 的 build/watch＋preview 当作 HMR 主入口；其宽泛停止逻辑不适合并行任务。
[`local-frontend-preview.sh`](../scripts/deploy/local-frontend-preview.sh) 用于已授权的验收发布，会构建产物并重建 app 网络单元，
也不应在每次保存代码后调用。
