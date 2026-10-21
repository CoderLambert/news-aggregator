# RSSD-06.2：频道详情与明确的订阅确认

> 审阅：待审阅；实施：未开始；自动/人工验收：NOT_RUN。本文中的新增文件、接口、测试和命令是未来开发要求，本轮不执行。

## 目标与交付物

**目标：** 用户看懂频道来源/健康/授权预览后，明确选择个人分类和私人分组再提交。

**交付物：** 资料详情、三条以内授权标题、两种订阅动作确认、匿名登录返回与安全选中恢复。

## 范围与前置依赖

**范围：** 详情加载/失效、Feed/网站/RSSHub输入分流、分类/分组确认及SubscriptionOutcome展示接线。

**不包含：** 不改07持久化服务、不新增模板通用参数表单、不抓正文/远程图标、不将token持久化。

**前置依赖：** [RSSD-06.1](RSSD-06.1-共享发现浏览与关键词搜索界面.md)的已验收输出。

**必须引用的合同：** [开发合同](../../开发合同.md) C05、C06、C07、C08；[完整方案](../../完整方案.md)相应产品/A编号。无需重读其他任务正文；接口以共同合同为准。

## 具体文件与输入输出

- 新增：frontend/src/features/rss/discovery/FeedDetails.tsx、SubscriptionAction.tsx、frontend/tests/features/rss/FeedDetails.test.tsx
- 修改：共享DiscoverPanel及现有DiscoverDialog接线，复用已有个人分类/分组查询
- 复用：frontend/src/services/rssDiscoveryApi.ts、workspaceApi.ts、现有RSS发现/操作接口

**输入：** 选中DirectoryEntry/action、当前viewer、自己的group_ids/category_id、已有网站发现候选。

**输出：** 冻结的用户确认意图；RSS与public两种SubscriptionOutcome的展示容器，实际写入闭环由07.1/07.2交付。

## 实现方案与开发步骤

**方案：** 详情独立query含viewer+ID，过期404清选择并重查；Feed URL只显示受审地址。确认保留个人分类/分组，不从目录主题代填；匿名先登录再重查。网站无候选保留显式直接Feed确认，candidate过期重发现。

- [ ] 1. 确认依赖输出、当前base/head与文件所有权；按C07准备无真实.env的隔离环境，读取适用AGENTS。
- [ ] 2. 先添加下表指定负例/契约断言；运行下列自动命令，保存原行为FAIL。环境/导入错误只记BLOCKED，不作为功能负例。
- [ ] 3. 按本卡文件、输入输出和方案实现最小改动；共同接口变化先同步开发合同及消费者。
- [ ] 4. 同命令运行至目标断言PASS，再做本卡列出的受影响回归；不扩大到无关全量测试。
- [ ] 5. 完成人工验收并记录实际版本/结果；缺前提记未测。更新总览对应项及C08证据，提交仅在另获授权后进行。

## 自动测试与通过条件

| 指定用例/检查 | 必须成立的断言 |
|---|---|
| `test_details_show_unknown_and_only_authorized_titles` | 无证据/无文章如实显示，标题最多3，HTML当文本、无任意图标请求。 |
| `test_confirmation_does_not_replace_personal_category` | 目录category_keys不写category_id，多选自己的分组原样进入意图。 |
| `test_login_and_stale_selection_are_rechecked` | 登录/换号后重新加载，旧404与过期token不能继续提交。 |
| `test_distinct_outcomes_do_not_invent_operation` | RSS显示连接中/首次同步，public关系成功不轮询operation。 |

关键断言示意（变量由该用例的隔离fixture提供，不能直接当现成测试执行）：

```typescript
expect(previewTitles.length).toBeLessThanOrEqual(3)
expect(confirmedIntent.group_ids).toEqual(selectedOwnGroupIds)
expect(publicOutcome).not.toHaveProperty('operation_id')
```

在C07环境执行：

```bash
npm --prefix frontend run test:run -- tests/features/rss/FeedDetails.test.tsx tests/features/rss/DiscoverDialog.test.tsx
npm --prefix frontend run typecheck
npm --prefix frontend run lint
```

**预期：** 新增代码的目标断言先见原行为失败，实施后退出码0且断言全部通过；真实核验/基线/运营场景按本卡前提记录实际结果，不人为制造失败或把未运行记PASS。

**受影响回归与限制：** 订阅写接口在07前用冻结合同测试替身；不能将替身成功记成真实订阅/文章可读。

## 人工验收步骤

1. 打开有/无预览、有/无核验的详情，核对来源许可、健康时间/环境与未知文案。
2. 选择个人分类及两个分组，确认目录主题没有覆盖；匿名登录返回后选择须重查。
3. 在隔离夹具使选中ID下线、token过期或网站返回多个/零候选，确认提示及重新选择路径可用。

每步记录PASS/FAIL/未测及候选版本；合成/隔离结果不代表生产验收。

## 完成标准与回退方式

**完成标准：** A10/A13/A14/A17/A18的详情/确认部分通过；选中目标与确认字段清晰可审，实际写入仍待07。

**回退：** 关闭详情入口回到浏览/旧添加；保留已经受理任务，不清私人分类/分组。

**交接：** 依C08给出变更文件、接口实际映射、base/head、命令/退出码、证据位置、未测和风险；不得只交“代码已写”。返回[任务总览](../../任务执行计划.md)。
