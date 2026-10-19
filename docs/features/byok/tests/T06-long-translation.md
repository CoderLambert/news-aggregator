# Test T06 · 长文分块完整翻译

> 本文按冻结契约 `ed58afa7a72ae905e2a2ffc315d968ca3634b8f2` 记录 PR #130 的实现和证据。当前 main 起点没有该 T06 Test 文件，因此本 PR 新建此证据页；未修改权威开发计划。所有未实际执行的项继续标记 NOT_RUN。

对应冻结任务：`docs/features/byok/tasks/T06-long-translation.md`（同一冻结提交）。

## 当前代码范围

- PR：[ #130 · T06 bounded private long translation](https://github.com/CoderLambert/news-aggregator/pull/130)
- 分支：`codex/byok-t06-long-translation-20261019`
- 本批次合入的 main 基线：`5770062ad10d923ca28c90fe4a4f3709adc30939`；共同 merge base：`675a846fc6dd8f58fe80e18950679fc9ca5032f8`。
- 上一轮完整 CI 记录的代码/测试 HEAD：`d10560f9762cc9718aac3b33d74b9628ffe81f78`（PR merge SHA `3bc68b672f4e51c6efd9eaf725162e31e58e2229`，当时 base 为 `675a846fc6dd8f58fe80e18950679fc9ca5032f8`）。本次合并到 main `5770062ad10d923ca28c90fe4a4f3709adc30939` 并修正测试断言/夹具后的新 HEAD 尚待 CI。
- 任务状态：代码尚未合并；无生产请求或真实 provider 调用。

| 用例 | 实现及拟验证的约束 | 结果 |
| --- | --- | --- |
| T06-01 | 后端用例覆盖多 chunk 中文译文合并及 detail/latest GET 刷新同一私有 result、无 redispatch。 | PASS（#912 backend run） |
| T06-02 | EOF、finish_reason=length、空输出须失败，仅留已验证 progress，不产生完整 result/cache 且不重放。 | #912 三个子例均因测试把 JSON 默认 `{}` 误断言为 `None` 而失败；本批次改为检查空 result，修复后新 HEAD 尚未验证。 |
| T06-03 | 入队和后续 chunk 的源文/credential epoch/model revision fence。 | #912 queued/source 两处同样受 `None` vs `{}` 断言影响；credential/model 子例重用了相同源文哈希而触发预期 409。此批次修正空 result 断言和子例源文唯一性；新 HEAD 尚未验证。 |
| T06-04 | 未知/漂移 profile、context、output 或请求 byte budget 显式拒绝；不截断，bytes 与 token 是分立上限。 | PASS（#912 backend run） |
| T06-05 | T05 短/中篇单请求和旧订阅任务/结果回归。 | #912 oversize 负例测试把 T06 请求限额误 patch 为旧 T05 常量，导致 202/400 期望失配；本批次将 fixture 改为 patch T06 专属限额。新 HEAD 尚未验证。 |

## 代码与负例覆盖（实现与执行情况）

- `backend/api/services/ai_private_translation.py`：重用 T05 task/snapshot/result、lease/claim/CAS、raw stop + clean EOF verifier 和私有结果写入；最多 8 个顺序 chunk，每块单次 dispatch marker，chunk 失败不自动重放。预发送 SQLite lock 只对凭据准入与标记后的 fresh fence DB 读取做有界重试，gateway 构造和 provider `.create()` 均不在重试边界内。无需新增 task 表或迁移。
- `backend/api/tests/test_ai_private_translation_t05.py`：新增多块 Markdown 合并、分隔符恢复、GET 刷新、队列/后续 chunk owner/source/model/credential fence、EOF/length/empty、预算漂移和不支持 Markdown 拒绝用例；修正 #912 的限额 patch、JSON 空对象断言、唯一源文夹具，并为 #913 暴露的真实预发送 SQLite contention race 加入确定性重试/撤销/一请求负例。
- `frontend/src/components/news-detail/PrivateTranslationPanel.tsx` 与 `frontend/tests/components/news-detail/PrivateTranslationPanel.test.tsx`：长文明确提示最多 8 次顺序 billable model request，并告知失败后已派发请求仍可能计费；短文保留单次路径。
- `backend/api/services/ai_worker_fencing.py`：将 T01 的 DB-only `prepare_dispatch` 从 `dispatch_once` 提取出来；`dispatch_once` 公共行为/API不变。BYOK 只重试预发送 DB-only 凭据准入和 CAS 标记/post-marker fence，外部调用仍单次。
- `tools/byok_t00_probe/t04_django_localproxy.py`：加入双 chunk 成功/第二块 length 失败的 SDK→固定 LiteLLM Proxy→synthetic upstream 探针；run #912 实际执行通过（SDK_LOCAL=PASS、PROXY_PROCESS_LOCAL=PASS，239 passed/0 failed），只证明合成 SDK/本地 Proxy 路径。
- Markdown 支持是有界子集：顶层 fenced block 的代码载荷与围栏签名会在每块译文中校验。入队前拒绝引用围栏（包括 `>  ~~~` / `>   ~~~`）、列表项同一行的围栏（如 `- ~~~`、`1. ```py`、引用列表形式），以及 4 个及以上空格或 tab 缩进的围栏；这些拒绝形式有 preflight negative fixtures。列表项之后单独缩进 1–3 格的 child fence 会按普通顶层 fence 识别，并比对代码载荷/围栏，但 parser 不验证列表容器语义；不宣称对所有 CommonMark 嵌套结构均有完整解析。

## 容量依据与安全边界

长文路径只接受固定的 `deepseek/deepseek-flash` proxy alias、DeepSeek provider、`deepseek_default` endpoint profile/version 和本地版本化 capability profile。当前 T02 model payload 对 context window 返回未知时，不从 alias 或模型配置猜容量；未知、配置漂移和预算超限都 fail closed。DeepSeek 官方 pricing 页面列示此 alias 的 1M context / 384K max output，Chat API 文档说明总输入+输出受 context 约束；token usage 文档说明字符/token 比例因模型而异。因此输入字节、系统提示/协议 reserve 与每块/全任务 output tokens 是彼此独立的保守产品上限，不是 tokenizer 的精确 token 证明。

- [DeepSeek pricing](https://api-docs.deepseek.com/quick_start/pricing/)
- [DeepSeek Chat API](https://api-docs.deepseek.com/api/create-chat-completion/)
- [DeepSeek token usage](https://api-docs.deepseek.com/quick_start/token_usage/)

## 执行证据

| 项目 | 结果 |
| --- | --- |
| 当前记录时间 | 2026-10-19 05:47 UTC |
| T06 定向 backend | #912 执行了全后端套件；T06-01、T06-04 通过，T06-02/03/05 的测试断言/夹具失败，具体见上表；修复后的新 HEAD 尚未运行。 |
| 本地环境、DB、Python/Node、浏览器/OS 版本 | NOT_RUN；本轮只读写 GitHub connector，没有运行本地环境或安装依赖。 |
| CI 执行环境 | Python 3.12.3、pytest 9.1.1、Django 6.1.2、pytest-xdist 3.8.0、2 workers。 |
| 代码/测试基线对照 | 只读比较确认分支 `d10560f` 与 main `5770062` 的共同基线为 `675a846`；main 多 1 个提交。本批次以 main tree 为合并基底，保留全部 6 个 T06 改动文件及共享 polling probe，并增加 T01 纯 helper 抽取；RSS 的 main-only 三文件保持 main 版本。 |
| SDK_LOCAL / PROXY_PROCESS_LOCAL / PROVIDER_REAL / UAT | run #912 synthetic probe：PASS / PASS / NOT_RUN / NOT_RUN。没有真实 provider 请求或 UAT。 |
| CI run #906，source HEAD `0bce5b78eaaa0283e487cf7053a1af1ecac8fd46` | 成功，但仅 `changes`、`dev-frontend`、`dev-backend` 成功；`frontend`、`backend-and-release-gates`、`merge-gate` 均 skipped。这不是 T06 功能测试证据。[run #906](https://github.com/CoderLambert/news-aggregator/actions/runs/39204580385) |
| CI run #909，source HEAD `3e36a4ef0b093a18a4c2c3f3be56a2d1b9a25597` | 已取消：`changes` 成功，`dev-backend` 当时仍 queued/no result；其他前端/full-gate jobs skipped。[run #909](https://github.com/CoderLambert/news-aggregator/actions/runs/39204822206) |
| CI run #910，source HEAD `b8edae7211ddcf47ed49904704aa48936a544abc` | workflow success，但此提交仅改证据文档：只有 `changes` 执行，dev/full/frontend/merge-gate jobs 均 skipped；不代表产品验证。[run #910](https://github.com/CoderLambert/news-aggregator/actions/runs/39204961514) |
| CI run #912，PR code head `d10560f9762cc9718aac3b33d74b9628ffe81f78`，merge SHA `3bc68b672f4e51c6efd9eaf725162e31e58e2229` | workflow failure：`frontend` 成功；`backend-and-release-gates` 的后端全套件 8 failed、2486 passed、16 skipped；`merge-gate` 因后端失败；dev jobs skipped。BYOK T00 synthetic SDK/Proxy step 独立 PASS。具体 8 个失败都是上述 test fixture/assertion 问题，详见 [run #912](https://github.com/CoderLambert/news-aggregator/actions/runs/39205284719)。 |
| 本批次修复/整合后 HEAD | 后端/前端/release/merge 全门禁尚未对新提交运行；修复后的结果必须等待最新 CI。 |
| CI run #913，main HEAD `5770062ad10d923ca28c90fe4a4f3709adc30939` | backend run failure：1 failed、2479 passed、16 skipped；唯一失败是 BYOK T05 concurrent POST/worker-claim exactly-once test，两个 worker 出现分类的 `SQLITE_LOCKED_SHAREDCACHE` (262) contention during admission/claim，导致未调用 provider。此批次加入预发送 DB-only retry 与锁注入/撤销回归；不重试 `.create()` 或网络。该 run 的 `backend-and-release-gates` failed，T00 synthetic SDK/Proxy step passed，其他 release jobs skipped。[run #913](https://github.com/CoderLambert/news-aggregator/actions/runs/39205855011) |
| 真实 provider、生产数据、部署 | 未使用。 |

不要将 #912 workflow 总体状态误写为 PASS。新批次快进当前 main，修正 T06 测试夹具/断言并收窄修复预发送数据库 contention；该批次的完整后端、前端、release/merge gates 仍待新 CI 验证。真实 provider 和 UAT 仍为 NOT_RUN。
