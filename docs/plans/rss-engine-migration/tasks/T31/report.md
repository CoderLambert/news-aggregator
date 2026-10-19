# T31：旧栈清理候选与隔离验收

独立候选已实现并验证，集成状态仍为 IN_PROGRESS：[Draft PR #154](https://github.com/CoderLambert/news-aggregator/pull/154)，源码 `7ff9900b5c2c6cb00c995c96f2187d5fbd64ebec`，基线 `6a2cc025c338ef0308024151be4fbd796f7f3a39`。**真实 T30 停止/重启与关键变更独立复核未完成，不得合并或发布。** main 保留运行兼容代码。原任务允许按合同先独立开发，T30 前置约束集成/完成。

## 实现与保留边界

- 复用 `safe_http` / `http_execution`；只把正文可读性、空白处理、建议问题缓存 CAS 的纯工具移入 `article_body_state`。删除 Scrapy、旧 Feed parser、网页 Provider、全文 worker、专属命令及依赖，不改名保留来源提取器。
- 保留历史模型、全部已应用迁移和字段；历史正文继续使用 ACL/版本读取。`fetch-full` 在文章授权后返回 410，不能创建意图或修改请求人。Miniflux 独立 refetch 保留。
- 旧管理/Provider URL 保留 Session/CSRF/管理员检查后返回 410。新管理页复用 RSS 连接状态和搜索索引控件，旧书签受权限约束后转入 RSS 管理；前端 capability 解析支持明确的退役原因。
- 默认 Compose 只保留 app/migrate/indexer；频道 overlay 保留。删除仓库旧 cron/timer 和抓取入口，`news start` 只启动前后端；没有操作已安装的宿主任务。
- 清单 v4 显式声明 crawler capability，备份校验同步支持，历史 v1–v3 语义保持。按精确项目/服务标签核对全部 writer 后才停止，包括当前 YAML 不再声明的旧角色；不删除容器或数据卷。只有显式选择历史能力清单才加载兼容角色 overlay，新清单默认不复活旧采集。
- 部署/回退 `--with-rss` 复用现有 RSS overlay，检查独立镜像同 SHA、非 root 和同步命令，以及同项目已健康的 Miniflux。已有 RSS 却未选该参数时，停止前退出；选择后恢复 RSS 并检查独立镜像/健康，全部成功才切换静态版本。失败保持项目 writer 停止；不创建或升级 Miniflux/PostgreSQL。

## 最终候选证据

[机器可读记录](../../../../verification/rss-t31-retirement-2026-10-20.json)含源码/基线、镜像身份、日志摘要、浏览器清理与保留的 NOT_RUN。原始日志位于 `/tmp/newshub-t31-validation-20261020/`。检查使用无 `.env` 工作树、合成数据、Python 3.12 / Node 22、只读依赖缓存；没有复制活动库或追加真实厂商请求。

| 检查 | 实际结果与范围 |
| --- | --- |
| 后端完整矩阵 | `bash ops/ci/benchmark-xdist.sh` 三根原混合入口，2005 PASS / 16 SKIP；2021 个收集/执行身份完全对账，单轮 166 秒、退出 0、无重试，源码 7ff9900 |
| 发布与 RSS 专项 | 135 PASS；旧接口、v4/旧清单、RSS 恢复、错误镜像、缺失/错误归属/不健康引擎、失败保持停止和静态版本保护。标准 shell 发布验收 PASS；shell 语法 PASS |
| 前端 | 99 文件 / 700 测试、类型检查、构建 PASS，Lint 只有 1 个既有 Hook warning。源码 c2eac3f，已核对到 7ff9900 的 frontend 零差异，复用该证据 |
| Django→官方 SDK→固定 Proxy | 原 T04/T05/T06/T09 联合用例 3 PASS；源码 3458fb2 到 7ff9900 的 backend/Proxy/probe 零差异，合成上游，不是真实厂商验收 |
| 实际应用/RSS 镜像 | 两个镜像的 revision 均为 7ff9900、用户 10001:10001，旧代码路径和 Scrapy/feedparser/Playwright 等包不存在；RSS 另无 Torch/Chroma/OpenAI/Anthropic，默认命令是 rss_sync_worker。大小仅作构建事实，不作为容量证明 |
| 轻量运行时 | 在实际轻量镜像执行 Django.setup、control_worker/reconciliation 导入 PASS；没有引擎请求或真实库迁移，不声称同步已验收 |
| G1 / G2 | 同源码镜像逐个执行，均 status=PASS、cleanup=PASS；45/68 个报告字段。G2 实际 Chromium 验证 RSS 管理、退役接口、停用会话、普通账号拒绝和账号隔离。真实 WSGI 客户端地址直接观察仍 NOT_RUN，字段数不等于全部独立检查通过 |
| 项目停止真实容器 | [脱敏记录](../../../../verification/rss-t31-retirement-container-stop-2026-10-20.json)：只停止自身合成项目的 crawler/full-content/indexer，另一项目仍运行，清理 PASS。后续改动仅收紧项目名上限并新增维护准入，停止逻辑保持；不代表 T30 宿主停止验收 |
| CI 结构与依赖 | Agent 结构 PASS；Python 3.12 CI unittest 50 PASS，156 项精确锁静态检查 PASS。实际 GitHub CI NOT_RUN：两台 runner offline，不能以本地检查代替 merge-gate |
| 真实 T30 / 独立复核 / T33 | NOT_RUN；生产按用户要求延期，候选保持 Draft、未合并 |

## 首次失败与对应修复

- 退役 admission 回归先复现预期 410、实际 202；修复为保留授权后拒绝旧抓取。旧采集专属正向测试随实现删除；混合测试保留权限、历史数据、迁移、HTTP 和备份断言，将死 mock 改为实际网络边界。完整矩阵中的首次失败日志保留，最终没有修改 skip 预算或隐藏重试。
- G2 首轮发现旧管理接口预期过时；按已审 410 退役合同更新。后续真实浏览器发现 capability 解析缺新原因，导致整个前端 fail-closed；先保留 1 FAIL / 17 PASS 复现，再修复并运行 700 项前端全集。
- RSS 健康页面 fixture 缺引擎身份而返回 503：仅加入合成 UUID/account，健康仍明确 engine_ready=false；不配置真实引擎或 Token。停用账户时 RSS 原合同返回 401，其余管理接口 403，分别保留精确断言和负例。
- 发布回归先复现现有 RSS 被停止但没有恢复，脚本错误返回 0（`rss-release-lifecycle-red.log`）。新增显式管理与维护前检查后，原负例及恢复/失败用例通过。旧 shell 夹具仍等待已移除的 compose stop：改为验证真实项目标签筛选及每个 Docker stop，保留备份失败和不兼容 schema 拒绝断言，未降低要求。

恢复仍遵循原 [ROLLBACK](../../ROLLBACK.md)，不默认逆迁移或覆盖数据。T31 的集成/完成、生产停止与最终单栈发布门禁继续保留；本报告没有批准这些操作。
