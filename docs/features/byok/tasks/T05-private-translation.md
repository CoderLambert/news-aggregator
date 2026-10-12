# T05 · 个人全文翻译最小闭环

> **READY FOR REVIEW（2026-10-12）**：[Draft PR #39](https://github.com/CoderLambert/news-aggregator/pull/39) 中的 T05 实现已在 `task/byok-T05-private-translation` 完成，本地新用例与前端验证通过。旧订阅回归有一个 SQLite 并发用例在完整组跑中失败、隔离重跑通过；SDK_LOCAL、PROXY_LOCAL、PROVIDER_REAL 和用户浏览器 UAT 仍为 NOT_RUN。实际证据见 [Test T05](../tests/T05-private-translation.md)。

| 属性 | 内容 |
| --- | --- |
| 前置任务 | [T04](T04-article-chat.md) |
| 推荐规模 | M（限定安全长度） |
| 对应测试 | [Test T05](../tests/T05-private-translation.md) |

## 本次交付的完整功能

对一篇安全长度内新闻原文使用个人 Key 翻译，看到进度和完整私有结果；重新打开通过 GET 找回同一任务及译文。

**允许修改范围**：在现有 ChatGPTTranslationTask/ChatGPTArticleTranslation 上增量增加 api_key 凭据变体/幂等身份/冻结输入/来源结果；复用旧执行器、租约、CAS、SSE；只在完整上游终态且事务成功后提交私有译文，迁移旧行保真。

**本次明确不做**：不新增 UserTranslationTask 第二套表、不对长文无上限生成（T06）、不同时修改 TTS/研究、不发布共享译文。

### 可直接复现的验收路径

短/中篇 Markdown→个人模型翻译→显示成功→刷新通过 GET 恢复同一个 result_id；超过预算明确拒绝。

### 对应 Test 用例

| Test ID | 可操作情境 | 必须观察到 | Test 文件 |
| --- | --- | --- | --- |
| T05-01 | 完整上游终态+事务提交结果、任务和完成事件 | 结果有稳定 task_id/result_id，关 SSE 不影响已成功内容 | [Test 契约](../tests/T05-private-translation.md) |
| T05-02 | 重复 Idempotency-Key 同请求/不同请求/同源并发 | 前者同任务，后者409，无二次自动调用 | [Test 契约](../tests/T05-private-translation.md) |
| T05-03 | partial EOF/length/DB提交失败 | 进度不能作为完成译文，禁止 complete | [Test 契约](../tests/T05-private-translation.md) |
| T05-04 | A/B 使用自己的 Key 译同篇文章 | 不同用户/连接隔离，BYOK内容不发布 shared | [Test 契约](../tests/T05-private-translation.md) |
| T05-05 | 旧 subscription 翻译任务和旧迁移行 | 旧语义/外键约束保持 | [Test 契约](../tests/T05-private-translation.md) |

### 立即停止并纠偏

GET 派发任务、旧订阅记录迁移有损、私有内容写入公共缓存或 DB 未保存却显示完成时停止。

### Codex 一次任务交付要求

1. 查看当前工作目录 AGENTS、分支和未提交改动；读取本卡和同编号 Test、技术方案/最新相关代码。
2. 同环境记录受影响旧测试的基线；用既有 Django/React/SSE/SDK/持久任务，先验证关键假设再编码。
3. 本次只交付这一项**可以运行的完整功能**，包括权限、正常操作与最主要的失败路径；不跨到其它 Txx。
4. 跑最小定向单元/契约测试以及受影响旧功能回归，列出修改过的测试断言 diff；需求未变时禁止改断言迁就代码。
5. 更新对应 Test 文档中的真实日志、环境、SHA 和 NOT_RUN 项；单张任务 PR base 指向 `task/byok-T04-article-chat`。未授权时不合并 main、不开始下一张卡。

**当前实现**：短文私有翻译、任务 GET 恢复、取消、同用户幂等、跨用户隔离、凭证代次 fencing、完整上游终态和事务回滚已有自动化覆盖。[T05 Draft PR #39](https://github.com/CoderLambert/news-aggregator/pull/39) 以 T04 分支为 base；父 PR #38 仍未合并。测试中的未验证项明确保留为 NOT_RUN。

**任务结束**：这条用户流程能运行、失败能清楚识别，主要不变量有自动化验证；更新同名 Test 实际证据并留下单张可审核 PR。当前任何未验证的地方明确写 NOT_RUN。

