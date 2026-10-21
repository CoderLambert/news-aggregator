# RSSD-03：中英文频道搜索与稳定分页

> 审阅：待审阅；实施：未开始；自动/人工验收：NOT_RUN。本文中的新增文件、接口、测试和命令是未来开发要求，本轮不执行。

## 目标与交付物

**目标：** 用户能按名称/主题/别名找到频道，筛选与分页结果可解释且无副作用。

**交付物：** 数据库检索、有限同义词、过滤交集、签名游标与固定50条相关度评估。

## 范围与前置依赖

**范围：** 本地查询与排序、输入边界、撤回安全、旧search_directory入口兼容。

**不包含：** 不做全网/模型/向量检索，不实现浏览页面或实时探测健康。

**前置依赖：** [RSSD-02.2](../catalog/RSSD-02.2-公开频道入目录与即时撤回.md)的已验收输出。

**必须引用的合同：** [开发合同](../../开发合同.md) C01、C03、C04、C07、C08；[完整方案](../../完整方案.md)相应产品/A编号。无需重读其他任务正文；接口以共同合同为准。

## 具体文件与输入输出

- 新增：backend/api/rss/directory_search.py、backend/api/rss/directory_data/search-synonyms-v1.json
- 修改：backend/api/rss/directory.py委托；规范化字段变更交02.1模型单写者
- 新增：backend/api/tests/rss/test_directory_search_v2.py；消费00固定golden fixture

**输入：** 规范化目录贡献、q/全部筛选/limit/cursor、当前活动checksum。

**输出：** C04 search_directory的results/next_cursor/snapshot_version及安全facets；featured分派在04接入。

## 实现方案与开发步骤

**方案：** 导入期NFKC/casefold物化，英文词边界与中文子串、多词AND；数据库完成可见性过滤、分层排序、分页。末尾规范名称+ID稳定；游标绑定全部条件和checksum，不加载全表Python排序。

- [ ] 1. 确认依赖输出、当前base/head与文件所有权；按C07准备无真实.env的隔离环境，读取适用AGENTS。
- [ ] 2. 先添加下表指定负例/契约断言；运行下列自动命令，保存原行为FAIL。环境/导入错误只记BLOCKED，不作为功能负例。
- [ ] 3. 按本卡文件、输入输出和方案实现最小改动；共同接口变化先同步开发合同及消费者。
- [ ] 4. 同命令运行至目标断言PASS，再做本卡列出的受影响回归；不扩大到无关全量测试。
- [ ] 5. 完成人工验收并记录实际版本/结果；缺前提记未测。更新总览对应项及C08证据，提交仅在另获授权后进行。

## 自动测试与通过条件

| 指定用例/检查 | 必须成立的断言 |
|---|---|
| `test_exact_alias_and_chinese_intersection` | 精确名称/别名高于简介，中文连续匹配及多词AND正确。 |
| `test_ai_does_not_match_email` | 英文词边界、防止偶然子串；%/_按文本，规范化后超长也400。 |
| `test_cursor_binds_filters_snapshot_and_sort` | 同快照连续翻页不重复/遗漏；更换q/filter/checksum拒绝旧cursor。 |
| `test_golden_search_quality` | 20实体至少19进Top3、30主题/别名至少27在Top5有相关项、精确名称100%命中。 |

关键断言示意（变量由该用例的隔离fixture提供，不能直接当现成测试执行）：

```python
assert 'email-only-feed' not in ids_for_ai
assert len(set(all_page_ids)) == len(all_page_ids)
assert entity_top3_hits >= 19 and topic_top5_hits >= 27
```

在C07环境执行：

```bash
PYTHONPATH=backend:crawler RUN_MAIN=true python -m pytest -q backend/api/tests/rss/test_directory_search_v2.py backend/api/tests/rss/test_directory.py
```

**预期：** 新增代码的目标断言先见原行为失败，实施后退出码0且断言全部通过；真实核验/基线/运营场景按本卡前提记录实际结果，不人为制造失败或把未运行记PASS。

**受影响回归与限制：** 补无网络/无写入断言及撤回专属简介不命中；输出实际排名和SQL，不为了达标改人工标注。

## 人工验收步骤

1. 搜索已收录的精确名称、中英文别名和域名，核对排序与50条固定样例。
2. 组合分类/语言/关键词逐页加载，核对交集和ID；改变条件及切快照测试过期提示。
3. 搜索vue.js、AI、%与_并观察请求边界，确认只有本地查询，未自动创建发现任务。

每步记录PASS/FAIL/未测及候选版本；合成/隔离结果不代表生产验收。

## 完成标准与回退方式

**完成标准：** A04/A05/A06/A07/A16/A21通过；golden结果可复查，容量最终证据留09。

**回退：** 关闭新查询入口回到兼容搜索；保持已发布身份及安全可见性过滤，不回滚用户数据。

**交接：** 依C08给出变更文件、接口实际映射、base/head、命令/退出码、证据位置、未测和风险；不得只交“代码已写”。返回[任务总览](../../任务执行计划.md)。
