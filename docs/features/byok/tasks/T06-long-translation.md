# T06 · 长文分块完整翻译

> **IMPLEMENTED · DRAFT PR**。代码提交 `1f719e666edc5554c16ffc1aa0b227909118a60f`；测试证据见 [Test T06](../tests/T06-long-translation.md)。本卡依赖 T05 私有翻译任务链，分支与 PR 堆叠于 T05 PR #39 的 head `54df6abd70a979fee11a2c610c4fde0c35f00a15`；PR #39 未合并。T06 head `7200211b382cdbee5086ee721eec64ad5d075ee0` 的 T06 定向测试在 CI 中通过，但两组后端完整门禁因既有 SQLite worker-recovery 用例失败；具体运行见 Test T06。CI 全绿前保持 Draft。

| 属性 | 内容 |
| --- | --- |
| 前置任务 | [T05](T05-private-translation.md)，PR [#39](https://github.com/CoderLambert/news-aggregator/pull/39) |
| 分支 | `task/byok-T06-long-translation` |
| PR base | `task/byok-T05-private-translation`（明确堆叠依赖，不以未包含 T05 的 feature branch 假装独立） |
| 推荐规模 | M |
| 对应测试 | [Test T06](../tests/T06-long-translation.md) |

## 交付行为

T05 的持久化 BYOK 翻译任务现在支持受限长度的多段 Markdown 长文翻译：每个分段按原序流式展示；只有全部 chunk 收到完整终态、正文非空且 Markdown 结构校验通过后，才沿用 T05 私有事务保存完整结果。

- 任务创建前读取模型目录的 context/output 元数据，拒绝未知预算、超长来源、超 chunk 数或不可安全拆开的结构；不会静默截断。
- 模型输入按 UTF-8 字节和输出 token 限额保守界定；fenced code 不发给模型、原样回传。分段在可识别的 Markdown 原子范围外切开，最终校验标题级别、列表标记/缩进、行内代码、链接目标、引用定义、表格行列及围栏。
- 每段使用 Responses streaming、`store=False`、0 SDK retries；执行前及每个 delta/terminal 检查 T05 凭据与任务 fence。任一段 EOF、incomplete、failed、空响应或结构损坏都会中止完整结果保存。
- 继续复用 T05 owner/session 权限、冻结输入、凭据 epoch、任务租约、SSE、私有缓存；未改前端，没有增加队列、模型 fallback 或通用文档编译器。

预算边界、真实执行日志、测试命令、断言改动和 NOT_RUN 项详见 [Test T06](../tests/T06-long-translation.md)。PROVIDER_REAL 与浏览器 UAT 仍是 NOT_RUN；本地 PROXY_LOCAL 只证明 T06 服务实际走通 OpenAI SDK、锁定 LiteLLM 和合成 upstream。
