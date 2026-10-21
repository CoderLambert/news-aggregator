# RSSD-02.3：后台目录维护与回退版本保护

> 审阅：待审阅；实施：未开始；自动/人工验收：NOT_RUN。本文中的新增文件、接口、测试和命令是未来开发要求，本轮不执行。

## 目标与交付物

**目标：** 目录变化自动进入搜索，同时不干扰采集、不被旧种子或迟到构建覆盖。

**交付物：** 同进程单一在途维护、输入变化检查、退避、heartbeat保护和固定回退行为。

## 范围与前置依赖

**范围：** runtime目录维护入口、启动/每日种子路径、构建结果收割和失败隔离。

**不包含：** 不新建常驻进程/调度平台，不改Miniflux身份、不重试未知Feed创建。

**前置依赖：** [RSSD-02.2](RSSD-02.2-公开频道入目录与即时撤回.md)的已验收输出。

**必须引用的合同：** [开发合同](../../开发合同.md) C02、C03、C07、C08；[完整方案](../../完整方案.md)相应产品/A编号。无需重读其他任务正文；接口以共同合同为准。

## 具体文件与输入输出

- 新增：backend/api/rss/directory_maintenance.py、backend/api/tests/rss/test_directory_maintenance.py
- 修改：backend/api/rss/runtime.py；必要时只调整directory.py种子包装
- 扩展：scripts/deploy/tests/test_rss_runtime.py；必须先读部署/CI/测试规则

**输入：** monotonic now、当前head/固定状态、最新本地资料及种子/编辑输入版本。

**输出：** maintain_directory(now=...)返回maintenance状态；经publish_directory激活，不直接改active。

## 实现方案与开发步骤

**方案：** 30秒检查输入，单future编译、tick不等待；30/60/120/300秒失败退避。收割时校验最新版本和revision，无变化不发布，过期结果丢弃。修正无条件seed-v1重新激活；固定回退保持到显式解除。

- [ ] 1. 确认依赖输出、当前base/head与文件所有权；按C07准备无真实.env的隔离环境，读取适用AGENTS。
- [ ] 2. 先添加下表指定负例/契约断言；运行下列自动命令，保存原行为FAIL。环境/导入错误只记BLOCKED，不作为功能负例。
- [ ] 3. 按本卡文件、输入输出和方案实现最小改动；共同接口变化先同步开发合同及消费者。
- [ ] 4. 同命令运行至目标断言PASS，再做本卡列出的受影响回归；不扩大到无关全量测试。
- [ ] 5. 完成人工验收并记录实际版本/结果；缺前提记未测。更新总览对应项及C08证据，提交仅在另获授权后进行。

## 自动测试与通过条件

| 指定用例/检查 | 必须成立的断言 |
|---|---|
| `test_startup_and_daily_check_keep_active_v2` | 模拟满足导入阈值的启动及86400秒后检查，活动v2不倒退。 |
| `test_catalog_failure_does_not_stop_sync` | 构建抛异常或长时间未完成，control/sync tick和heartbeat仍前进。 |
| `test_single_inflight_and_stale_build_discarded` | 连续变更不并发构建，旧head结果不能覆盖新发布。 |
| `test_pinned_rollback_survives_maintenance` | rollback固定后跨tick/重启/每日检查保持checksum，解除固定后才接受新输入。 |

关键断言示意（变量由该用例的隔离fixture提供，不能直接当现成测试执行）：

```python
assert active_checksum_after_daily_check == v2_checksum
assert sync_ticks_after > sync_ticks_before
assert max_inflight_builds == 1
```

在C07环境执行：

```bash
PYTHONPATH=backend:crawler RUN_MAIN=true python -m pytest -q backend/api/tests/rss/test_directory_maintenance.py scripts/deploy/tests/test_rss_runtime.py
```

**预期：** 新增代码的目标断言先见原行为失败，实施后退出码0且断言全部通过；真实核验/基线/运营场景按本卡前提记录实际结果，不人为制造失败或把未运行记PASS。

**受影响回归与限制：** 使用假时钟/受控future验证调度，不在单元测试真实等待一天；保留原runtime重导入/角色/heartbeat/重依赖边界。

## 人工验收步骤

1. 在隔离runtime发布v2，模拟启动及每日检查，inspect版本不变。
2. 更改合成公共资料，正常条件下60秒目标内可搜索；注入构建失败后旧目录可读、采集心跳持续。
3. 固定回退版本并跨维护检查，再解除固定；核对每次激活日志的head/revision及输入版本。

每步记录PASS/FAIL/未测及候选版本；合成/隔离结果不代表生产验收。

## 完成标准与回退方式

**完成标准：** A09/A21/A22成立；迟到、失败、单一在途和固定回退均可验证；60秒是正常条件目标，故障积压单独记录。

**回退：** 停用新维护入口并固定旧快照；不恢复无条件v1覆盖逻辑，不停用户采集服务或清理共享资源。

**交接：** 依C08给出变更文件、接口实际映射、base/head、命令/退出码、证据位置、未测和风险；不得只交“代码已写”。返回[任务总览](../../任务执行计划.md)。
