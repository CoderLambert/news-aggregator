# T10 · 研究续问与安全恢复

> **PLANNED**：本文件为未执行的实施/测试契约，所有测试当前 NOT_RUN。实施时以 `origin/feat/byok-user-api-keys` 最新 HEAD 为准，勿把设计 SHA 当作当前代码。

| 属性 | 内容 |
| --- | --- |
| 前置任务 | [T09](T09-research-first-run.md) |
| 推荐规模 | M |
| 对应测试 | [Test T10](../tests/T10-research-followup.md) |

## 本次交付的完整功能

已保存研究可续问，断开 SSE 后原会话只读恢复，不再发起新的收费研究；取消只作用准确运行。

**允许修改范围**：在 ResearchSession 服务端持久化带协议版本的 native continuation、前端仅可见消息；复用 research_chat/stream/resume_queued/cancel，模型会话锁定与严格幂等、事件序号、旧 worker fencing。

**本次明确不做**：不跨厂商移植原始 thinking blocks；不从 GET/浏览器刷新创建新收费任务。

### 可直接复现的验收路径

研究完成→提追问→工具二轮→断线重连 GET 恢复同 run_id→明确取消仅取消最新任务。

### 对应 Test 用例

| Test ID | 可操作情境 | 必须观察到 | Test 文件 |
| --- | --- | --- | --- |
| T10-01 | 二轮工具调用保留原生 provider continuation | 可见消息与秘密续接分离，最终完整入库 | [Test 契约](../tests/T10-research-followup.md) |
| T10-02 | GET status/stream 重连 | 零新任务、零 provider 请求 | [Test 契约](../tests/T10-research-followup.md) |
| T10-03 | 重复 POST 同幂等键/不同请求同键 | 同运行 / 409 冲突，无重复收费 | [Test 契约](../tests/T10-research-followup.md) |
| T10-04 | cancel、迟到 response、运行租约过期 | run_token/CAS 阻止旧提交，未知上游状态不重发 | [Test 契约](../tests/T10-research-followup.md) |
| T10-05 | 既有研究会话继续读取与历史权限 | 不回归 | [Test 契约](../tests/T10-research-followup.md) |

### 立即停止并纠偏

GET 能派发新任务、旧 SSE/Worker 事件覆盖新会话、native 续接不可用时停止。

### Codex 一次任务交付要求

1. 查看当前工作目录 AGENTS、分支和未提交改动；读取本卡和同编号 Test、技术方案/最新相关代码。
2. 同环境记录受影响旧测试的基线；用既有 Django/React/SSE/SDK/持久任务，先验证关键假设再编码。
3. 本次只交付这一项**可以运行的完整功能**，包括权限、正常操作与最主要的失败路径；不跨到其它 Txx。
4. 跑最小定向单元/契约测试以及受影响旧功能回归，列出修改过的测试断言 diff；需求未变时禁止改断言迁就代码。
5. 更新对应 Test 文档中的真实日志、环境、SHA 和 NOT_RUN 项；单张任务 PR base 指向 `feat/byok-user-api-keys`。未授权时不合并 main、不开始下一张卡。

**任务结束**：这条用户流程能运行、失败能清楚识别，主要不变量有自动化验证；更新同名 Test 实际证据并留下单张可审核 PR。当前任何未验证的地方明确写 NOT_RUN。

