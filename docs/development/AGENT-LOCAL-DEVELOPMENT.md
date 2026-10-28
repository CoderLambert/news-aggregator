# Agent 本地开发与任务调度指南

任务调度、源码开发和本地交付先读本文。它串联已有入口，不新增执行平台或授权：约束以[根规则](../../AGENTS.md)、模块规则和当前任务为准；启动参数/隔离细节以[源码开发说明](../../frontend/README.md)及实际脚本为准。旧审计背景见[工程标准](CODEX-AGENT-STANDARD-2026-10-18.md)。

## 范围与停止条件

开始前限定本任务必要的文件、调用链、测试及可检查的停止条件；已有证据足以满足验收时立即交付，不为追求“全面”继续排查。旁支或历史问题只记录，不顺手修复。确需扩大范围时，先说明它与当前任务直接关联的证据、拟增加的工作及原因，征得用户同意后再继续。

## 1. 领取任务：先确认边界，再选择执行方式

1. **新批量需求**：保留原任务 ID，按可验收结果拆任务，用 `add_task` 入队后结束当前轮，由看板串行派发。写清依赖、基线、允许文件、验收和禁止动作，避免拆成没有独立结果的文件级碎片。
2. **已收到 `[看板任务 #N]`**：直接完成该项，不把同一任务重新入队。非简单任务用 `plan_update` 记录步骤、完成条件、File Touch List、风险/回滚；阻塞时记录具体缺失条件，不伪报完成。
3. **先做只读核对**：工作树列表、实际 branch/base/head、上游/远端引用及 outgoing commits、暂存/未暂存/未跟踪差异；不输出含凭据的 remote URL。读对应 AGENTS、源码和测试，再确定最小改动。`cd` 不代表子规则已自动加载。
4. **有本地写入授权后隔离实现**：用 `worktree` 工具先 list，再 create（指定批准的基线 SHA、独立分支/路径）和 switch。主工作区有用户修改时保留原样；不要 reset/clean/stash 或改历史。动手前用 `claim_files` 声明文件；认领是协调提示，不是互斥锁。

完成条件：任务 ID、绝对工作树路径、基线、写入范围、验证范围和授权边界均可明确回答。后续若 HEAD/dirty 状态出现不明变化，先停下核对归属。

### 调度与委派

当前 agent 对计划、实现、核验和交付负责，可直接做测试和本地提交。日常开发不强制模型、思考等级或代理数量；不存在“必须等某固定代理才能继续”。按[项目测试 Skill](../../.agents/skills/newshub-test-acceptance/SKILL.md)和[提交 Skill](../../.agents/skills/newshub-stage-commit/SKILL.md)执行；同名全局旧副本不是替代依据，也不因此改全局配置。

| 情况 | 选择 | 收回结果时检查 |
|---|---|---|
| 小范围修改、信息已齐 | 当前 agent 直接完成 | 行为、回归、完整差异和边界 |
| 跨模块未知接口/风险 | 可委派只读探索或设计 | 源码位置、反例、结论与尚未证明的假设 |
| 真正独立的实现范围 | 可委派实现 | 文件归属、接口兼容、无越权副作用、可复现测试 |
| 安全边界或复杂交付 | 可委派专项审查 | 具体失败路径与测试，而非仅“看起来正确” |

委派前先说明所选模板及适用原因，给出单一目标、输入、工具/文件范围、必须做/不能做、验收与输出。等待被委派决定的问题解决后再实现依赖它的工作；复用同一会话追踪，不反复派发副本。返回的“PASS”要核对命令、候选和实际产出，不能直接转述成自己的验证。

每批最多两个独立写目标；共享 schema、routes、迁移、lockfiles、fixtures、同一 Git index/refs 必须有明确单一写入责任。看板串行不等于可以任意启动并发子任务。Worktree 只隔离源码：DB、端口、卷、缓存、浏览器配置和服务仍须分开。与任务有关的既有服务只有核实所有权、源码版本及合成数据边界后才可复用。

状态区分：**待完成**是已排队；执行中记录计划与证据；**待审核**是本轮产出可供审核，不等于用户验收、远端 CI 或上线。当前派发任务交付后结束本轮，由系统转待审核；缺条件须显著标 `BLOCKED/NOT_RUN`。用户要求修复则回到本地实现与验收，不沿用上一阶段的推送许可。

## 2. 准备环境：复用依赖，隔离可变数据

- 先核对 CI 运行时与 lockfile：当前为 Python 3.12 / Node 22。已兼容的 `backend/venv`、`frontend/node_modules` 或内容寻址缓存优先复用；目录名字相似不是兼容证据，记录实际版本与 lock 指纹。
- 可使用已核对的依赖链接；不要覆盖已有链接，或在共享环境里重装、升级依赖。依赖缺失才考虑在独立缓存按原 lock 一次性准备，且先确认下载/网络授权；缺授权就报告阻塞。详见[环境复用顺序](../../.agents/skills/newshub-test-acceptance/SKILL.md)。
- 当前源码工作树必须无真实 `.env`/凭据文件（核对存在性，不打印秘密）；不从 main 或旧实例复制真实 DB/WAL、环境文件或用户数据。选择仓库外的任务状态目录、唯一 instance 和空闲 loopback 端口。
- 普通源码变更用 HMR/重载，不每次安装依赖或构建镜像。依赖升级、构建输入和缓存失效另按[构建合同](../../ops/ci/build-release-policy.md)处理；不能靠全局清缓存“修复”。

完成条件：运行时/依赖匹配已记录，数据/端口/浏览器隔离已选定，无需借用真实环境。仅写文档时不需要搭建或启动业务服务。

## 3. 启动源码开发：明确使用独立模式

完整参数表、默认账号和隔离规则只维护在[源码开发说明](../../frontend/README.md)。以下是 agent 常用配方，不是现有生产/验收服务操作命令。接口有疑问时查[前端入口](../../scripts/news_dev.py)、[后端入口](../../scripts/news_backend_dev.py)及[隔离环境实现](../../backend/newsaggregator/dev_runtime.py)。

先进入批准的源码 worktree 根目录，设置两个**已核对且存在**的可执行路径（不在这里安装）：

```bash
# backend/venv 已准备好时可用此路径；否则替换为已验证的兼容缓存环境。
export NEWSHUB_DEV_PYTHON="$PWD/backend/venv/bin/python"
# 替换为本机实际存在的 Node 22 可执行文件。
export NEWSHUB_DEV_NODE=/absolute/path/to/node22
test -x "$NEWSHUB_DEV_PYTHON" && test -x "$NEWSHUB_DEV_NODE"
"$NEWSHUB_DEV_PYTHON" -I -B ops/ci/check-backend-lock.py \
  backend/requirements.txt backend/requirements-ci.lock --installed
"$NEWSHUB_DEV_NODE" --version
```

以上任一步不符合条件就停止准备，不继续启动。下面另开一个干净的开发 shell，避免继承真实服务环境；将 `t123` 换成本任务 ID，两个端口必须空闲、不同，不能用 9527/19527：

```bash
env -i HOME="$HOME" \
  PATH="$(dirname "$NEWSHUB_DEV_PYTHON"):$(dirname "$NEWSHUB_DEV_NODE"):/usr/bin:/bin" \
  NEWSHUB_DEV_PYTHON="$NEWSHUB_DEV_PYTHON" NEWSHUB_DEV_NODE="$NEWSHUB_DEV_NODE" \
  NEWSHUB_DEV_INSTANCE=t123 \
  NEWSHUB_DEV_STATE_DIR="$HOME/.local/state/newshub-dev" \
  NEWSHUB_DEV_BACKEND_PORT=29527 NEWSHUB_DEV_FRONTEND_PORT=25173 \
  NEWSHUB_DEV_PORT=25173 NEWSHUB_DEV_API_TARGET=http://127.0.0.1:29527 \
  bash --noprofile --norc
```

在这个 shell 中执行以下生命周期；跨工具调用时保留该 shell。若工具每次执行后销毁 shell，则每次用相同的 `env -i` 参数包裹实际命令，而不是启动一个立即退出的空 shell。不要换了 instance/state/worktree 再宣称停掉了原实例。

```bash
# 第一次初始化；以后仅在停服后、明确要应用迁移/默认初始化时运行。
bash scripts/news-server dev init
bash scripts/news-server dev start
bash scripts/news-dev start
bash scripts/news-server dev health
bash scripts/news-dev health
# 用本任务独立浏览器配置文件打开 http://127.0.0.1:25173

# 状态检查；status 的退出码0本身不证明健康。
bash scripts/news-server dev status
bash scripts/news-dev status
# 修改配置需重启相应实例；普通 Python 保存由 Django 重载，UI 源码用 HMR。
bash scripts/news-server dev restart
bash scripts/news-dev restart

# 收尾：只停止当前实例，保留数据。
bash scripts/news-dev stop
bash scripts/news-server dev stop
```

- **旧 `news-server start` 不是隔离入口**。前端默认代理若未设置会指向既有 9527 服务；只启前端接旧后端不是数据沙盒，也不会加载新后端源码。只有获准操作该服务才使用说明中的模式 A。
- `NEWSHUB_DEV_FRONTEND_PORT` 与 `NEWSHUB_DEV_PORT` 必须一致；`NEWSHUB_DEV_API_TARGET` 指向所选后端。CSRF/CORS 精确对应两个 origin，改端口后同步配置并 restart。不同端口不隔离 Cookie，尤其 `csrftoken`，故要独立浏览器配置文件。
- 后端重建白名单环境、禁用 dotenv，并固定外置合成 SQLite/cache/tmp/锁等路径；不要传 `DJANGO_DB_PATH` 等应用数据覆盖变量。启动不隐式迁移。`RUN_MAIN` 由 Django 自己处理，不由调用者强塞。
- `health` 只证明进程身份和它拥有的 listener，不证明全部 API、RSS、worker 或 provider 可用。停止按 Linux pidfd/启动身份核对父子进程；不要以进程名群杀、删状态目录或重启既有 app 来解决冲突。
- 需排错时 `bash scripts/news-server dev log` 输出有界日志；`bash scripts/news-dev log` 持续跟随，Ctrl+C 仅结束跟随。保留原退出码及脱敏证据。

完成条件：两端 health 与本次实际修改面的本地验收分别通过；记录源码候选、instance、端口、状态目录。任务结束说明哪些资源已停、哪些获准保留。

## 4. 默认账号和 Key：配置成功不是推理授权

首次 `dev init` 创建开发管理员 `admin` 和普通用户 `user`；公开开发密码见[默认账号说明](../../frontend/README.md)。只用于隔离开发，不改变生产账号策略或全局密码验证。

两账号分别拥有私有 DeepSeek 连接和 `deepseek-flash` 候选，复用既有 `deepseek_default`/Proxy 路由及 `https://api.deepseek.com`，不自行追加 `/v1` 或另建 HTTP 客户端。连接禁用、能力未知、无已验证业务任务绑定；候选存在不是厂商支持或 Key 有效性的证据。此 profile 的 AI/BYOK、worker 和外部 I/O 仍关闭，属于防误操作保护，不是对抗恶意源码的安全沙盒。

普通 `init` 没有安全 Key 输入也可完成，明确报告 `missing`。只有任务授权导入时，在同一开发 shell 停本实例后执行 `bash scripts/news-server dev import-key`，由用户在隐藏 TTY 输入；无 TTY 则由用户提供仓库外、本人所有、0600、无软/硬链接的专用单行文件，设置 **`NEWSHUB_DEV_KEY_FILE` 为路径而非 Key**。详见[导入方法](../../frontend/README.md)。不要在聊天中再次索要明文，也不从聊天、真实 `.env` 或旧服务配置复制秘密到参数/代码/文档/测试/日志。

入口仅经私有 stdin 传递，复用 owner/连接/版本绑定的加密存储；不是共享站点 Key fallback。没有安全输入就交付入口并标“待导入”，不声称已配置真实凭据。导入不授权联网验证或付费推理，更不授权关闭 I/O 保护；需要这些能力应单独明确任务、环境及授权。

重复 `init` 保留已有密码、权限、Key、模型和任务偏好；首次补入未改动空候选推进 epoch/version/revision。已有 Key 不覆盖，撤销/删除/改过配置的对象不自动恢复；同名未知对象或不完整身份回执拒绝接管。保留冲突证据，核对归属或另选新实例，不删除回执假装首次初始化。

## 5. 验证、提交、等待审核

按[验证 Skill](../../.agents/skills/newshub-verify/SKILL.md)选择语义影响最小充分集：UI 看实际页面与相应组件；CLI 看真实命令；跨 owner/版本/SSE 的修改补负例和消费者。源码循环为：最小修改 → HMR/重载或廉价复现 → 定向检查 → 本地结果 → 本地提交 → 用户验收。不要把全部测试/镜像构建插入每次保存。

| 本次范围 | 最小起点（仍须结合实际影响） |
|---|---|
| 文档 | 本地链接、事实/命令、diff 检查；无需为文档启动服务 |
| AGENTS/Skills 入口或规则 | 下方结构检查和既有规则回归；预算不因新入口而提高 |
| 源码启动器/默认初始化 | README 中对应 `test_news_dev.py`、`test_news_backend_dev.py`、`test_dev_bootstrap.py`；合成环境、真实命令面验证 |
| 普通前后端行为 | 对应现有测试和本地场景；不是默认跑整套 pytest/Vitest |

规则变更从仓库根执行（使用已有兼容 Python 3.12；只需标准库）：

```bash
python3 ops/ci/agent_rules.py
python3 -m unittest discover -s ops/ci/tests -p 'test_agent_rules.py'
git diff --check
```

证据可复用，但必须仍匹配源码、配置、依赖、测试范围与候选；执行者换了不代表需要重跑，代码或 base 变化也不代表旧绿灯仍有效。Bug 尽可能记录同一用例红/绿；无法安全补前置证据则标 `NOT_RUN`。失败先保留原始结果和原因，不弱化断言、不循环重试刷绿。结构检查不能证明所有 agent 会自动发现或遵守文档。

检查通过后按[本地提交合同](../../.agents/skills/newshub-stage-commit/SKILL.md)由当前 agent 直接提交或按需委派：再次核对实际 refs/差异，只暂存本任务文件或已审查 hunks，复核 staged diff/check 和证据指纹；尊重更新的只读/no-commit 指令。排除用户修改、依赖链接、运行状态和秘密；不把不明 outgoing commits 一并送往远端。

本地完成后等待审核。推送/建 PR/触发 CI 需用户明确接受本功能进入该阶段或明确要求现在执行，不能用“已修复/继续”或上一功能许可代替。获准后按[现有分流](../../ops/ci/change-routing.md)：Draft 快检不是合并依据；Ready 要用户接受及适用完整 CI/`merge-gate`，核对最新 head/base；修复前回 Draft。暂停测试则停止交付、回 Draft并取消相关待运行/运行中 CI，包括转换触发的运行，报告实际状态。

Full suite、provider、image/G1、合并和部署均在各自授权范围内进行。按需委派不覆盖[本地镜像专用机制](pi-local-image-builder.md)的独立授权与 native Luna/no OMP 合同；不要为了日常源码开发调用它。CI 真相仍是现有 workflow/classifier，本文不再复制路由表或提供一键发布脚本。

### 交付最小记录

- 原任务 ID、允许范围/实际文件、工作树/分支、精确 base/head、剩余 dirty 和排除项。
- 执行/复用的命令、环境身份与候选指纹、范围、退出码；`PASS/FAIL/BLOCKED/NOT_RUN/SKIPPED` 分列。
- 实际服务与资源收尾、凭据导入/验证状态、真实 CI 状态；合成测试不冒充 provider、生产或人工 UAT。
- 风险、下一项所需授权、回滚。代码可通过经审查的 revert 回退，**不会自动删除实例数据、撤销外部 Key 或回滚数据库**。
- 用户可用的命令/路径；有报告或截图时展示文件，而不仅贴路径。然后结束派发任务，等待审核。

## 6. 阻塞时做什么

| 现象 | 下一步 | 保持的边界 |
|---|---|---|
| Node/Python/lock 不匹配 | 核对版本和完整 installed lock，查已有匹配缓存 | 不覆盖共享依赖；缺安全前提则 BLOCKED |
| 端口被占或身份记录不匹配 | 核对原 instance/state/worktree、进程身份；新实例选新端口 | 不接管外来进程，不群杀/删库 |
| 登录/CSRF 失败 | 核对代理目标、两个 origin、UI 端口一致性和独立浏览器配置 | 不通配 CSRF，不借用真实用户会话 |
| 默认初始化冲突/回执 pending | 保留 DB/回执/日志，检查本任务所有权与中断点 | 不提升同名外来用户，不猜测归属 |
| Key 缺失或无 TTY | 交付受控入口并报告待输入 | 不用聊天秘密、站点 fallback 或示例 Key 冒充真实配置 |
| AI 接口被关闭、外部 I/O 拒绝 | 确认这是隔离 profile 的边界；确需联调时申请独立授权 | 不关闭保护来“通过”测试 |
| 检查失败/无法证明候选匹配 | 分类原因，保留退出码；修正后定向复测 | 不标 PASS，不推动下一交付阶段 |

例如，只改列表样式：读 frontend 规则 → 确认允许文件 → 复用依赖和隔离模式 → HMR 看页面 → 相关测试 → 本地提交与截图 → 等用户验收。只改本文则做事实/链接和规则检查，不启动页面。需要真实模型翻译时，先界定 provider 授权、owner 绑定及独立验收环境，不能把离线默认候选当现成业务模型。

## 7. 本轮历史快照（任务 #8 基线，不是永远成立的 main 状态）

| 原任务 | 本地提交 | 本轮交付范围 |
|---|---|---|
| #4 | `154be99e075ad2d324f9758a6daa191399d334e1` | 安全 Vite/HMR 入口 |
| #5 | `1040828230da42c8d69170a8fccce9ffe7b54622` | 项目级可选委派与执行自主性 |
| #6 | `d0061bdb2a5c0b4048596d736e24e0224c13c364` | 外置合成数据的 Django 重载开发模式 |
| #7 | `1491c468f56eb2d012cbe4a58fa8c2f33891dbc7` | 幂等开发账号、私有模型候选和安全导入入口 |

任务 #8 开始核对时，以上串联提交在本地任务分支，main 为 `2d58493fbd2cc95beae141ac05654e514a31fae4`，未因本轮而推送/合并；main 有七项既有暂存修改，#6/#7 仍有本地依赖链接，均须保留。#7 交付记录为本地回归/登录检查通过、测试服务已停；真实 Key 未导入，模型未联网验证，业务调用关闭。后来 agent 应重新检查实时 refs、数据/进程归属和最新授权，不把该快照当成永久状态或新的禁令。
