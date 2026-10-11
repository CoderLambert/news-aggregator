# Test T02 · 录入模型并显式验证

对应：[T02 Task](../tasks/T02-models-and-tests.md)。

> **状态：READY FOR REVIEW。** 模型配置 CRUD、显式文本/工具探测和固定 alias 的本地 Proxy 联调已通过。未知手动模型不会被动态路由。没有真实供应商请求；浏览器 E2E 与未来 BYOK 文章调用仍未运行。

## 提交与执行环境

| 项目 | 结果 |
| --- | --- |
| 父提交 / T01 PR | 8eb383991e1a0b83de07dd34aa40d5721172e7df / PR #34，Draft、未合并 |
| T02 CRUD 提交 | 2bcf1cb22d4f0e070bedc0de14272a90cf4b325d |
| T02 探测实现提交 | 80bc47180786071ba651ea256581dffad90c892a |
| 分支 / PR 目标 | task/byok-T02-models-and-tests / feat/byok-user-api-keys |
| T02 PR | [#36 Draft](https://github.com/CoderLambert/news-aggregator/pull/36) |
| 前置网关 | T00-G PR #35，Draft、未合并；测试源码提交 89e1694f071601b85cb604d6551af7836917199a |
| OS / 架构 | Linux 7.2.5-3-omarchy x86_64 |
| Python / Django / DRF / cryptography / pytest | 3.14.8 / 6.1.2 / 3.18.3 / 50.0.2 / 9.1.1 |
| Node / npm / Vitest / Vite | 24.21.0 / 11.19.0 / 4.1.7 / 8.0.13 |
| Docker Engine / Compose | 29.7.2 / 5.5.1 |
| 数据库 | Django 检查、迁移和测试均使用自动创建并清理的临时 SQLite；未打开仓库数据库 |
| 隔离 | Python venv /tmp/byok-t01-verify-20261012；空临时 HOME；只含测试 stub 的 /tmp/byok-t02-test-stubs；没有读取仓库 .env 或用户 Key |

## PROXY_LOCAL 合成联调

执行命令：

    /tmp/byok-t01-verify-20261012/bin/python scripts/byok/run_t02_proxy_local.py \
      --gateway-worktree /home/lambert/Documents/Codex/2026-10-11/task-2/news-aggregator-t00-g

联调基于 T00-G 源码提交 89e1694f071601b85cb604d6551af7836917199a。Proxy 和受控上游使用 ghcr.io/berriai/litellm:v1.105.0，镜像 digest 为 sha256:60947db020b57e204823d3fbc8bb295c85be890d7c9adcc77fb4f5fc2fe410b2。上游只接受测试脚本创建的合成用户 Key；provider egress 网络设为 internal。Django 通过随机临时项目的私有 gateway bridge IP 访问 Proxy，没有发布宿主机端口。

实际输出摘要：

    scope: T02_PROXY_LOCAL_SYNTHETIC_ONLY
    status: PASS
    text_probe: PASS
    tools_probe: PASS_FAILED_SAFELY
    upstream_request_count: 2
    provider_key_only_at_upstream: true
    secret_leak_check: PASS
    provider_real: NOT_RUN
    cleanup: PASS

文本探测成功。工具探测由合成上游明确返回无工具调用，接口安全记录 probe_not_supported，工具能力仍为 unknown。两个上游请求都只带对应用户的合成 Provider Key；项目虚拟 Key 和 master Key 没有转发，上游请求体不含 api_key，代理日志和上游记录没有发现任何合成密钥。临时容器、网络和卷均已清理。

## 后端验证

- api/tests 全量回归（最终稳定运行排除下述一个 SQLite 并发波动用例）：529 passed、1 skipped、1 deselected，51.49 秒。被跳过的是需要专用 runner 的 PROXY_LOCAL 测试；该测试已由上述 runner 单独执行。
- T02 定向模型 API / Proxy service 单测：16 passed，覆盖用户隔离、CSRF/no-store、预批准 alias、文章正文参数拒绝、单次尝试记账、迟到结果 fencing、无自动重试、固定 alias/请求头/请求体和重定向拒绝。
- 新增文章正文边界断言后，无过滤的全量回归出现一个既有波动：api/tests/test_subscription_recovery.py::test_simultaneous_database_connections_share_one_unique_task 在三个重复尝试中失败，报 SQLite OperationalError / task_storage_busy；它在此前一次无过滤全量运行中通过。没有修改该订阅恢复代码；除这一个用例外，全量过滤运行通过。
- manage.py check：System check identified no issues。可选 embedding 模块因隔离 stub 未安装而记录 preload warning。
- manage.py makemigrations --check --dry-run：No changes detected。
- 临时 SQLite 完整应用全部 Django migrations 成功，包括 api.0034_ai_model_configs_and_attempts 和 api.0035_aicallattempt_probe_kind。

执行全量 API 回归时只提供开发模式开关与合成加密密钥，SQLite 文件、HOME、缓存目录都是临时目录。为无需网络的翻译单测提供 deep_translator 测试 stub；没有向新闻源、供应商或网关外部地址发请求。

## 前端验证

| 命令 | 结果 |
| --- | --- |
| npm test -- --run | 68 个测试文件、481 个测试通过 |
| npm run typecheck | 通过 |
| npm run lint | 通过 |
| npm run build | Vite 转换 4338 个模块，构建通过 |
| python scripts/validate_build.py（仓库根目录） | Dist、JS imports、CSS files、Bundle size 全部通过 |

页面测试覆盖目录模型的收费确认、文本/工具分开触发以及未知手动模型禁用测试入口；API client 测试确认浏览器只发送 probe_kind，不提交用户 Key，并拒绝原始供应商响应字段。

## T02 场景状态

| 用例 | 场景 / 正确性约束 | 状态 |
| --- | --- | --- |
| T02-01 | 多模型 CRUD、用户/连接隔离、目录不可用时仍可手动保存 | PASS；没有浏览器 E2E |
| T02-02 | 每次用户显式探测都创建单独尝试记录，并提示可能收费 | PASS；本地合成 Proxy 共观察到 2 个请求 |
| T02-03 | 文本成功不推断工具能力；无工具调用保持 unknown | PASS；合成上游失败路径 |
| T02-04 | 替换 Key/配置更新会失效旧状态；迟到回执不能覆盖新版本 | PASS；epoch 竞态与 revision 失效单测 |
| T02-05 | 用户不能将未知模型、URL 或额外参数送入路由 | PASS；未知 alias 在创建尝试前返回 409 |
| T02-06 | 未核实 context 的模型不应自动发送整篇文章 | 防护 PASS：界面提示 context 未核实，探测接口拒绝 messages/文章正文；未来业务文章调用与长度裁剪 NOT_RUN |

## SDK / Proxy / Provider / UAT

| 等级 | 状态 | 证据 |
| --- | --- | --- |
| SDK_LOCAL | NOT_RUN | T02 探测通过 OpenAI-compatible HTTP endpoint，不调用供应商 SDK |
| PROXY_LOCAL | PASS | T00-G 固定 alias、真实 LiteLLM Proxy、本地受控 HTTP upstream；只使用合成凭据 |
| PROVIDER_REAL | NOT_RUN | 没有连接 DeepSeek 或其它真实供应商。用户提供的 direct baseline 未重放，也未读取用户 Key |
| UAT | NOT_RUN | 未运行浏览器端到端流程；后端 API、页面组件和服务测试已覆盖对应动作 |

唯一可测的服务端路由为 news.deepseek-flash。新增供应商或手动模型路由需先由运维批准。T02 不包含真实新闻/研究内容的 BYOK 业务调用；当前探测端点拒绝用户传入文章内容。
