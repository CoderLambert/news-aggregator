# Test T06 · 长文分块完整翻译

> 本文按冻结契约 `ed58afa7a72ae905e2a2ffc315d968ca3634b8f2` 记录 PR #130 的实现和证据。当前 main 起点没有该 T06 Test 文件，因此本 PR 新建此证据页；未修改权威开发计划。所有未实际执行的项继续标记 NOT_RUN。

对应冻结任务：`docs/features/byok/tasks/T06-long-translation.md`（同一冻结提交）。

## 当前代码范围

- PR：[ #130 · T06 bounded private long translation](https://github.com/CoderLambert/news-aggregator/pull/130)
- 分支：`codex/byok-t06-long-translation-20261019`
- 基线 main：`675a846fc6dd8f58fe80e18950679fc9ca5032f8`
- 被本证据记录的代码/测试/probe HEAD：`3e36a4ef0b093a18a4c2c3f3be56a2d1b9a25597`；本文件是随后追加的证据文档提交。
- 任务状态：代码尚未合并；无生产请求或真实 provider 调用。

| 用例 | 实现及拟验证的约束 | 结果 |
| --- | --- | --- |
| T06-01 | 后端合成用例覆盖多 chunk 的中文译文按原顺序合并，保留顶层 fenced code、heading、link target、table 结构和段落边界；detail/latest GET 刷新得到相同私有 result，不重新 dispatch。 | NOT_RUN |
| T06-02 | 中间 chunk 的 EOF、finish_reason=length、空输出分别失败；仅保存已完整验证 chunk 的 progress，无完整 result/cache，下一次 worker 调用不重放不确定请求。 | NOT_RUN |
| T06-03 | 入队后源文变更在 dispatch 前拒绝；第一块完成后源文、credential epoch 或 model revision 改变时，不发送后续块且不提交完整结果。 | NOT_RUN |
| T06-04 | 未知/漂移 profile、context、output 或请求 byte budget 显式拒绝，不截断。预算守卫将 UTF-8 请求字节与输出 token 上限分开；没有声明 bytes=provider tokens。 | NOT_RUN |
| T06-05 | T05 短/中篇路径仍是单次请求；旧订阅任务/结果保持原行为。 | NOT_RUN |

## 代码与负例覆盖（尚未执行）

- `backend/api/services/ai_private_translation.py`：重用 T05 task/snapshot/result、lease/claim/CAS、raw stop + clean EOF verifier 和私有结果写入；最多 8 个顺序 chunk，每块单次 dispatch marker，chunk 失败不自动重放。无需新增 task 表或迁移。
- `backend/api/tests/test_ai_private_translation_t05.py`：新增多块 Markdown 合并、分隔符恢复、GET 刷新、队列/后续 chunk owner/source/model/credential fence、EOF/length/empty、预算漂移和不支持 Markdown 拒绝用例；未通过放宽已有断言来让实现通过。
- `frontend/src/components/news-detail/PrivateTranslationPanel.tsx` 与 `frontend/tests/components/news-detail/PrivateTranslationPanel.test.tsx`：长文明确提示最多 8 次顺序 billable model request，并告知失败后已派发请求仍可能计费；短文保留单次路径。
- `tools/byok_t00_probe/t04_django_localproxy.py`：加入双 chunk 成功/第二块 length 失败的 SDK→固定 LiteLLM Proxy→synthetic upstream 探针；代码已加入，但没有运行，不代表 SDK_LOCAL 或 PROXY_LOCAL 已验证。
- Markdown 支持是有界子集：顶层 fenced block 的代码载荷与围栏签名会在每块译文中校验。入队前拒绝引用围栏（包括 `>  ~~~` / `>   ~~~`）、列表项同一行的围栏（如 `- ~~~`、`1. ```py`、引用列表形式），以及 4 个及以上空格或 tab 缩进的围栏；这些拒绝形式有 preflight negative fixtures。列表项之后单独缩进 1–3 格的 child fence 会按普通顶层 fence 识别，并比对代码载荷/围栏，但 parser 不验证列表容器语义；不宣称对所有 CommonMark 嵌套结构均有完整解析。

## 容量依据与安全边界

长文路径只接受固定的 `deepseek/deepseek-flash` proxy alias、DeepSeek provider、`deepseek_default` endpoint profile/version 和本地版本化 capability profile。当前 T02 model payload 对 context window 返回未知时，不从 alias 或模型配置猜容量；未知、配置漂移和预算超限都 fail closed。DeepSeek 官方 pricing 页面列示此 alias 的 1M context / 384K max output，Chat API 文档说明总输入+输出受 context 约束；token usage 文档说明字符/token 比例因模型而异。因此输入字节、系统提示/协议 reserve 与每块/全任务 output tokens 是彼此独立的保守产品上限，不是 tokenizer 的精确 token 证明。

- [DeepSeek pricing](https://api-docs.deepseek.com/quick_start/pricing/)
- [DeepSeek Chat API](https://api-docs.deepseek.com/api/create-chat-completion/)
- [DeepSeek token usage](https://api-docs.deepseek.com/quick_start/token_usage/)

## 执行证据

| 项目 | 结果 |
| --- | --- |
| 当前记录时间 | 2026-10-19 05:32 UTC |
| T06-01…T06-05 | 全部 NOT_RUN；没有执行本地测试命令或浏览器/UAT。 |
| 本地环境、DB、Python/Node、浏览器/OS 版本 | NOT_RUN；本轮只读写 GitHub connector，没有运行本地环境或安装依赖。 |
| 定向 Django/DB/HTTP/worker/Vitest 测试 | NOT_RUN。 |
| 代码/测试基线对照 | NOT_RUN；基线 SHA 已记录为 main `675a846f…`。 |
| SDK_LOCAL / PROXY_LOCAL / PROVIDER_REAL / UAT | 全部 NOT_RUN。虽已增加 synthetic SDK/Proxy probe，未实际执行。 |
| CI run #906，source HEAD `0bce5b78eaaa0283e487cf7053a1af1ecac8fd46` | 成功，但仅 `changes`、`dev-frontend`、`dev-backend` 成功；`frontend`、`backend-and-release-gates`、`merge-gate` 均 skipped。这不是 T06 功能测试证据。[run #906](https://github.com/CoderLambert/news-aggregator/actions/runs/39204580385) |
| CI run #909，source HEAD `3e36a4ef0b093a18a4c2c3f3be56a2d1b9a25597` | 已取消：`changes` 成功，`dev-backend` 被取消；其他前端/full-gate jobs skipped。没有 T06 Django 或功能测试结果。[run #909](https://github.com/CoderLambert/news-aggregator/actions/runs/39204822206) |
| CI run #910，source HEAD `b8edae7211ddcf47ed49904704aa48936a544abc` | workflow success，但此提交仅改证据文档：只有 `changes` 执行，dev/full/frontend/merge-gate jobs 均 skipped；不代表产品验证。[run #910](https://github.com/CoderLambert/news-aggregator/actions/runs/39204961514) |
| 真实 provider、生产数据、部署 | 未使用。 |

不要将 scoped fast CI 误写为 T06 PASS；在相关后端/前端/full gate、SDK_LOCAL/PROXY_LOCAL 和 UAT 真实执行前，所有对应证据必须保持 NOT_RUN。
