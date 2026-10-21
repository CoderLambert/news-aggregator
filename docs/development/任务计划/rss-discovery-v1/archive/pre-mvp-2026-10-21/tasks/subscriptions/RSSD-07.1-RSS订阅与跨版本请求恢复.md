# RSSD-07.1：RSS订阅与跨版本请求恢复

> 审阅：待审阅；实施：未开始；自动/人工验收：NOT_RUN。本文中的新增文件、接口、测试和命令是未来开发要求，本轮不执行。

## 目标与交付物

**目标：** 确认的RSS选择可靠进入现有持久任务，响应丢失/目录换版也不重复注册或换目标。

**交付物：** 目录版本校验、三类旧选择兼容、不可变意图重放、任务恢复/取消与前端真实接线。

## 范围与前置依赖

**范围：** 已有RSS subscribe/_selection/结果读取的最小修订、Idempotency-Key语义、05 DTO的RSS分支。

**不包含：** 不建第二个任务队列，不强制公开个人来源，不对unknown盲重发create，不改公共订阅分支。

**前置依赖：** [RSSD-06.2](../discovery/RSSD-06.2-频道详情与明确的订阅确认.md)的已验收输出。

**必须引用的合同：** [开发合同](../../开发合同.md) C01、C02、C05、C06、C07、C08；[完整方案](../../完整方案.md)相应产品/A编号。无需重读其他任务正文；接口以共同合同为准。

## 具体文件与输入输出

- 修改：backend/api/rss/{subscriptions.py,subscription_views.py}；必要时FeedOperation持久凭据字段使用现有safe_input/request_hash
- 修改：frontend/src/features/rss/discovery/SubscriptionAction.tsx、frontend/src/features/rss/queryRefresh.ts
- 新增：backend/api/tests/rss/test_discovery_subscription_contract.py、frontend/tests/features/rss/SubscriptionAction.test.tsx
- 复用：backend/api/rss/{operations.py,discovery.py,additions.py,control_worker.py}及既有test_subscriptions.py/test_operations.py

**输入：** 一种选择+目录版本（可选）+group_ids/category_id、当前viewer及同一意图幂等键。

**输出：** 原RSS 201/202/重放200及actor-scoped operation；06.2的RSS SubscriptionOutcome、刷新后的频道/添加记录。

## 实现方案与开发步骤

**方案：** 先辨认当前用户已受理的持久键与不可变请求，重放安全结果而非重新解析旧目录；新请求再校验活动选择、权限/策略/引擎，按原服务建立意图。同键不同选择/分组/分类409，变更意图换键；终态用既有refreshRssViews扩展刷新，不把succeeded等同已有文章。

- [ ] 1. 确认依赖输出、当前base/head与文件所有权；按C07准备无真实.env的隔离环境，读取适用AGENTS。
- [ ] 2. 先添加下表指定负例/契约断言；运行下列自动命令，保存原行为FAIL。环境/导入错误只记BLOCKED，不作为功能负例。
- [ ] 3. 按本卡文件、输入输出和方案实现最小改动；共同接口变化先同步开发合同及消费者。
- [ ] 4. 同命令运行至目标断言PASS，再做本卡列出的受影响回归；不扩大到无关全量测试。
- [ ] 5. 完成人工验收并记录实际版本/结果；缺前提记未测。更新总览对应项及C08证据，提交仅在另获授权后进行。

## 自动测试与通过条件

| 指定用例/检查 | 必须成立的断言 |
|---|---|
| `test_lost_response_replay_after_snapshot_switch_returns_original_intent` | POST已受理响应丢失，切目录/移除旧ID后同键重试恢复原operation且register数不增。 |
| `test_new_stale_selection_and_changed_payload_rejected` | 新键旧版本409，同键不同payload409，ID不可转到新URL。 |
| `test_two_users_share_feed_but_not_private_state` | 仅一个物理binding，分组/已读/收藏/标题权限隔离。 |
| `test_unknown_cancel_and_refresh_recovery` | unknown先对账，取消自己的意图不删他人Feed；关闭/刷新后添加记录继续可查。 |

关键断言示意（变量由该用例的隔离fixture提供，不能直接当现成测试执行）：

```python
assert replay['operation_id'] == original['operation_id']
assert register_count_after == register_count_before
assert changed_payload_response.status_code == 409
```

在C07环境执行：

```bash
PYTHONPATH=backend:crawler RUN_MAIN=true python -m pytest -q backend/api/tests/rss/test_discovery_subscription_contract.py backend/api/tests/rss/test_subscriptions.py backend/api/tests/rss/test_operations.py
npm --prefix frontend run test:run -- tests/features/rss/SubscriptionAction.test.tsx tests/features/rss/DiscoverDialog.test.tsx
```

**预期：** 新增代码的目标断言先见原行为失败，实施后退出码0且断言全部通过；真实核验/基线/运营场景按本卡前提记录实际结果，不人为制造失败或把未运行记PASS。

**受影响回归与限制：** CSRF/read_only/owner错误继续拒绝；candidate_token当前actor且15分钟有效；网关/引擎版本变化重新校验。

## 人工验收步骤

1. 选择目录Feed确认分类/分组提交，看到已保存请求，再分别检查关系建立、引擎连接、首次文章三个阶段。
2. 用隔离代理丢弃一次响应，换目录后以原键重试，核对同一个operation和一个物理Feed。
3. 双账号同Feed后取消其中一个意图，检查另一个仍可使用；刷新/关闭后在添加记录继续核对。

每步记录PASS/FAIL/未测及候选版本；合成/隔离结果不代表生产验收。

## 完成标准与回退方式

**完成标准：** A11/A12/A14/A15/A17/A18的RSS路径通过；真实远端资源计数在08补证，离线不冒充真引擎。

**回退：** 关闭新目录选择/版本路径，保留已受理operation审计、围栏和所有用户关系；不把unknown改pending。

**交接：** 依C08给出变更文件、接口实际映射、base/head、命令/退出码、证据位置、未测和风险；不得只交“代码已写”。返回[任务总览](../../任务执行计划.md)。
