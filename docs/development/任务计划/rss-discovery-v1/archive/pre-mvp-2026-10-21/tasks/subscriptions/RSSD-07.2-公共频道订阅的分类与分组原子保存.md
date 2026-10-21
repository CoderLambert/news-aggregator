# RSSD-07.2：公共频道订阅的分类与分组原子保存

> 审阅：待审阅；实施：未开始；自动/人工验收：NOT_RUN。本文中的新增文件、接口、测试和命令是未来开发要求，本轮不执行。

## 目标与交付物

**目标：** 订阅已发布公共频道时，一次确认原子保存自己的新关系/分类/分组，保持原接口兼容。

**交付物：** 单source可选字段支持、事务内公共资格/归属复查、重复不覆盖及public前端接线。

## 范围与前置依赖

**范围：** ChannelSubscriptionsView subscribe分支与新确认面板的public分支；消费07.1已交接的共享UI。

**不包含：** 不伪造operation_id、不重做公共审核、不改正文权限、不覆盖已有个人设置。

**前置依赖：** [RSSD-07.1](RSSD-07.1-RSS订阅与跨版本请求恢复.md)的已验收输出。

**必须引用的合同：** [开发合同](../../开发合同.md) C05、C06、C07、C08；[完整方案](../../完整方案.md)相应产品/A编号。无需重读其他任务正文；接口以共同合同为准。

## 具体文件与输入输出

- 修改：backend/api/channel_views.py的ChannelSubscriptionsView.post、frontend/src/features/rss/discovery/SubscriptionAction.tsx
- 新增：backend/api/tests/rss/test_public_discovery_subscription.py；扩展frontend/tests/features/rss/SubscriptionAction.test.tsx
- 复用：backend/api/services/channel_catalog.py、backend/api/rss/access.py、现有set_groups/set_category及queryRefresh.ts

**输入：** {action:'subscribe',source_ids:[id],group_ids?:number[],category_id?:number|null}，当前用户。

**输出：** 既有订阅列表中的当前关系；前端构造public SubscriptionOutcome，不请求rss-operation。

## 实现方案与开发步骤

**方案：** 保留原user写锁和短事务，读取前校验单source增量字段；复用当前公共资格及私有分组归属，原子get_or_create及新关系设置。已存在关系只返回当前值，后续显式修改用原版本接口。省略新字段时旧批量调用不改变。

- [ ] 1. 确认依赖输出、当前base/head与文件所有权；按C07准备无真实.env的隔离环境，读取适用AGENTS。
- [ ] 2. 先添加下表指定负例/契约断言；运行下列自动命令，保存原行为FAIL。环境/导入错误只记BLOCKED，不作为功能负例。
- [ ] 3. 按本卡文件、输入输出和方案实现最小改动；共同接口变化先同步开发合同及消费者。
- [ ] 4. 同命令运行至目标断言PASS，再做本卡列出的受影响回归；不扩大到无关全量测试。
- [ ] 5. 完成人工验收并记录实际版本/结果；缺前提记未测。更新总览对应项及C08证据，提交仅在另获授权后进行。

## 自动测试与通过条件

| 指定用例/检查 | 必须成立的断言 |
|---|---|
| `test_group_category_and_relation_commit_together` | 新公共关系与所选分类/两个组同时可见，越权组时全部回滚。 |
| `test_duplicate_subscribe_preserves_existing_preferences` | 双击/重放不覆盖原分类/组，不产生第二关系。 |
| `test_public_eligibility_rechecked_in_transaction` | 请求间撤回/暂停/换引擎拒绝新关系，不能只信前端action。 |
| `test_legacy_response_and_public_ui_no_polling` | 省略字段的旧调用保持列表响应；public界面不请求operation。 |

关键断言示意（变量由该用例的隔离fixture提供，不能直接当现成测试执行）：

```python
assert subscription.category_id == requested_category_id
assert set(subscription.groups.values_list('pk', flat=True)) == requested_group_ids
assert not ChannelSubscription.objects.filter(user=outsider, source=source).exists()
```

在C07环境执行：

```bash
PYTHONPATH=backend:crawler RUN_MAIN=true python -m pytest -q backend/api/tests/rss/test_public_discovery_subscription.py backend/api/tests/rss/test_unified_channels.py
npm --prefix frontend run test:run -- tests/features/rss/SubscriptionAction.test.tsx tests/pages/ChannelWorkspace.test.jsx
```

**预期：** 新增代码的目标断言先见原行为失败，实施后退出码0且断言全部通过；真实核验/基线/运营场景按本卡前提记录实际结果，不人为制造失败或把未运行记PASS。

**受影响回归与限制：** 验证旧批量subscribe、set_groups/set_category和取消订阅行为；能力/read_only/CSRF保持，更新查询只影响当前viewer。

## 人工验收步骤

1. 在公开频道卡选择个人分类及两个组，提交后在我的频道一次看到完整设置，无连接轮询。
2. 重发订阅确认并提供不同默认设置，检查既有用户选择保持；显式修改再走原设置接口。
3. 在隔离请求中使用另一账号组ID或先撤回公开来源，确认整笔拒绝、没有半成品关系。

每步记录PASS/FAIL/未测及候选版本；合成/隔离结果不代表生产验收。

## 完成标准与回退方式

**完成标准：** A11/A13/A14/A16/A18公共路径通过；旧客户端响应、原子性、重复行为和无operation轮询均有证据。

**回退：** 关闭新可选字段的UI入口并保留旧subscribe；已建立个人关系/分类/分组不删除，安全事务校验保留。

**交接：** 依C08给出变更文件、接口实际映射、base/head、命令/退出码、证据位置、未测和风险；不得只交“代码已写”。返回[任务总览](../../任务执行计划.md)。
