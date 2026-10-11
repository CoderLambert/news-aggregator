# T00 · SDK 协议验真

> **PLANNED**：本文件为未执行的实施/测试契约，所有测试当前 NOT_RUN。实施时以 `origin/feat/byok-user-api-keys` 最新 HEAD 为准，勿把设计 SHA 当作当前代码。

| 属性 | 内容 |
| --- | --- |
| 前置任务 | 无 |
| 推荐规模 | S·技术门槛 |
| 对应测试 | [Test T00](../tests/T00-sdk-protocol.md) |

## 本次交付的完整功能

能用目标 Python 环境实际安装的 OpenAI/Anthropic SDK，经受控 HTTP 上游完整跑通 Responses、Chat Completions、Messages 的文本流和工具往返。

**允许修改范围**：固定必要 SDK 版本及适配器契约；ModelTurn/ModelEvent、原生终态、provider_state 和安全异常；独立 CLI 探针覆盖原始请求/响应解析和明确关闭；SDK 自动重试为0。

**本次明确不做**：不得建用户表、设置页、文章聊天、翻译任务或通用网关。仅调用 mocked gateway 不算 SDK 验真。

### 可直接复现的验收路径

执行一个脚本依次验证正常完成、仅输出 partial 后 EOF、流内错误与 tools→result→final；打印脱敏结果和版本。

### 对应 Test 用例

| Test ID | 可操作情境 | 必须观察到 | Test 文件 |
| --- | --- | --- | --- |
| T00-01 | 真实 SDK 文本和流在三种协议均收到各自完整终态 | 只完整且语义正确时报告成功 | [Test 契约](../tests/T00-sdk-protocol.md) |
| T00-02 | partial 后 EOF/length/incomplete/stream error/HTTP error | 全部是明确非成功，不能生成 complete | [Test 契约](../tests/T00-sdk-protocol.md) |
| T00-03 | tools 往返保留 Responses items / Anthropic thinking 签名 / Chat reasoning_content | 仅允许白名单工具和完整合法参数，可见消息剔除私密续接 | [Test 契约](../tests/T00-sdk-protocol.md) |
| T00-04 | 两组显式 Key/模型并发调用；设置 max_retries=0 | HTTP 请求无凭据混用，无隐式重发 | [Test 契约](../tests/T00-sdk-protocol.md) |
| T00-05 | 已有聊天/研究/翻译入口未被替换 | 已有旧测试按基线运行 | [Test 契约](../tests/T00-sdk-protocol.md) |

### 立即停止并纠偏

SDK 实际流的原始终态不可靠，或 native continuation 丢失，则只修本任务，禁止继续业务接入。

### Codex 一次任务交付要求

1. 查看当前工作目录 AGENTS、分支和未提交改动；读取本卡和同编号 Test、技术方案/最新相关代码。
2. 同环境记录受影响旧测试的基线；用既有 Django/React/SSE/SDK/持久任务，先验证关键假设再编码。
3. 本次只交付这一项**可以运行的完整功能**，包括权限、正常操作与最主要的失败路径；不跨到其它 Txx。
4. 跑最小定向单元/契约测试以及受影响旧功能回归，列出修改过的测试断言 diff；需求未变时禁止改断言迁就代码。
5. 更新对应 Test 文档中的真实日志、环境、SHA 和 NOT_RUN 项；单张任务 PR base 指向 `feat/byok-user-api-keys`。未授权时不合并 main、不开始下一张卡。

**任务结束**：这条用户流程能运行、失败能清楚识别，主要不变量有自动化验证；更新同名 Test 实际证据并留下单张可审核 PR。当前任何未验证的地方明确写 NOT_RUN。

