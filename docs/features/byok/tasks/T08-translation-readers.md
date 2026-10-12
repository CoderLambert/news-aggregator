# T08 · 译文详情、问答与朗读同源

> **IMPLEMENTED · DRAFT PR #42**。本卡自动化证据见 [Test T08](../tests/T08-translation-readers.md)。真实 provider 请求和手动浏览器 UAT 保持 NOT_RUN。

| 属性 | 内容 |
| --- | --- |
| 前置任务 | [T05](T05-private-translation.md)、[T07](T07-translation-lifecycle.md) |
| 推荐规模 | M |
| 对应测试 | [Test T08](../tests/T08-translation-readers.md) |

本次代码提交 `e9e96444488c75b3dbd550ab51ff7d04370bfc03` 基于 T07 Draft PR #41 的固定 head `b0139e42291bc83c701a04f73f1f7fdcbf16b0a0`。T07 仍未合并，因此本 PR 暂以 T07 分支为 base，作为可独立审阅的堆叠任务提交；不代表前置 PR 已集成。

## 本次交付的完整功能

个人译文生成后刷新页面仍可见，聊天上下文和中文朗读读同一份结果；换/删 Key 不删除历史。

**允许修改范围**：构建一个用户私有 result_id 解析入口，复用 serializers、pick_chat_context、tts_service；处理个人优先/公共/旧订阅回退、source stale 与已保存独立、TTS 缓存含 owner/result 身份。

**本次明确不做**：不开发第二套 TTS Provider，不改变旧订阅发布策略，不用 GET 重新付费翻译。

### 可直接复现的验收路径

生成译文→重进文章看到模型/版本→聊天与朗读引用同一结果→停用 Key 仍能查看；源码更新仅显示 stale。

### 对应 Test 用例

| Test ID | 可操作情境 | 必须观察到 | Test 文件 |
| --- | --- | --- | --- |
| T08-01 | 详情/问答/TTS读取明确所属的同一结果 | 三个消费者来源一致，零 Provider 调用 | [Test 契约](../tests/T08-translation-readers.md) |
| T08-02 | 同篇文章用户 A/B 两份私人译文+朗读 | 数据与音频缓存按用户及result隔离 | [Test 契约](../tests/T08-translation-readers.md) |
| T08-03 | 文章源内容变化 | 旧 result 仍 saved 但 current-match=stale | [Test 契约](../tests/T08-translation-readers.md) |
| T08-04 | 无个人结果或已有公共/订阅译文 | 遵守既定优先级，旧内容读取正常 | [Test 契约](../tests/T08-translation-readers.md) |
| T08-05 | 删除连接后的历史读取 | 无有效 Key 仍可见自己的完成数据 | [Test 契约](../tests/T08-translation-readers.md) |

### 立即停止并纠偏

私人音频跨用户、旧原文被冒充新结果、历史 GET 需要仍有效 Key 时停止。

### Codex 一次任务交付要求

1. 查看当前工作目录 AGENTS、分支和未提交改动；读取本卡和同编号 Test、技术方案/最新相关代码。
2. 同环境记录受影响旧测试的基线；用既有 Django/React/SSE/SDK/持久任务，先验证关键假设再编码。
3. 本次只交付这一项**可以运行的完整功能**，包括权限、正常操作与最主要的失败路径；不跨到其它 Txx。
4. 跑最小定向单元/契约测试以及受影响旧功能回归，列出修改过的测试断言 diff；需求未变时禁止改断言迁就代码。
5. 更新对应 Test 文档中的真实日志、环境、SHA 和 NOT_RUN 项；单张任务 PR base 指向 `feat/byok-user-api-keys`。未授权时不合并 main、不开始下一张卡。

**任务结束**：这条用户流程能运行、失败能清楚识别，主要不变量有自动化验证；更新同名 Test 实际证据并留下单张可审核 PR。当前任何未验证的地方明确写 NOT_RUN。

