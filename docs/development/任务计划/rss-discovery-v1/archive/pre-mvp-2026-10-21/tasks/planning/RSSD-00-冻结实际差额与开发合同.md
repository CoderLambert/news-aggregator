# RSSD-00：冻结实际差额与开发合同

> 审阅：待审阅；实施：未开始；自动/人工验收：NOT_RUN。本文中的新增文件、接口、测试和命令是未来开发要求，本轮不执行。

## 目标与交付物

**目标：** 把v1.2方案变成当前候选可以执行、可以逐项拒绝或通过的明确合同。

**交付物：** 源码差额表、50条固定搜索标注、同条件性能基线及冻结后的接口/任务依赖。

## 范围与前置依赖

**范围：** 核对现有目录/订阅/能力/前端消费者，冻结分类key、接口、身份、错误码与测量口径。

**不包含：** 不实现搜索/界面，不发布目录，不运行真实Feed或生产迁移。

**前置依赖：** 无。

**必须引用的合同：** [开发合同](../../开发合同.md) C01、C05、C06、C07、C08；[完整方案](../../完整方案.md)相应产品/A编号。无需重读其他任务正文；接口以共同合同为准。

## 具体文件与输入输出

- 读取：backend/api/rss/{directory.py,directory_http.py,subscriptions.py,runtime.py}、backend/api/channel_views.py
- 读取：backend/api/capabilities_views.py、frontend/src/services/{api.ts,workspaceApi.ts}、frontend/src/features/rss/DiscoverDialog.tsx
- 新增：backend/api/tests/rss/fixtures/directory_search_golden.json、backend/api/tests/rss/test_directory_golden_contract.py
- 更新：本目录开发合同.md、任务执行计划.md；运行后才新增evidence/<candidate-sha>/baseline.json

**输入：** 完整方案A01～A23、当前main/HEAD、实际源码、用户已选[Top200 OPML](../catalog/tidings-top200.opml)及已有历史身份；seed-v1仅用于现有行为基线/兼容对照。

**输出：** golden含20条entity、30条topic/alias，每条query/filters/relevant_ids/negative_ids；固定种子checksum和标注理由，不按算法结果挑选样例。

## 实现方案与开发步骤

**方案：** 只为已选Top200建立固定查询与相关身份标注，按C01复用历史代表或计算新ID，不为测试重新选频道；基线读取现有本地API并保存SQL/响应字节/耗时，不引入测试服务或新CI。

- [ ] 1. 确认依赖输出、当前base/head与文件所有权；按C07准备无真实.env的隔离环境，读取适用AGENTS。
- [ ] 2. 先添加下表指定负例/契约断言；运行下列自动命令，保存原行为FAIL。环境/导入错误只记BLOCKED，不作为功能负例。
- [ ] 3. 按本卡文件、输入输出和方案实现最小改动；共同接口变化先同步开发合同及消费者。
- [ ] 4. 同命令运行至目标断言PASS，再做本卡列出的受影响回归；不扩大到无关全量测试。
- [ ] 5. 完成人工验收并记录实际版本/结果；缺前提记未测。更新总览对应项及C08证据，提交仅在另获授权后进行。

## 自动测试与通过条件

| 指定用例/检查 | 必须成立的断言 |
|---|---|
| `test_golden_has_fixed_query_classes` | entity恰20条、topic/alias恰30条，中文英文均覆盖且每条有非空相关ID。 |
| `test_golden_has_no_conflicting_labels` | 同条relevant_ids与negative_ids不相交，所有标注ID可追溯到锁定身份；fixture不放docs。 |

关键断言示意（变量由该用例的隔离fixture提供，不能直接当现成测试执行）：

```python
assert len(entity_cases) == 20 and len(topic_cases) == 30
assert set(case['relevant_ids']).isdisjoint(case['negative_ids'])
```

在C07环境执行：

```bash
PYTHONPATH=backend:crawler RUN_MAIN=true python -m pytest -q backend/api/tests/rss/test_directory_golden_contract.py
```

**预期：** 新增代码的目标断言先见原行为失败，实施后退出码0且断言全部通过；真实核验/基线/运营场景按本卡前提记录实际结果，不人为制造失败或把未运行记PASS。

**受影响回归与限制：** 本任务不改变产品行为；检查所有任务卡的签名、分类key及共同合同一致，基线只记录实测而不宣称变快。

## 人工验收步骤

1. 逐项从A01～A23找到总览中的责任任务，不得遗漏。
2. 抽查一条中文实体、一条英文别名与一条负例，确认标注有资料来源且不是未来排名的反推结果。
3. 确认基线写明环境、样本、候选SHA和目录hash；未能安全运行的项标NOT_RUN。

每步记录PASS/FAIL/未测及候选版本；合成/隔离结果不代表生产验收。

## 完成标准与回退方式

**完成标准：** 50条搜索标注与共同合同可审阅；实际差额逐项标复用/增量/排除；A01～A23均有责任任务。基线缺失会阻止后续性能比较，不伪造PASS。

**回退：** 撤销本任务新增的fixture/文档改动；仅清理本任务合成基线环境，保留用户工作区和运行DB。

**交接：** 依C08给出变更文件、接口实际映射、base/head、命令/退出码、证据位置、未测和风险；不得只交“代码已写”。返回[任务总览](../../任务执行计划.md)。
