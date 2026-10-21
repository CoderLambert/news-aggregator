# RSSD-04：编辑精选与可信健康状态

> 审阅：待审阅；实施：未开始；自动/人工验收：NOT_RUN。本文中的新增文件、接口、测试和命令是未来开发要求，本轮不执行。

## 目标与交付物

**目标：** 打开即有可解释推荐，核验状态真实，过期不让推荐集合突然消失。

**交付物：** 精选配置、独立证据记录/读取、分类配额、首屏12条及过期降级。

## 范围与前置依赖

**范围：** 编辑顺序和健康的独立模型、证据来源/环境/策略失效、私人证据隔离。

**不包含：** 不调用AI、不按私有订阅人数推荐、不自动外网复核；真实24源核验由08执行。

**前置依赖：** [RSSD-03](RSSD-03-中英文频道搜索与稳定分页.md)的已验收输出。

**必须引用的合同：** [开发合同](../../开发合同.md) C03、C04、C07、C08；[完整方案](../../完整方案.md)相应产品/A编号。无需重读其他任务正文；接口以共同合同为准。

## 具体文件与输入输出

- 新增：backend/api/rss/{directory_featured.py,directory_evidence.py}、directory_data/featured-v1.json
- 接入：backend/api/rss/directory_search.py的featured分派，03完成后单写者交接
- 新增：backend/api/tests/rss/test_directory_featured_v1.py；schema复用02.1，不另开并行迁移

**输入：** 受审精选ID/主分类/weight/reason、可信证据与当前身份/环境/策略上下文。

**输出：** C04 select_featured/record_directory_evidence/read_directory_health；同一个分页合同。

## 实现方案与开发步骤

**方案：** 24个不同Feed按六主分类配额、编辑weight与稳定ID排列，首屏至多12；证据最新有效记录决定unknown/ok/error/stale。超过7天仅降级标签；读取时排除撤回/私人证据。

- [ ] 1. 确认依赖输出、当前base/head与文件所有权；按C07准备无真实.env的隔离环境，读取适用AGENTS。
- [ ] 2. 先添加下表指定负例/契约断言；运行下列自动命令，保存原行为FAIL。环境/导入错误只记BLOCKED，不作为功能负例。
- [ ] 3. 按本卡文件、输入输出和方案实现最小改动；共同接口变化先同步开发合同及消费者。
- [ ] 4. 同命令运行至目标断言PASS，再做本卡列出的受影响回归；不扩大到无关全量测试。
- [ ] 5. 完成人工验收并记录实际版本/结果；缺前提记未测。更新总览对应项及C08证据，提交仅在另获授权后进行。

## 自动测试与通过条件

| 指定用例/检查 | 必须成立的断言 |
|---|---|
| `test_featured_has_unique_feeds_and_category_quotas` | ≥24不同Feed，六主分类各≥4；同源多标签不重复计数。 |
| `test_seed_timestamp_cannot_grant_verified` | 种子与上游validated_at不能生成本地成功记录。 |
| `test_stale_health_keeps_editorial_membership_and_order` | 假时钟跨7天后status=stale，ID集合与编辑顺序不变。 |
| `test_private_or_changed_context_evidence_is_hidden` | 私人证据、撤回资料、URL/引擎/策略/环境变化不继续显示为当前ok；低频不判故障。 |

关键断言示意（变量由该用例的隔离fixture提供，不能直接当现成测试执行）：

```python
assert health_after_seven_days['status'] == 'stale'
assert featured_ids_before == featured_ids_after
assert len(set(featured_ids)) >= 24
```

在C07环境执行：

```bash
PYTHONPATH=backend:crawler RUN_MAIN=true python -m pytest -q backend/api/tests/rss/test_directory_featured_v1.py
```

**预期：** 新增代码的目标断言先见原行为失败，实施后退出码0且断言全部通过；真实核验/基线/运营场景按本卡前提记录实际结果，不人为制造失败或把未运行记PASS。

**受影响回归与限制：** 同URL独立外部来源不继承撤回公共来源的健康；分页只因目录/条件变化重置，不因证据自然过期重排。

## 人工验收步骤

1. 请求mode=featured，核对推荐理由、六主分类与首屏数量。
2. 推进隔离测试时钟跨7天，观察仍可浏览精选、标签变为过期而非近期成功。
3. 移除所有可信证据及编辑配置分别测试：前者unknown推荐，后者真实空态；不得显示假文章或热度。

每步记录PASS/FAIL/未测及候选版本；合成/隔离结果不代表生产验收。

## 完成标准与回退方式

**完成标准：** A01/A03配置部分/A10/A13通过；真实精选核验在08前明确NOT_RUN，不把本任务单测当来源可用性证据。

**回退：** 撤下精选配置或关闭入口，保留普通安全目录与证据历史，不删除订阅。

**交接：** 依C08给出变更文件、接口实际映射、base/head、命令/退出码、证据位置、未测和风险；不得只交“代码已写”。返回[任务总览](../../任务执行计划.md)。
