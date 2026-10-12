# Test T09 · 首次个人模型深度研究

对应：[T09 Task](../tasks/T09-research-first-run.md)。

> **READY FOR REVIEW。** 已验证个人模型的研究请求能经业务后端和 LiteLLM Proxy 完成工具往返，并将工具结果、Run/Event 和最终报告持久化。真实 provider/UAT 尚未运行，因此本卡不标记为完整 PASS。

## 提交与执行环境

| 项目 | 结果 |
| --- | --- |
| T03 父提交 / 父分支 | `68895c1e26660564ddc01d474caaef510770a22b` / `task/byok-T03-preferences` |
| T03 PR | [#37 Draft](https://github.com/CoderLambert/news-aggregator/pull/37)，未合并 |
| T09 实现提交 | `72e800582336739c798764490d8881a789a9a233` |
| T09 分支 / PR base | `task/byok-T09-first-research` / `task/byok-T03-preferences` |
| T09 PR | [#43 Draft](https://github.com/CoderLambert/news-aggregator/pull/43)，未合并 |
| 日期 | 2026-10-12（Asia/Shanghai） |
| OS / 架构 | Linux 7.2.5-3-omarchy x86_64 |
| Python / Django / DRF / pytest | 3.14.8 / 6.1.2 / 3.18.3 / 9.1.1 |
| OpenAI SDK / httpx2 | 3.28.0 / 2.13.1 |
| SQLite | 3.53.1 |
| Docker Engine / Compose | 29.7.2 / 5.5.1 |
| 测试数据库 | 独立临时 SQLite；没有迁移或读写共享/生产数据库 |
| 隔离 | venv `/tmp/byok-t01-verify-20261012`、测试 stub `/tmp/byok-t02-test-stubs`、临时 HOME/cache；拒绝读取仓库及网关 `.env`，未读取用户 provider Key |

## 后端回归

完整套件使用隔离环境和合成 `DJANGO_SECRET_KEY` 运行：

```sh
env -i \
  PATH=/tmp/byok-t01-verify-20261012/bin:/usr/bin:/bin \
  HOME=/tmp/byok-t01-empty-home \
  PYTHONPATH=/tmp/byok-t02-test-stubs:$PWD/backend:$PWD/crawler \
  DJANGO_ENV=development \
  DJANGO_SECRET_KEY=t09-synthetic-only-not-a-secret \
  DJANGO_DB_PATH=/tmp/byok-t09-final-backend-20261012.sqlite3 \
  CHROMA_DATA_DIR=/tmp/byok-t09-final-chroma \
  TTS_CACHE_DIR=/tmp/byok-t09-final-tts \
  RUN_MAIN=true \
  /tmp/byok-t01-verify-20261012/bin/python -m pytest backend/api/tests -q
```

结果：`548 passed, 2 skipped, 2 warnings in 58.41s`。两个跳过项需要专用本地 runner；两条 warning 是现有 Category/Source 列表分页未显式排序提示。

T09 原有定向测试 `backend/api/tests/test_research_byok.py` 曾为 `10 passed in 3.34s`。审核修复后重新运行 `test_research_byok.py` 与 `test_research_byok_proxy_local.py`：`15 passed, 1 skipped, 1 warning in 4.62s`，包含新增撤销阶段和工具批次断言。

T03 父提交上的旧 T09 相关测试曾以 `151 passed in 30.94s` 作为实现前基线。另一次扩大到翻译恢复相关用例的基线尝试为 `166 passed, 1 failed`。后续 SQL trace 已确认失败由 `SQLITE_LOCKED_SHAREDCACHE` 引起，具体落在任务 claim 或最终提交 CAS；这不是普通业务回归。该问题作为独立 R0 修复，不混入 T09。R0 已在独立工作树上复现并修复；由于 R0 尚未进入当前 T09 分支，此处不把它计入 T09 的验证结果。

## PROXY_LOCAL 合成端到端

执行命令：

```sh
/tmp/byok-t01-verify-20261012/bin/python scripts/byok/run_t09_proxy_local.py \
  --gateway-worktree /home/lambert/Documents/Codex/2026-10-11/task-2/news-aggregator-t00-g
```

网关配置源码来自 T00-G 提交 `89e1694f071601b85cb604d6551af7836917199a`。测试使用锁定镜像 `ghcr.io/berriai/litellm:v1.105.0@sha256:60947db020b57e204823d3fbc8bb295c85be890d7c9adcc77fb4f5fc2fe410b2`、真实 OpenAI SDK、受控合成 upstream 和临时项目网络。provider、项目 virtual key、master key 均为本次随机生成的合成值；无宿主机公开端口，测试完成后删除容器、网络和卷。

脱敏后的实际输出：

```json
{"cleanup":"PASS","gateway_source":"/home/lambert/Documents/Codex/2026-10-11/task-2/news-aggregator-t00-g","model_alias":"news.deepseek-flash","provider_key_only_at_upstream":true,"provider_real":"NOT_RUN","scope":"T09_PROXY_LOCAL_SYNTHETIC_ONLY","secret_leak_check":"PASS","status":"PASS","tool_calls":"PASS","upstream_request_count":2}
```

两个受控上游请求完成一次 `search_news` 工具往返和最终报告；记录确认 upstream 只收到用户合成 provider key，未收到项目 virtual key/master key 或请求体 `api_key`。Run/Event、工具搜索结果和最终报告都已写入临时数据库；日志与返回记录的合成密钥扫描通过。

## T09 场景结果

| 用例 | 证据 | 状态 |
| --- | --- | --- |
| T09-01 | 合法工具调用、工具结果持久化、最终报告提交；合成 Proxy 真实 SDK 联调通过 | PASS（合成 upstream） |
| T09-02 | 生产环境 BYOK 关闭或缺模型时拒绝建任务；只允许启用开关且存在合格个人模型的路径 | PASS（策略与 worker 自动化测试） |
| T09-03 | tools 未验证时拒绝排队；整批工具调用在执行前校验，混合非法参数和超过 8 个调用均零工具执行/零工具结果/零工具事件 | PASS |
| T09-04 | 排队、Provider 请求中、工具结果保存后、最终提交事务开始前撤销凭据；旧 epoch 不提交成功报告或 complete 事件 | PASS；最终事务先条件更新锁定连接行，再锁定模型配置并核验快照 |
| T09-05 | 工具结果写入失败、任务取消、Run CAS 失败 | PASS；不能误报 succeeded |
| T09-06 | 同快照幂等请求只排队一次；模型变更后的同一 key 冲突；owner 私有 GET 返回已保存报告，Run/Event 顺序正确 | PASS |

## 凭据撤销和工具批次审核修复

最终结果写入现在在同一 `atomic()` 事务内，先按 owner、连接 ID、enabled/deleted 状态、credential epoch、Provider 和 endpoint profile 条件更新连接行（SQLite 获取写锁；支持行锁的数据库同时锁定该连接行），再 `select_for_update()` 锁住模型配置并重新核验模型/验证快照。若撤销先提交，epoch 条件失败，不能写入成功 session、Run 状态或 complete 事件；若最终事务先取得锁，则撤销只能排在该事务之后提交。

BYOK 每次工具响应最多允许 8 个调用。所有调用的 type、唯一 ID、工具名、UTF-8 参数长度、标准 JSON（拒绝重复键/非标准常量）、对象形状和工具 schema 都先通过后，才保存 assistant 调用消息、发工具事件或执行任何工具。测试用“第一个调用合法、第二个调用参数非法”的批次确认第一项也不会先执行。

四个确定性撤销测试分别在排队后、Provider 响应生成期间、工具结果持久化后，以及最终提交入口（刚通过外部 guard、尚未开始最终事务）撤销连接。前两阶段禁止继续处理并保留空历史；工具完成阶段禁止后续工具结果事件和报告提交；最终阶段确认事务内 epoch 检查拒绝报告提交。

测试代码差异：旧 `test_public_policy.py` 仅为原有 AI 关闭场景显式设置 `AI_BYOK_ENABLED=False`，使其固定覆盖原先关闭语义；旧断言没有删除或放宽。其余新增断言位于 `test_research_byok.py`、`test_research_byok_proxy_local.py` 和新增的 capability 策略用例。

`python backend/manage.py check` 通过；仅有仓库当前缺少 `frontend/dist/assets` 的既有静态目录 warning。`python backend/manage.py makemigrations --check --dry-run` 输出 `No changes detected`。在独立临时 SQLite 上完整迁移通过，包括 `api.0037_research_execution_snapshot`。生产/shared DB migration 为 NOT_RUN。

## SDK / Proxy / Provider / UAT 边界

| 级别 | 状态 | 证据 / 限制 |
| --- | --- | --- |
| SDK_LOCAL | NOT_RUN（独立路径） | 官方 OpenAI SDK 已在 PROXY_LOCAL 中实际调用；没有另跑 SDK 直连受控 upstream 的独立测试 |
| PROXY_LOCAL | PASS | 上述固定 LiteLLM Proxy + OpenAI SDK + 合成 upstream，两次请求、工具续接、密钥边界和清理均通过 |
| PROVIDER_REAL | NOT_RUN（T09） | T09 没有向真实 provider 发研究/工具请求。本对话此前提供过一次单独 DeepSeek 非流式调用结果，但它不是此 T09 持久研究链路的证据，故不计入本卡 |
| UAT | NOT_RUN | 未由真实用户在浏览器完成选模型→发起研究→查看历史报告的流程 |
| 生产迁移 / 部署 | NOT_RUN | 只在临时 SQLite 验证迁移；未部署或连接生产服务 |

本卡状态保持 **READY FOR REVIEW**，不将合成 Proxy 测试或此前单次 DeepSeek 调用表述为真实 provider 研究兼容性。
