# RSSD-01：接入已选定的TidingsTop200清单

> 审阅：待审阅；实施：未开始；自动/人工验收：NOT_RUN。本文中的新增文件、接口、测试和命令是未来开发要求，本轮不执行。

## 目标与交付物

**目标：** 将用户已经选定的Tidings Top200 OPML适配为NewsHub目录，不重新选源，不自动订阅。

**交付物：** 已选Top200的200条逐项处理结果、NewsHub目录产物、来源锁与必要校验报告；不再补源或设语言配额。

## 范围与前置依赖

**范围：** 只读取本卡旁的[tidings-top200.opml](tidings-top200.opml)，转换名称、Feed地址、站点和原始分类，生成稳定ID并做必要格式/安全校验。

**不包含：** 不重新筛选频道、不从Plenary或Tidings全集补源、不设语言数量配额；不探测Feed健康、不改成自有网关、不注册Source/FeedBinding/订阅、不执行上游JS。

**前置依赖：** [RSSD-00](../planning/RSSD-00-冻结实际差额与开发合同.md)的已验收输出。

**必须引用的合同：** [开发合同](../../开发合同.md) C01、C07、C08；[完整方案](../../完整方案.md)相应产品/A编号。无需重读其他任务正文；接口以共同合同为准。

## 具体文件与输入输出

- 新增：scripts/rss/build_directory.py、backend/api/rss/directory_build.py
- 实施时逐字节复制：本地已选OPML → backend/api/rss/directory_data/tidings-top200.opml，保持hash；用户原文件不改
- 新增：backend/api/rss/directory_data/{sources-v2.lock.json,seed-v2.json,seed-v2.lock.json}及对应许可/排除清单
- 新增：tests/rss_discovery/test_catalog_compiler.py；复用backend/api/rss/opml.py的安全bytes解析边界

**输入：** 指定OPML的200条、C01来源/hash记录和历史身份清单；本任务public_sources=[]，不追加其他外部目录。

**输出：** C01 compile_catalog(...)返回DirectoryCandidate，CLI写受审产物及report，不激活快照。

## 实现方案与开发步骤

**方案：** 校验指定文件hash → 安全解析OPML → 逐项转换字段及稳定ID → 保留原14类/来源 → 生成NewsHub目录及200项处理结果。当前194个HTTPS、6个HTTP；按现有策略把受限地址或不支持类型明确记录，不改协议、不静默丢项，也不另找源补数。缺失简介/语言保持未知。

- [ ] 1. 确认依赖输出、当前base/head与文件所有权；按C07准备无真实.env的隔离环境，读取适用AGENTS。
- [ ] 2. 先添加下表指定负例/契约断言；运行下列自动命令，保存原行为FAIL。环境/导入错误只记BLOCKED，不作为功能负例。
- [ ] 3. 按本卡文件、输入输出和方案实现最小改动；共同接口变化先同步开发合同及消费者。
- [ ] 4. 同命令运行至目标断言PASS，再做本卡列出的受影响回归；不扩大到无关全量测试。
- [ ] 5. 完成人工验收并记录实际版本/结果；缺前提记未测。更新总览对应项及C08证据，提交仅在另获授权后进行。

## 自动测试与通过条件

| 指定用例/检查 | 必须成立的断言 |
|---|---|
| `test_selected_top200_is_the_only_external_input` | 输入hash匹配，200条各有处理结果；额外外部来源为0，不从全集补数。 |
| `test_same_inputs_reproduce_bytes` | 输入及历史相同则payload、checksum完全相同，无生成时间扰动。 |
| `test_upstream_validation_is_not_local_health` | validated_at只在来源资料中，本地verified_at为null。 |
| `test_http_and_unsafe_xml_are_quarantined` | HTTP不升级；DTD/实体/超深XML拒绝；凭据URL在报告中脱敏。 |
| `test_native_and_third_party_are_not_confused` | 第三方RSSHub不标原生；同URL合并、多栏目/参数URL分别保留。 |
| `test_original_categories_and_missing_metadata_are_preserved` | 原14类及视频/播客条目均能追踪到结果；缺语言不猜测，不因非文章类型替换来源。 |

关键断言示意（变量由该用例的隔离fixture提供，不能直接当现成测试执行）：

```python
assert first['payload'] == second['payload']
assert first['checksum'] == second['checksum']
assert imported_entry['verified_at'] is None
assert report['input_count'] == len(report['items']) == 200
assert extra_external_sources == []
```

在C07环境执行：

```bash
PYTHONPATH=backend:crawler RUN_MAIN=true python -m pytest -q tests/rss_discovery/test_catalog_compiler.py
```

**预期：** 新增代码的目标断言先见原行为失败，实施后退出码0且断言全部通过；真实核验/基线/运营场景按本卡前提记录实际结果，不人为制造失败或把未运行记PASS。

**受影响回归与限制：** 运行既有backend/api/tests/rss/test_directory.py；检查sources/FeedBinding/ChannelSubscription数量及网络计数不因编译变化。

## 人工验收步骤

1. 核对指定文件的200个地址、14类与C01 hash；确认没有导入其他目录。
2. 对同一文件转换两次，对比生成checksum；抽查名称、xmlUrl、htmlUrl和原始分类是否对应。
3. 核对200项处理结果总账，查看6个HTTP及不支持项的明确原因；不得擅自替换地址/来源，不以中英文配额验收。

每步记录PASS/FAIL/未测及候选版本；合成/隔离结果不代表生产验收。

## 完成标准与回退方式

**完成标准：** A02按固定Top200接入验收，200条全部有结果，无额外选源/补数；A08/A20/A22及确定性检查通过。这里只完成目录适配，健康仍unknown，不能标成200个Feed都已连接。

**回退：** 保留seed-v1，撤销新输入选择；未激活快照、不删除订阅。

**交接：** 依C08给出变更文件、接口实际映射、base/head、命令/退出码、证据位置、未测和风险；不得只交“代码已写”。返回[任务总览](../../任务执行计划.md)。
