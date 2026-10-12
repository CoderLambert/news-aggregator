# T03 · 用途默认模型设置

> **READY FOR REVIEW（2026-10-12）**：五种用途的用户偏好、严格保存 API、失效选择的 fail-closed 处理、只读执行快照解析和设置页已实现。`resolve_execution` 尚未接入真实业务 worker；在途 worker/历史结果的端到端验收保持 NOT_RUN，不能据此声称 T04/T05/T09/T11 已闭环。详细证据见 [Test T03](../tests/T03-preferences.md)。

本工作树已重放到最新 T02 分支 `task/byok-T02-models-and-tests`，父提交为 `c2f50dd6a56e17dad65e78b295a13598895b4c76`。T02 PR #36 仍为 Draft、未合并；本卡继续使用 stacked PR 并依赖 #36。T03 代码实现重放后提交：`1fbd8535454d50c3d4939b4949c762fff23daa9f`。

| 属性 | 内容 |
| --- | --- |
| 前置任务 | [T02](T02-models-and-tests.md) |
| 推荐规模 | S-M |
| 对应测试 | [Test T03](../tests/T03-preferences.md) |
| 本卡 PR | [#37 Draft](https://github.com/CoderLambert/news-aggregator/pull/37) |
| PR base | `task/byok-T02-models-and-tests` @ `c2f50dd6a56e17dad65e78b295a13598895b4c76`（stacked；依赖 Draft PR #36） |
| 实现提交 | `4310d2143fe1ad748f264f421a5d500f3621abcd` |

## 本次交付的完整功能

用户为“默认、文章问答、全文翻译、深度研究、问题推荐”选择模型并点击保存；刷新和重新登录状态一致。

**允许修改范围**：UserAITaskPreference、按 user 的原子保存与服务端 resolve_execution 快照选择；实现模型与用途区、未保存/失败/空账户/禁用状态、移动端和键盘使用。

**本次明确不做**：不改业务接口实际推理；不因为新增连接自动更换默认；不添加第二套状态管理。

### 可直接复现的验收路径

配置五个用途→显示未保存→保存→刷新→不同账号各自读取→停用连接显示需重选，不偷偷兜底。

### 对应 Test 用例

| Test ID | 可操作情境 | 必须观察到 | Test 文件 |
| --- | --- | --- | --- |
| T03-01 | 保存五个偏好并重新 GET | 只对当前用户有效，必须明确点击保存 | [Test 契约](../tests/T03-preferences.md) |
| T03-02 | 草稿撤销与保存失败 | 草稿状态真实，不宣称持久化成功 | [Test 契约](../tests/T03-preferences.md) |
| T03-03 | 偏好指向 B 的模型或停用连接 | 拒绝，缺省时不得自动用站点/订阅凭据 | [Test 契约](../tests/T03-preferences.md) |
| T03-04 | 改变默认与正在运行任务的执行快照 | 已开始任务完全不变，历史仍可读 | [Test 契约](../tests/T03-preferences.md) |
| T03-05 | 阅读设置/ChatGPT设置与 390px 布局 | 旧入口正常，新页面易于操作 | [Test 契约](../tests/T03-preferences.md) |

### 立即停止并纠偏

引用另一用户 model_config 或改变默认后旧运行任务重绑定时停止。

### Codex 一次任务交付要求

1. 查看当前工作目录 AGENTS、分支和未提交改动；读取本卡和同编号 Test、技术方案/最新相关代码。
2. 同环境记录受影响旧测试的基线；用既有 Django/React/SSE/SDK/持久任务，先验证关键假设再编码。
3. 本次只交付这一项**可以运行的完整功能**，包括权限、正常操作与最主要的失败路径；不跨到其它 Txx。
4. 跑最小定向单元/契约测试以及受影响旧功能回归，列出修改过的测试断言 diff；需求未变时禁止改断言迁就代码。
5. 更新对应 Test 文档中的真实日志、环境、SHA 和 NOT_RUN 项；单张任务 PR base 指向 `feat/byok-user-api-keys`。未授权时不合并 main、不开始下一张卡。

**任务结束**：这条用户流程能运行、失败能清楚识别，主要不变量有自动化验证；更新同名 Test 实际证据并留下单张可审核 PR。当前任何未验证的地方明确写 NOT_RUN。

