# T11：统一授权读取交付报告

实现状态：REVIEW_READY。隔离模块专项和直接回归通过；关键权限独立复核、批次集成和生产验收尚未完成。

## 实现与接口

- 初始接口提交 `2dd70dd`（主调度已以 `5a8cae3` 集成）；本报告所属提交补齐现有入口与批量列表授权。任务分支 `task/rss-T11-access`，基线 `21bbd10`。
- `authorized_sources` / `authorized_news` 在 SQL 中限制来源及文章；缺少 SourcePublication 默认拒绝。public 与 personal 的历史可见范围不随 paused 改变；personal 退订立即撤销，收藏不授予权限。
- `body_authorized_news` 独立检查当前正文政策、原始来源、绑定/账号/引擎/entry provenance。相同 URL 或关联频道只扩展身份成员关系，不扩展正文读取权。legacy / complete / available、空白正文与 summary completeness 使用一致规则。
- `get_stored_article(user, news_id)` 返回 C05 StoredArticle，拒绝或未知 ID 为 Http404；正文授权与正文数据在同一 SQL 快照中取得。`get_article_access` 提供不传输完整正文的预览授权。均不发起抓取。
- 已存储正文保留 scope=full/summary、revision、canonical_hash、completeness、policy_versions、provenance。序列化新增 full_content_completeness、content_completeness、has_readable_content；body_owner 保持 `legacy` / `miniflux` / null 字符串契约，摘要权限不泄漏正文状态及正文 provenance。
- 列表、直接 ID、关键词/向量候选、收藏、屏蔽、来源/分类计数、频道目录/解析、阅读统计均先授权。响应使用 private, no-store。隐藏主来源通过允许的关联来源呈现；旧订阅入口不能猜测 private 来源 ID 自授权限。
- 文章页翻译/TTS 缓存入口先检查正文权限；问答和建议问题读取已存储上下文，不隐式抓取。深层 AI/翻译/研究服务收口由 T14 继续。

## 实测证据

环境：独立 worktree `/tmp/newshub-rss-T11`；Python 3.12.14；只读使用协调环境 `/tmp/newshub-rss-coordinator-venv`。所有数据库验证使用临时合成数据库，未连接用户或生产数据库。

```bash
RUN_MAIN=true DJANGO_DB_PATH=/tmp/newshub-t11-test.sqlite3 PYTHONPATH=backend:crawler \
  /tmp/newshub-rss-coordinator-venv/bin/python -m pytest \
  backend/api/tests/rss/test_access_contract.py \
  backend/api/tests/test_favorites.py backend/api/tests/test_news_summary.py -q
```

退出码 0：**72 passed in 14.99s**。T11 专项 20、收藏回归 21、摘要/查询预算回归 31。

最后的来源显示名/动态 reading_policy 和稳定来源排序调整后，重跑以下针对性回归：

```bash
RUN_MAIN=true DJANGO_DB_PATH=/tmp/newshub-t11-test.sqlite3 PYTHONPATH=backend:crawler \
  /tmp/newshub-rss-coordinator-venv/bin/python -m pytest \
  backend/api/tests/rss/test_access_contract.py::test_http_id_list_favorites_counts_and_dynamic_revocation \
  backend/api/tests/rss/test_access_contract.py::test_catalog_dashboard_reading_stats_and_subscribe_cannot_grant_private_source \
  backend/api/tests/test_news_summary.py::test_payload_detail_and_constant_queries -q
```

退出码 0：**3 passed in 4.03s**。

| 验收 | 实际覆盖 |
| --- | --- |
| T11-A1 | A/B/匿名 ID、列表、semantic/hybrid/keyword 候选、收藏、分类/来源计数、目录/阅读统计；未知 publication 和 inactive 用户拒绝；向量提供者使用 stub，未运行真实向量引擎 |
| T11-A2 | 同 URL 不同 personal 频道、legacy 身份关联、Miniflux 原始来源与绑定/账号不匹配均不提升正文权限 |
| T11-A3 | 退订、政策收紧、缓存命中之前拒绝；高权限 body_access 也不能绕过动态政策 |
| T11-A4 | legacy/complete/available、public/personal paused 历史、空白/summary 正文、SQL 与读取结果一致；暂停来源可读缓存但不能 force fetch |

列表 1 条与 20 条均固定 5 次查询，semantic 为 5、hybrid 为 6；新增两次页内批量 ACL 读取，无逐文章权限查询。来源计数使用相关 SQL 聚合。20 条合成摘要响应 47,119 字节，预算随 4 个固定 C04 字段调整至 50 KB；完整正文/译文/provenance 保持 deferred。既有测试 fixture 显式提供 public publication 与 legacy owner，未引入自动公开默认。

`git diff --check` 通过。使用独立 `/tmp/newshub-t11-check.sqlite3` 执行 `RUN_MAIN=true PYTHONPATH=backend:crawler .../python backend/manage.py check` 退出码 0；仅 staticfiles.W004：当前 worktree 未构建 frontend/dist/assets。

## 集成边界、风险与未验证

- 高风险权限改动仍需非作者独立复核；不以本报告替代主调度 T26/T27 组合验收或 CI。未运行无关全仓测试、真实发布者网络、浏览器、生产部署或迁移恢复。
- `SourceFeedLink.association_policy` 当前接受合同 V1 all-entry 的精确结构；未知过滤策略拒绝。T09 的已审批元数据过滤需集成同一关联判断，不能绕过授权。
- T25 独占 `full_content_status.py`；已向其发送 `_rss_access_user` 经 `body_authorized_news` 判断的读取补丁。本分支没有并发修改该文件。T14 继续深层服务中的翻译内容哈希/缓存、流式重授权、研究工具与 TTS 统一 StoredArticle 使用。
- 主调度在本分支释放后补 `can_rss_refetch` 与 Miniflux 专用修复条件，以及旧 ChannelSubscriptionsView 的 RSS unsubscribe/subscribe 服务委托；本分支仅关闭猜测个人来源 ID 的授权旁路。
- 本任务不改 models、迁移、frontend、api.urls 或 EXECUTION-STATUS。不包含生产批准或执行。回退使用任务提交的普通 revert，并保留数据；未执行回退或数据库逆迁移。
