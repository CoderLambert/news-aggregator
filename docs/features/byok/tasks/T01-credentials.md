# T01 · 个人 Key 连接增删改停

> **READY FOR REVIEW（2026-10-12）**：T01 本地实现和 CRUD/权限/密钥生命周期验证已完成；修复代码 SHA `34f5a843dbc4a9fb218ff9fadf8ed32886f46953`。T01-03 的排队旧 epoch 拒绝与在途撤销后不提交结果，已由堆叠 T05 PR #39 的 worker 集成测试覆盖（head `54df6ab`）；该 PR 尚未合并，T01 PR #34 本身仍不包含翻译 worker。未据此宣称真实 Provider 兼容。完整环境、命令和验证边界见 [Test T01](../tests/T01-credentials.md)。

| 属性 | 内容 |
| --- | --- |
| 前置任务 | 无；Key 管理不调用 Proxy |
| 推荐规模 | M |
| 对应测试 | [Test T01](../tests/T01-credentials.md) |

## 本次交付的完整功能

在正式 /settings/ai 页面新增自己的官方服务商 Key，查看掩码状态，更换、停用和删除连接，登录后的状态能够跨刷新恢复。

**允许修改范围**：UserAIConnection、可信厂商/地域端点、加密 Secret+AAD/credential_epoch、Session+CSRF、按 user CRUD、最小连接 UI；AI_BYOK_ENABLED 默认关闭，保留 /settings/chatgpt。

**本次明确不做**：不做模型测试、Proxy 请求或任何收费调用；用户不能任意输入 Base URL；不修改订阅 OAuth 令牌格式。

### 可直接复现的验收路径

用户 A 保存 DeepSeek 通用 Key→刷新看到脱敏连接→替换→停用→删除；用户 B 无权查看/更改。

### 对应 Test 用例

| Test ID | 可操作情境 | 必须观察到 | Test 文件 |
| --- | --- | --- | --- |
| T01-01 | A 新增/更新/停用/删除连接，重新进入仍反映最新状态 | GET 无原始 Key，数据加密且 AAD 绑定身份及端点 | [Test 契约](../tests/T01-credentials.md) |
| T01-02 | B/匿名/跨站请求尝试访问 A 的连接 | 不可读取或修改，必须 CSRF 与 owner 校验 | [Test 契约](../tests/T01-credentials.md) |
| T01-03 | 替换/撤销 Key 后旧 credential_epoch 请求仍在队列 | 旧凭据不可再获调用或提交权限；旧订阅不受影响 | [Test 契约](../tests/T01-credentials.md) |
| T01-04 | 只打开页面、保存 Key 或改别名 | provider 调用次数为 0，记录不谎报“已验证” | [Test 契约](../tests/T01-credentials.md) |
| T01-05 | 生产只读、开关关闭、缺主密钥 | 拒绝新写操作，无法降级为明文或站点 Key | [Test 契约](../tests/T01-credentials.md) |

### 立即停止并纠偏

Key 进入日志/URL/浏览器持久存储、缺 Secret 却允许保存、或跨用户访问成功，则中止。

### Codex 一次任务交付要求

1. 查看当前工作目录 AGENTS、分支和未提交改动；读取本卡和同编号 Test、技术方案/最新相关代码。
2. 同环境记录受影响旧测试的基线；用既有 Django/React/SSE/SDK/持久任务，先验证关键假设再编码。
3. 本次只交付这一项**可以运行的完整功能**，包括权限、正常操作与最主要的失败路径；不跨到其它 Txx。
4. 跑最小定向单元/契约测试以及受影响旧功能回归，列出修改过的测试断言 diff；需求未变时禁止改断言迁就代码。
5. 更新对应 Test 文档中的真实日志、环境、SHA 和 NOT_RUN 项；单张任务 PR base 指向 `feat/byok-user-api-keys`。未授权时不合并 main、不开始下一张卡。

**任务结束**：这条用户流程能运行、失败能清楚识别，主要不变量有自动化验证；更新同名 Test 实际证据并留下单张可审核 PR。当前任何未验证的地方明确写 NOT_RUN。

