# T14：AI/TTS 本地上下文与译文版本读取报告

状态：REVIEW_READY。隔离专项和直接回归通过；等待独立审查及批次集成，不代表生产或真实模型验收。

## 实现

任务分支 `task/rss-T14-ai-readers`，基线 `da2365c`。主调度提供并已作为依赖合入：0058 私有译文唯一键增加 source_hash（根提交 `37b6e03`，本分支 `b6f6412`）；0059 对存量兼容译文作一次精确字节绑定（根提交 `27086b5`，本分支 `e8424a1`）。这些依赖不重复作为 T14 自有 schema 交付。

- AI 问答、推荐问题、翻译、TTS、研究工具均以当前授权 StoredArticle 的正文或摘要为输入，携带 scope、revision、canonical_hash、completeness。详情标题、摘要、正文、revision、content_kind 从同一快照输出，避免旧 News 对象与新正文串配。
- `stored_readers` 统一当前快照核对、译文读取与精确源文本关键词检索。读取期间重新核对账号状态、当前政策、正文原始归属及 provenance；流式正文/翻译/语音输出前检查授权与版本。
- 私有译文按 user/当前 connection/news/source_hash 读取；共享译文按 news/source_hash 读取。私有译文源版本更新保留旧记录，普通重译不覆盖首份共享记录。共享旧任务完整结果按旧 hash 保存历史并报 stale，不返回为当前译文；私人任务沿用持久 lease/generation/source hash CAS，旧 progress/result 留存但当前 API 不释放已失权数据。
- legacy / legacy-bound 归档只有精确 source_text 和 source_hash 与当前源字段一致才展示；保留 legacy 来源标记，不伪造 provider 或连接身份。原始 title_zh/content_zh/full_content_zh 字段不再无条件回退。0059 是停止写入升级时对现存字段作的一时点精确绑定，不宣称旧译文曾有独立服务商验证。
- 删除中文译文外链发现与抓取函数。研究 fetch_article/fetch_webpage 只读已同步且获授权的内容；未知 URL 返回已有搜索摘要/链接能力提示，不排队旧抓取。联网 search_web 保留，通用 HTTP 安全与取消工具迁到 services/safe_http.py 和 http_execution.py；旧 article_fetcher 路径仅模块别名兼容 shim，不复制提取算法。
- 研究本地搜索/向量候选先 SQL ACL、返回前重授权；中文关键词搜索保留，但仅匹配精确源文本绑定的译文。研究历史证据、事件回放和后续模型上下文复核当前读取权及版本，旧工具消息也核对；被撤回的结果留在数据库中但不从当前 API 重放。
- 推荐问题使用现有 JSON 字段的 `{questions, article_context}` 缓存结构，旧无版本数组不作当前结果。聊天 assistant 消息增加 article_context；来源不明或当前不匹配的 assistant 历史保留数据库但不进入当前正文读取/AI 上下文。
- 修复两个 T11 集成回归：合法旧来源、双 owner 空且正文缺失可进入 T25 原子认领；有正文政策授权的 legacy 摘要可保留安全排队状态。列表不逐条调用 RSS refetch eligibility，避免引入 N+1。列表译文只增加一条批量读取，1/20 行固定 6 次查询，semantic 6、hybrid 7。

## 验证环境与实际结果

Python 3.12.14；只读使用 `/tmp/newshub-rss-coordinator-venv`；worktree `/tmp/newshub-rss-T14`。每组设置 `RUN_MAIN=true PYTHONPATH=backend:crawler` 与独立 `/tmp/newshub-t14-*.sqlite3` 数据库；未读写用户数据库。模型、订阅提供方、向量和搜索提供方使用 fixture/mock，没有真实模型付费或发布者抓取。

所有以下 pytest 命令使用：

```bash
RUN_MAIN=true DJANGO_DB_PATH=/tmp/newshub-t14-<group>.sqlite3 PYTHONPATH=backend:crawler \
  /tmp/newshub-rss-coordinator-venv/bin/python -m pytest <files> -q --tb=short
```

| 组 | files（均位于 backend/api/tests/） | 实际结果 |
| --- | --- | --- |
| 合同与直接回归 | rss/test_ai_readers.py、rss/test_access_contract.py、test_news_summary.py、test_shared_translations.py、test_translation_jobs.py、test_llm_translation_prompt.py、test_research_evidence.py | 113 passed，20.96s；日志 `/tmp/newshub-t14-contract-regression.log` |
| 旧 reader 兼容 | test_chat_completion.py、test_chat_context.py、test_chat_ownership.py、test_chatgpt_subscription.py、test_live_attach.py、test_provider_credentials.py、test_suggested_questions.py、test_tts_endpoint.py | 127 passed，27.45s；日志 `/tmp/newshub-t14-readers-final.log` |
| 持久任务与恢复 | test_subscription_recovery.py、test_subscription_submission_locks.py、test_subscription_worker_locks.py、test_research_recovery.py、test_research_csrf.py | 71 passed，31.36s；日志 `/tmp/newshub-t14-recovery-regression.log` |
| 公共 HTTP 抽离 | test_safe_http.py、test_budgeted_safe_http.py、test_research_http_budget_routes.py、test_research_tool_cancellation.py | 75 passed，3.33s；日志 `/tmp/newshub-t14-network-regression.log` |
| 最后快照细节 | test_ai_readers.py::test_translation_uses_new_snapshot_not_stale_news | 1 passed，3.16s；断言旧 News 对象得到新标题、正文、revision 2 和匹配译文 |

最终关键词 helper 复用、研究旧工具消息核对及新增中文搜索反例后，重跑 rss/test_ai_readers.py、test_news_summary.py、test_research_recovery.py、test_research_evidence.py、test_research_tool_cancellation.py：**81 passed，10.33s，退出码 0**；日志 `/tmp/newshub-t14-last.log`。旧测试 fixture 显式创建 SourcePublication/legacy owner/精确译文快照，未设置全局自动公开信号。删除外链抓取、禁止隐式排队、版本缓存结构的旧测试已按 ADR-002/C04 更新；旧账号隔离、CSRF、持久任务与请求预算断言保留。

`manage.py check` 退出 0，只有未构建前端资源目录的 staticfiles.W004。`git diff --check` 通过。0058/0059 的独立迁移专项由主调度执行并提供证据，不重复运行；本组临时测试库正常应用全部当前迁移。

## 验收与限制

T14-A1：available/unknown 正文被允许消费，scope/revision/hash/completeness 明确；旧对象与新快照反例通过。T14-A2：summary 不当全文，TTS/翻译拒绝 full 请求，推荐问题和聊天准确标范围。T14-A3：迟到共享结果只作为旧 hash 历史、私有跨 hash 版本保留、连接切换/撤权不泄漏缓存或任务结果。T14-A4：无中文外链、研究无旧 Provider/排队，显式联网搜索及取消/安全预算继续有效。

未运行全仓、浏览器、真实 AI/TTS/搜索外部服务或部署；T27 仍需真实阅读/AI 组合验收。流式授权检查增加短数据库读取，长研究会话还需在最终容量测试中观察性能。现有明确 legacy fetch-full 过渡入口保留，由 T25 fence 约束；T31 才整体删除旧栈。

恢复可 revert 本任务应用提交；保留新增译文历史与 0058/0059 schema，不自动逆迁移或恢复数据库。未执行生产操作、main 合并、强推或数据清理。
