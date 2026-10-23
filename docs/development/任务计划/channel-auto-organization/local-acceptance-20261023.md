# 分组整理：恢复后的本地交付与验收

## 范围与精确基线

- 原编号：AG-04.1 / AG-05.1 / AG-06.1 / AG-07.1；续跑原看板 #7–#9，恢复前置 #12/#13。
- 基线：`f97c34e305522446efc4f53645c5d4dfb4f1f444`，不是最新远程主线的声明。
- 持久 worktree：`/home/lambert/githubRepos/lambert/news-aggregator-channel-organization-recovered-20261023`。
- 本地分支：`fix/recover-channel-organization-20261023`；提交状态以实际 Git 记录为准。
- 主工作树 `main` 的现有 SQLite 未纳入本功能；历史审计文档已由独立任务本地提交为 `5f3c00fe3fcc006d8bf86d2acfbbbc5cc6ed4703`。不推送、不建 PR、不执行 CI 或生产操作。
- 用户于 2026-10-23 明确表示将 `d93beac118be31767097e251f6447edcc59be87c` 对应的本地预览“当作通过”；这是当时候选的本地体验验收，不扩大为真实 Provider、完整 CI、部署或生产授权。看板 #21/#22 已根据后续反馈改变智能整理交互，当前 UI 候选需重新体验确认。

## 恢复事实及限制

继续任务时，原 `/tmp/newshub-channel-organization-20261022` 与 `-ui` 目录及浏览器证据已经不存在，Git 仍保留 worktree 登记及原分支。没有把这推断为确定的重启原因，也没有 prune 原记录、改写原分支或复制业务数据库。

从现存 Pi/Codex 操作日志提取文本变更，在只允许字符串与虚拟文件操作的恢复解释器中重放：不运行日志中的 shell 命令或任意 Python/JavaScript。已恢复原有 22 个源码/测试/合同文件（包含迁移），并将最终前端副本核对为一致。`0084` 与日志中完整打印的最终迁移逐字节相同；其他文件没有原工作树最终哈希可供独立证明，属于按成功操作重建，**不声称所有文件已取得原始最终哈希一致证明**。恢复后的实现重新执行了下列检查，而非套用旧 PASS。

恢复包保存在：`/home/lambert/.local/share/newshub/channel-organization-recovery-20261023/`，含恢复解释器、来源索引、逐次写入审计、`recovered-source-manifest.json`、历史预览脚本文本。清单绑定的是恢复时源码；本文及计划更新随后单独核对。临时路径中的历史 RED/PASS 只作历史记录，不能替代本次验证。

## 看板 #23：用户验收与队列顺序记录

- 用户对 `d93beac118be31767097e251f6447edcc59be87c` 对应本地预览的体验验收为 **PASS**。用户指出“旧版主题编辑器仍有原生下拉”“新旧流程变化不够明显”；这些反馈不阻塞当次验收，但必须如实保留，不能改写为“未发现问题”。
- 按用户指定顺序，先由看板 #19 解决共享 Git 元数据提交阻塞，再执行 #20 只读复现与入口诊断；随后 #21 以 `91e1afde966237145c62278d8943aae27fa620ff` 修正主流程层级，#22 以 `c76038268d7fe66971bed31271c74915bd9cb6c4` 完成 shadcn 搜索选择器规范修正。#20 没有修改业务代码。
- #21/#22 是当次验收之后的行为与交互变更，因此原 PASS 不自动覆盖当前 `c760382` 候选；当前候选的用户重新验收仍为 **PENDING**。任何后续行为改动同样必须重新提供本地验收，不能沿用旧截图、旧 bundle 指纹或旧接受结论。
- #23 仅归档上述验收边界与已完成队列事实，不改变运行时行为，也不授权 push、PR、CI、真实 Provider、生产或部署。

## 历史平面候选的本地行为

- 新订阅按本人已有分组整理；可信资料明确匹配时 auto 可自动加入，不可靠资料/AI 结果保留人工确认，不创建或改名分组。
- 首次个人激活边界独立于旧 topics 的 `active_since`；历史订阅留给显式整理。部分保存、关闭/恢复不会移动已经建立的个人边界。
- owner 调度失败隔离并轮转，单 owner 有界批次；未知已派发 AI 不自动付费重发。
- 列表返回 `{results,page,page_size,count,has_more}`，固定 30 条，前端与后台同时更新；按 owner/target 隔离，旧 pending/ready 可翻页到达。
- 批量加入/移动/移出保留订阅；未知批量结果在同一 SPA 生命周期的页面离开/重挂载后仍阻断写入，核对两条私有读取成功后才解除。该内存屏障不被描述为跨浏览器进程持久化保证。
- F1 mode 草稿、F3 长名称卡片、F4 分组/主题历史编辑器分流、F5 单 h1、F6 跨页面屏障均保留定向回归。

## 看板 #21：验收反馈后的主流程修正

在 `d93beac118be31767097e251f6447edcc59be87c` 上完成本地 UI 修正：默认入口现在明确展示“频道 → 建议的已有分组 → 匹配依据 → 调整并确认”，每条建议分别显示状态、已有分组和依据；空匹配明确标为“未匹配”，并提示保持未分组或手动选择。旧 topics 流程未删除、未扩权，仍保持默认收起，但标记为“次要入口 · 旧版 · 可创建分组”。后台 AI 仍未开启，也没有新增授权。

定向 Vitest 为 2 文件 38 项通过；Node 22 typecheck、受影响 lint、build 通过。全前端 lint 因命令脚本仍检查整个目录，结果为 0 errors、1 个未修改文件 `frontend/src/hooks/useSuggestedQuestions.ts:32` 的既存 warning。独立合成浏览器验收为 19/19：覆盖默认入口、两类建议状态、旧编辑器分流、单一 `h1`、390px 无横向溢出及当前 bundle 与本地构建一致。证据位于恢复包 `task-21-ui-feedback-fix-20261023/`。

旧 9531 候选 `SmartGroupingWorkspace-B1pDhtt3.js` 的 SHA-256 `d43d7e7b539a505d97970734f2b3a80c317a810d2a4ab1c5df084d5d0ab9480b` 已失效，不得继续作为当前 UI 证据。当前本地预览加载 `SmartGroupingWorkspace-DRcD2yMp.js`，HTTP 与本地 `dist` 逐字节一致，SHA-256 为 `54a97bb2db1f4816f70bae8a2d80672cd766dbbd869b28b4911a5e4c53839d43`。这是新的本地验收候选，尚未取得用户对变更后交互的重新接受。

## 看板 #22：旧版目标分组选择器规范修正

在看板 #21 提交 `91e1afde966237145c62278d8943aae27fa620ff` 上，将旧 topics `ProposalEditor` 的“放入分组”原生 `<select>` 替换为项目现有 shadcn `ModelCombobox`（Radix Popover + Command）。选择器支持按分组名称或数字 ID 搜索、键盘选择、Escape 关闭及触发器焦点恢复、长名称换行与受限滚动。空值仍代表“创建新分组”，且仅存在于明确标记的旧版次要入口；选择已有分组后仍向应用合同提交数字 `group_id`。同时将该编辑器中受影响的输入、按钮与复选框复用项目 `Input` / `Button`，两项短枚举“整理范围”改用已有 `NativeSelect`；没有用包装原生下拉冒充目标分组搜索选择器。

定向 Vitest 为 6 文件 86 项通过，覆盖真实 Command 弹层筛选、键盘 Enter、Escape、焦点恢复、创建新分组与已有分组 ID payload；Node 22 typecheck、全前端 lint、build 通过。lint 为 0 errors、1 个未修改文件 `frontend/src/hooks/useSuggestedQuestions.ts:32` 的既存 warning。独立 localhost:9531 合成 Chromium 验收为 13/13，含桌面真实弹层操作、390px 弹层边界与无横向溢出，共 3 张截图。证据位于恢复包 `task-22-shadcn-group-picker-20261023/`。

看板 #21 的 `SmartGroupingWorkspace-DRcD2yMp.js` 指纹 `54a97bb2db1f4816f70bae8a2d80672cd766dbbd869b28b4911a5e4c53839d43` 已失效。当前 9531 加载 `SmartGroupingWorkspace-Dp2PKxwB.js`，HTTP 与本地 `dist` 逐字节一致，SHA-256 为 `804a1c3e2da48694e3ed2ea17fa297051b59cae527be8d12c150a503f5c63419`。用户对变更后 UI 的重新验收仍为 PENDING。

## 当前两级层级候选

本轮在主工作树增加严格两级“根分类 → 子分组 → 频道”合同。它是历史平面分组候选之后的行为变更，因此下文 `d93beac`、#21/#22 的截图、bundle 指纹和用户 PASS 都不能作为当前候选证据。当前候选只使用隔离 SQLite 和合成/模拟 AI；未读取业务数据库，未调用真实 Provider。

本轮人工检查应至少覆盖：

1. 在 `/channels/groups` 创建、重命名和删除空根分类；创建、重命名、改挂和删除子分组，确认改挂前后成员不变。
2. 使用 `?root=<id>&group=<id>` 深链进入合法选择，并确认无效或不匹配的 ID 安全回退；桌面与 390px 都无横向溢出。
3. 在侧栏、频道卡片/详情、发现订阅、阅读范围和 OPML 映射中确认统一“根 / 子”路径；根分类不作为可读范围。
4. 在 `/channels/smart` 分别检查“整理层级”和“整理频道”：预览出现前、未勾选和未确认时数据库无层级或成员写入；确认后只应用选中的精确建议，撤销不覆盖后续人工修改。
5. 导入嵌套 OPML 时精确匹配已有完整路径；新子分组必须显式选择已有根分类。`/channels/manual` 必须重定向到 `/channels`。

当前候选的真实 Provider、Miniflux、完整 CI、生产迁移/部署、真实手机硬件和用户 UAT 均为 `NOT_RUN`；自动化浏览器结果和本地提交 SHA 以本轮最终交付记录为准。

### 两级层级候选的本轮本地验收

使用当前源码、独立迁移后的合成 SQLite、真实本地 Django HTTP 与 Chromium 完成桌面 1280px 和移动 390px 验收。桌面实测根分类与子分组的新建、重命名、空项删除、子分组改挂及成员保留；合法深链可恢复选择，无效深链安全回退。通过预置的 review-only 合成建议分别验证频道整理和层级整理的“查看建议 → 确认应用 → 状态更新”，并验证层级撤销只恢复未被后续修改的移动。未调用真实模型。

嵌套 OPML 预览将已有 `生活 / 商业观察` 精确映射到现有子分组；新路径 `技术 / 新导入` 初始不自动建组，人工显式选择根分类后才创建子分组。确认导入后立即取消两个合成接入任务，未连接真实 Miniflux。`/channels/manual` 实测重定向到 `/channels`。390px 页面 `scrollWidth == innerWidth == 390`，树的折叠/展开与 Tab 焦点可达，智能整理双模式可见；浏览器控制台无 JavaScript warning/error。页面切换产生的请求取消和合成账号未配置模型导致的任务偏好 403 已分类，不是成功路径错误。

## 本次真实执行的验证

运行环境：Python 3.12.14 / Django 6.1.2，复用现有兼容解释器；缺失的 `miniflux==1.1.6` 与 `redis==8.1.0` 从缓存离线安装到恢复包的独立 `deps/`，未修改共享 venv。Node 22.23.3，候选 worktree 中独立 `npm ci --offline --no-audit --no-fund`，未修改 lockfile。后端使用 `env -i`、合成 secret 与独立 SQLite，无 `.env`、真实 Key/Provider。

| 检查 | 结果与证据文件（相对恢复包） |
|---|---|
| 频道/分组 8 个模块 | PASS：135 tests；`backend-targeted.log` |
| classification evidence / AG-02 / RSS personal category / unified channels | PASS：15 tests；`backend-contracts.log` |
| `makemigrations --check --dry-run` | PASS：No changes detected；`migration-check.log` |
| 前端定向 8 文件 | PASS：91 tests；`frontend-targeted.log` |
| `npm run typecheck` | PASS；`typecheck.log`；看板 #7 重跑亦 PASS：`task-7-verify-20261023/frontend.log` |
| ESLint | 受影响文件 PASS：`eslint.log`；看板 #7 全前端 PASS（0 errors、1 个候选未修改文件中的既存 warning）：`task-7-verify-20261023/frontend.log` |
| `npm run build` | PASS；`build.log`；看板 #7 重跑亦 PASS：`task-7-verify-20261023/frontend.log` |
| Chromium / 真正本地 Django HTTP / 合成 DB | PASS：初次 33 checks；`browser-acceptance.log`、`browser-evidence/results.json`；看板 #14 重新初始化独立 DB 后 33/33、11 张截图：`task-14-verify-20261023/` |
| 用户原本地预览验收 | PASS：2026-10-23 接受 `d93beac` 对应预览；原生下拉与新旧流程反馈明确记录为不阻塞当次验收 |
| 当前 `c760382` UI 重新验收 | PENDING：#21/#22 改变交互后不能沿用原 PASS |
| 完整套件、CI、真实 Provider/Miniflux、生产、部署、线上回滚 | NOT_RUN，不以历史全量结果或本地用户接受替代 |

看板 #7 在未变更运行时代码的候选上再次执行同一后端定向范围，结果为 135 passed（36.66s）；并重跑 Node 22 typecheck、全前端 lint 和 build。独立证据摘要及原始日志位于恢复包的 `task-7-verify-20261023/`。全前端 lint 唯一 warning 位于本候选未修改的 `frontend/src/hooks/useSuggestedQuestions.ts:32`，退出码为 0；没有修改测试或源码来隐藏它。

看板 #14 在当前 23 文件清单哈希前后不变的前提下，新跑 B1–B3 后端 43 项和 F1–F6 前端 3 文件 41 项；随后重新初始化独立合成数据库，重启 9531 服务并生成 33/33 浏览器结果、11 张截图。typecheck、全前端 lint、build 因候选字节不变复用紧邻的 #7 证据，没有重复执行来制造额外 PASS。详情为 `task-14-verify-20261023/RESULT.md`。

后端定向命令为 `python -m pytest -c backend/pytest.ini -q -p no:cacheprovider --tb=short`，8 个文件为：`test_personal_channel_organization.py`、`test_smart_channel_workspace.py`、`test_channel_ai_limits.py`、`test_ag01_source_metadata.py`、`test_channels.py`、`test_channel_migration.py`、`test_channel_topic_hints.py`、`test_channel_intake_review.py`（均在 `backend/api/tests/`）。合同追加为 `test_classification_evidence.py`、`test_ag02_verified_evidence.py`、`rss/test_personal_category.py`、`rss/test_unified_channels.py`。

前端命令为 `npm run test:run -- tests/pages/GroupWorkspace.bulk.test.tsx tests/pages/GroupWorkspace.submission.test.tsx tests/pages/SmartGroupingWorkspace.groups.test.tsx tests/pages/SmartGroupingWorkspace.flow.test.tsx tests/pages/Channels.integration.test.jsx tests/pages/NewsList.test.jsx tests/pages/NewsList.auth.test.jsx tests/services/workspaceApi.test.ts`。

浏览器覆盖：桌面 1280px、移动视口 390px、登录、分组批量移动、主动中断 POST 后的未知结果屏障及 SPA 返回/核对、预览/确认、高级入口单 h1、阅读范围搜索；390px 卡片正常换行且无横向溢出。预览先验证陈旧元数据的建议必须确认，再额外用重新读取发布身份并记录正确证据的可信样例，运行真实 `channel_worker --once` 证明自动归组成功。没有为通过验收降低可信判断。

控制台两条已分类错误为匿名 `auth/me` 403 与主动中断 POST 的 ERR_FAILED；未观察到页面异常。系统手机触摸/输入法、真实声音和真实模型内容质量不是移动视口检查可以证明的。

## 可运行入口与人工验收

站点：`http://localhost:9531/channels/smart`；分组管理：`http://localhost:9531/channels/groups`。

合成账号：`organizer-preview`；合成口令：`local-preview-only-9531`（仅此预览，不是业务凭据）。合成运行库及服务脚本在恢复包 `task-14-verify-20261023/`；看板 #21 证据在 `task-21-ui-feedback-fix-20261023/`，看板 #22 的脚本、日志、结果和 3 张新截图在 `task-22-shadcn-group-picker-20261023/`。真实站点没有修改。旧的 `runtime/preview/` 与 `browser-evidence/` 作为初次验收历史保留，不冒充本轮新证据。

1. 查看首页三个固定范围与可搜索分组；在分组管理选择频道，批量移动/移出，确认个人订阅保留。
2. 在智能整理先确认四步主流程与“主流程”标识；查看“待确认”和“未匹配”建议。再展开旧版次要入口，打开 topics 建议，验证“放入分组”可搜索名称/ID、键盘选择及 Escape 焦点恢复，并确认只有一个页标题。
3. 查看自动整理设置、建议和历史。预览没有开启后台 AI；不要把无真实模型的合成结果当真实 AI 验收。

复用当前预览（无需重新初始化）：`/home/lambert/githubRepos/lambert/news-aggregator-accept/backend/venv/bin/python /home/lambert/.local/share/newshub/channel-organization-recovery-20261023/task-14-verify-20261023/local_preview.py serve`。脚本固定合成环境；端口已占用时不要启动第二份。恢复包根目录与 task #14 目录的 `preview-process.json` 记录当前服务 PID，停止前先核对其命令行，不按端口批量杀进程。`channel_worker --once` 已由验收脚本执行，没有遗留后台循环 worker。

## 用户验收、风险与回退

- 用户已接受的是 `d93beac` 对应的先前本地预览。验收中指出旧主题预设编辑器的视觉变化有限，且其中仍有原生下拉框；该反馈不应被改写成“未发现问题”。看板 #21 已实现更清晰的新旧流程区分，看板 #22 已完成 shadcn 搜索选择器替换，因此先前接受不能自动覆盖当前 UI 候选，需重新提供本地验收。
- `d93beac` 候选曾通过用户本地体验验收；看板 #21/#22 后的当前 `c760382` UI 候选仅完成自动化本地验收，用户重新验收仍为 PENDING。两者都不是已部署版本。新版分页响应和前端消费者必须同批交付；不能只部署一侧。
- `0084` 是前向迁移，恢复测试验证保留旧配置/提案/成员；回退应用时保留已写入的新表列与历史，不删除真实数据。
- 源码和证据现在在持久目录；分组功能及反馈修正已通过各阶段唯一指定 Luna/xhigh 委托依次本地提交为 `d93beac`、`91e1afd`、`c760382`。更早两次 `index.lock` 只读失败仍作为历史事实保留；#19 最终通过受支持的最小 Git 元数据授权解决，没有关闭沙箱或改写历史。
