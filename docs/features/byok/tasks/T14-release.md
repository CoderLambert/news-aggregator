# T14 · 公开部署与兼容性发布关卡

> **PLANNED**：本文件为未执行的实施/测试契约，所有测试当前 NOT_RUN。实施时以 `origin/feat/byok-user-api-keys` 最新 HEAD 为准，勿把设计 SHA 当作当前代码。

| 属性 | 内容 |
| --- | --- |
| 前置任务 | [T04](T04-article-chat.md)、[T05](T05-private-translation.md)、[T06](T06-long-translation.md)、[T07](T07-translation-lifecycle.md)、[T08](T08-translation-readers.md)、[T09](T09-research-first-run.md)、[T10](T10-research-followup.md)、[T11](T11-suggestions.md)、[T12](T12-usage.md)、[T13](T13-providers.md) |
| 推荐规模 | M·发布门槛 |
| 对应测试 | [Test T14](../tests/T14-release.md) |

## 本次交付的完整功能

部署可开关的 BYOK 功能；开关关闭后不再产生新收费请求但历史仍只读；既有 ChatGPT 订阅、新闻、TTS、研究无回归。

**允许修改范围**：在测试部署检查迁移副本、全部关联回归、账户/CSRF/SSRF、生产 HTTP 与 worker 门禁、环境 Secret、出站限制、移动端、事故回退；给明确 GO/NO-GO，真实用户验收另记。

**本次明确不做**：不临时重建整套架构；不自动合并 main 或部署公网站点；不因只有 fake provider 测试就声称支持六家。

### 可直接复现的验收路径

测试环境开 BYOK→聊天/翻译/研究可用→关 BYOK→任何新收费调用被拒绝且自己旧结果可读；旧订阅功能能跑。

### 对应 Test 用例

| Test ID | 可操作情境 | 必须观察到 | Test 文件 |
| --- | --- | --- | --- |
| T14-01 | 迁移前后旧订阅、任务、新闻、TTS数据完整 | 数据库副本对账成功，旧路径回归证据 | [Test 契约](../tests/T14-release.md) |
| T14-02 | 两个用户 Session/CSRF、端点白名单、私网阻断 | 无越权和 SSRF 外泄 | [Test 契约](../tests/T14-release.md) |
| T14-03 | read_only、PUBLIC_AI_ENABLED、AI_BYOK_ENABLED、worker | 禁用时无新付费调用，既有历史按权限只读 | [Test 契约](../tests/T14-release.md) |
| T14-04 | 重启、掉线、取消、完成写库失败 | 不产生伪完成或隐式重复调用 | [Test 契约](../tests/T14-release.md) |
| T14-05 | 六厂商真实结果与用户UAT状态 | 未执行标 NOT_RUN，最终 GO/NO-GO 附明确范围 | [Test 契约](../tests/T14-release.md) |

### 立即停止并纠偏

安全隔离/迁移/门禁任何一个阻断项失败即 NO-GO。

### Codex 一次任务交付要求

1. 查看当前工作目录 AGENTS、分支和未提交改动；读取本卡和同编号 Test、技术方案/最新相关代码。
2. 同环境记录受影响旧测试的基线；用既有 Django/React/SSE/SDK/持久任务，先验证关键假设再编码。
3. 本次只交付这一项**可以运行的完整功能**，包括权限、正常操作与最主要的失败路径；不跨到其它 Txx。
4. 跑最小定向单元/契约测试以及受影响旧功能回归，列出修改过的测试断言 diff；需求未变时禁止改断言迁就代码。
5. 更新对应 Test 文档中的真实日志、环境、SHA 和 NOT_RUN 项；单张任务 PR base 指向 `feat/byok-user-api-keys`。未授权时不合并 main、不开始下一张卡。

**任务结束**：这条用户流程能运行、失败能清楚识别，主要不变量有自动化验证；更新同名 Test 实际证据并留下单张可审核 PR。当前任何未验证的地方明确写 NOT_RUN。

