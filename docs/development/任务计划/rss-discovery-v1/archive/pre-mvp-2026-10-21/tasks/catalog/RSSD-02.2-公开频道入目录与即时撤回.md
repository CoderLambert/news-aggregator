# RSSD-02.2：公开频道入目录与即时撤回

> 审阅：待审阅；实施：未开始；自动/人工验收：NOT_RUN。本文中的新增文件、接口、测试和命令是未来开发要求，本轮不执行。

## 目标与交付物

**目标：** 正式公开频道能够进入目录，撤回后即使不重建也不泄漏资料。

**交付物：** 公共资料投影构建函数、按来源贡献过滤的安全查询入口及同URL独立资料回退。

## 范围与前置依赖

**范围：** 白名单元数据、publication/link/binding版本与字段指纹、撤回前置过滤；保留现有公共成员/正文ACL。

**不包含：** 不改投稿审核、不公开私人订阅、不授权正文、不调度或直接激活目录。

**前置依赖：** [RSSD-02.1](RSSD-02.1-稳定频道身份与原子快照发布.md)的已验收输出。

**必须引用的合同：** [开发合同](../../开发合同.md) C01、C02、C03、C07、C08；[完整方案](../../完整方案.md)相应产品/A编号。无需重读其他任务正文；接口以共同合同为准。

## 具体文件与输入输出

- 新增：backend/api/rss/directory_public.py、backend/api/tests/rss/test_directory_public_projection.py
- 接管：backend/api/rss/directory_build.py的公共记录适配；模型变更仍由02.1单写者处理
- 复用：backend/api/rss/{access.py,public_membership.py}、backend/api/services/channel_catalog.py

**输入：** 当前正式公开SourcePublication及其受支持的link/binding、外部来源贡献、expected_head。

**输出：** C03 load_public_projection/visible_directory_origins/rebuild_public_directory；返回候选与public input_version，不激活。

## 实现方案与开发步骤

**方案：** 按每个Feed关联保存独立资料贡献和白名单指纹；读取时用当前授权/版本/字段相等条件排除旧贡献，再搜索/排序/统计。独立外部贡献从自身字段重新判断，不能保留撤回简介造成的命中。

- [ ] 1. 确认依赖输出、当前base/head与文件所有权；按C07准备无真实.env的隔离环境，读取适用AGENTS。
- [ ] 2. 先添加下表指定负例/契约断言；运行下列自动命令，保存原行为FAIL。环境/导入错误只记BLOCKED，不作为功能负例。
- [ ] 3. 按本卡文件、输入输出和方案实现最小改动；共同接口变化先同步开发合同及消费者。
- [ ] 4. 同命令运行至目标断言PASS，再做本卡列出的受影响回归；不扩大到无关全量测试。
- [ ] 5. 完成人工验收并记录实际版本/结果；缺前提记未测。更新总览对应项及C08证据，提交仅在另获授权后进行。

## 自动测试与通过条件

| 指定用例/检查 | 必须成立的断言 |
|---|---|
| `test_withdrawal_works_without_rebuild` | 停用重建，public→personal后匿名/其他用户看不到其专属名称、简介、来源或预览。 |
| `test_same_url_external_origin_does_not_inherit_private_terms` | 外部同URL记录保留，但只出现在其自身关键词/分类查询。 |
| `test_nonversioned_metadata_change_hides_old_contribution` | 仅改Source资料而不增policy_version也不会暴露旧字段。 |
| `test_old_snapshot_rollback_does_not_restore_public_grant` | 切旧快照后当前撤回仍生效。 |

关键断言示意（变量由该用例的隔离fixture提供，不能直接当现成测试执行）：

```python
assert withdrawn_source_id not in public_result_source_ids
assert search_by_withdrawn_only_term['results'] == []
assert external_public_name in search_by_external_term_names
```

在C07环境执行：

```bash
PYTHONPATH=backend:crawler RUN_MAIN=true python -m pytest -q backend/api/tests/rss/test_directory_public_projection.py backend/api/tests/rss/test_public_membership.py
```

**预期：** 新增代码的目标断言先见原行为失败，实施后退出码0且断言全部通过；真实核验/基线/运营场景按本卡前提记录实际结果，不人为制造失败或把未运行记PASS。

**受影响回归与限制：** 复核授权查询为SQL前置条件；public eligibility只影响动作，不能把暂停采集误当历史文章撤权；不改变authorized_sources既有语义。

## 人工验收步骤

1. 在合成DB发布一个含唯一关键词的公共来源，构建候选并显式发布，记录可见结果。
2. 冻结重建并撤回，分别请求该关键词、详情和facets，确认下一请求无撤回贡献。
3. 添加同URL独立外部资料后重复：独立名称可见，撤回关键词不可命中，健康/预览不继承。

每步记录PASS/FAIL/未测及候选版本；合成/隔离结果不代表生产验收。

## 完成标准与回退方式

**完成标准：** A09/A13/A16/A17成立；覆盖列表前置查询、字段变化、详情所需可见性函数和回退撤权。HTTP联调由05验证。

**回退：** 停用公共投影构建、固定旧安全快照；读取授权仍保留，不以删除Source或用户数据回退。

**交接：** 依C08给出变更文件、接口实际映射、base/head、命令/退出码、证据位置、未测和风险；不得只交“代码已写”。返回[任务总览](../../任务执行计划.md)。
