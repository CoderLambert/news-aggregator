# RSSD-02.1：稳定频道身份与原子快照发布

> 审阅：待审阅；实施：未开始；自动/人工验收：NOT_RUN。本文中的新增文件、接口、测试和命令是未来开发要求，本轮不执行。

## 目标与交付物

**目标：** 新目录可以原子发布/回退，既有ID永远不转向另一目标。

**交付物：** v1/v2兼容导入、历史身份约束、单一激活服务和inspect/preview/publish/rollback/unpin管理命令。

## 范围与前置依赖

**范围：** 目录模型、增量迁移、checksum+revision CAS、固定回退与schema注册；为后续公共来源/核验证据预留合同中的模型。

**不包含：** 不做公共资料构建、runtime调度、Feed注册或数据清空。

**前置依赖：** [RSSD-01](RSSD-01-接入已选定的TidingsTop200清单.md)的已验收输出。

**必须引用的合同：** [开发合同](../../开发合同.md) C01、C02、C07、C08；[完整方案](../../完整方案.md)相应产品/A编号。无需重读其他任务正文；接口以共同合同为准。

## 具体文件与输入输出

- 修改：backend/api/rss/{directory_models.py,directory.py}、backend/api/models.py模型注册/重导出
- 新增：backend/api/rss/directory_publish.py、backend/api/management/commands/rss_directory.py、当前graph上的增量迁移
- 新增：backend/api/tests/rss/test_directory_snapshot_v2.py；复用test_directory.py

**输入：** DirectoryCandidate及directory_head()的checksum/revision；历史快照身份凭证。

**输出：** C02三个发布函数及五个管理子命令；唯一active、单调revision和固定版本状态。

## 实现方案与开发步骤

**方案：** 按C02创建Origin/Evidence/State及增量字段；事务外验证全部字节与身份，短写事务内重查head和输入后切active。v1旧签名包装到同一服务，不另留旁路。

- [ ] 1. 确认依赖输出、当前base/head与文件所有权；按C07准备无真实.env的隔离环境，读取适用AGENTS。
- [ ] 2. 先添加下表指定负例/契约断言；运行下列自动命令，保存原行为FAIL。环境/导入错误只记BLOCKED，不作为功能负例。
- [ ] 3. 按本卡文件、输入输出和方案实现最小改动；共同接口变化先同步开发合同及消费者。
- [ ] 4. 同命令运行至目标断言PASS，再做本卡列出的受影响回归；不扩大到无关全量测试。
- [ ] 5. 完成人工验收并记录实际版本/结果；缺前提记未测。更新总览对应项及C08证据，提交仅在另获授权后进行。

## 自动测试与通过条件

| 指定用例/检查 | 必须成立的断言 |
|---|---|
| `test_same_legacy_key_changed_target_rejected` | 同来源/key把URL从A改B不能复用旧ID，旧目标及用户数据不变。 |
| `test_failed_publish_keeps_active_snapshot` | 坏checksum/空/超限/DB异常后旧active及entries完整。 |
| `test_old_build_and_aba_cannot_activate` | head A→B→A后revision已变，迟到expected_head仍拒绝。 |
| `test_rollback_pins_without_deleting_user_state` | 回退只切元数据并固定，用户关系/文章/收藏数量和身份不变。 |

关键断言示意（变量由该用例的隔离fixture提供，不能直接当现成测试执行）：

```python
assert active.checksum == old_checksum
assert new_head['revision'] > old_head['revision']
assert before_user_state == after_user_state
```

在C07环境执行：

```bash
PYTHONPATH=backend:crawler RUN_MAIN=true python -m pytest -q backend/api/tests/rss/test_directory_snapshot_v2.py backend/api/tests/rss/test_directory.py
```

**预期：** 新增代码的目标断言先见原行为失败，实施后退出码0且断言全部通过；真实核验/基线/运营场景按本卡前提记录实际结果，不人为制造失败或把未运行记PASS。

**受影响回归与限制：** 迁移在新临时DB执行，另从合成v1有数据状态前向迁移；验证旧调用与旧字段，不在用户DB做迁移实验。

## 人工验收步骤

1. 在隔离DB用rss_directory preview检查产物，确认未切active。
2. 发布候选后inspect，再用旧expected_head发布另一候选，确认冲突且active不变。
3. rollback到保留checksum并inspect固定状态，对比用户数据；再显式unpin确认不删除任何对象。

每步记录PASS/FAIL/未测及候选版本；合成/隔离结果不代表生产验收。

## 完成标准与回退方式

**完成标准：** A08/A17/A21/A22快照部分通过；迁移兼容、身份冲突、CAS/ABA和回退都有证据。后续共享schema由本任务所有者接收变更。

**回退：** 关闭新选择入口并固定旧快照；保留前向schema和身份历史，不降迁移、不删已建关系。

**交接：** 依C08给出变更文件、接口实际映射、base/head、命令/退出码、证据位置、未测和风险；不得只交“代码已写”。返回[任务总览](../../任务执行计划.md)。
