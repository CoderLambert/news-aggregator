# T09 · 首次个人模型深度研究

> **READY FOR REVIEW**：T09 已在 T03 当前实现之上完成。合成 LiteLLM Proxy + OpenAI SDK 的工具往返和持久化报告通过；真实 provider/UAT 尚未执行。本卡对应 [Draft PR #43](https://github.com/CoderLambert/news-aggregator/pull/43)，base 为尚未合并的 T03 分支。

| 属性 | 内容 |
| --- | --- |
| 前置任务 | [T03](T03-preferences.md)、[T00 本地技术门槛](T00-sdk-protocol.md) |
| 推荐规模 | M |
| 对应测试 | [Test T09](../tests/T09-research-first-run.md) |

## 本次交付的完整功能

用户使用已验证工具能力的个人模型，创建研究会话、调用许可检索工具、收到步骤事件并保存完整研究报告。

**允许修改范围**：复用 ResearchRun/ResearchRunEvent、job_manager lease/CAS、研究工具和 SSE，首次研究注入服务端快照、可信用户连接及业务后端→Proxy 路由；本地验收使用临时 LiteLLM Proxy 与受控 upstream，不依赖共享生产服务。调整 HTTP 与 worker 门禁，区分已许可 BYOK 与未获批订阅研究。生产配置缺网关时 fail closed。

**本次明确不做**：不重写 Agent 框架或工具列表、不放开站点全局禁用，不同时实现后续续问重连（T10）。

### 可直接复现的验收路径

选已验证模型→经临时 Proxy 发起研究→受控工具调用/记录→完整答案入库→GET 只读旧报告。

### 对应 Test 用例

| Test ID | 可操作情境 | 必须观察到 | Test 文件 |
| --- | --- | --- | --- |
| T09-01 | 新建研究→调用一个合法工具→保存结果/Run/Event | 真正上游最终完成后事务提交 | [Test 契约](../tests/T09-research-first-run.md) |
| T09-02 | 生产环境个人合法 Key 与无 Key/未获批订阅 | 前者按 BYOK 开关鉴权；后者仍受阻断 | [Test 契约](../tests/T09-research-first-run.md) |
| T09-03 | 未验证 tools、工具名非法、参数无效、混合合法/非法批次、批次超限 | 整批预校验；无效批次在任何工具执行、工具事件或结果写入前整体拒绝；最多 8 个调用 | [Test 契约](../tests/T09-research-first-run.md) |
| T09-04 | 凭据在排队、模型请求中、工具完成后或最终提交前撤销 | 最终事务锁定并核验凭据 epoch 与模型快照；撤销先提交则不保存成功报告或 complete 事件 | [Test 契约](../tests/T09-research-first-run.md) |
| T09-05 | 工具写入失败、任务取消、最终 CAS 失败 | 不能误报 succeeded | [Test 契约](../tests/T09-research-first-run.md) |
| T09-06 | 现有研究历史/SSE/Idempotency-Key | 不复制或破坏旧 run 机制 | [Test 契约](../tests/T09-research-first-run.md) |

### 立即停止并纠偏

worker 绕过凭据/站点门禁，或工具能力/参数不可验证，禁止上线此路径。

### Codex 一次任务交付要求

1. 查看当前工作目录 AGENTS、分支和未提交改动；读取本卡和同编号 Test、技术方案/最新相关代码。
2. 同环境记录受影响旧测试的基线；用既有 Django/React/SSE/SDK/持久任务，先验证关键假设再编码。
3. 本次只交付这一项**可以运行的完整功能**，包括权限、正常操作与最主要的失败路径；不跨到其它 Txx。
4. 跑最小定向单元/契约测试以及受影响旧功能回归，列出修改过的测试断言 diff；需求未变时禁止改断言迁就代码。
5. 更新对应 Test 文档中的真实日志、环境、SHA 和 NOT_RUN 项；依赖卡尚未合并时，本卡 PR 以依赖卡分支为 base（本次为 `task/byok-T03-preferences`），形成可独立审核的堆叠 PR。未授权时不合并、不开始下一张卡。

**任务结束**：这条用户流程能运行、失败能清楚识别，主要不变量有自动化验证；更新同名 Test 实际证据并留下单张可审核 PR。当前任何未验证的地方明确写 NOT_RUN。

