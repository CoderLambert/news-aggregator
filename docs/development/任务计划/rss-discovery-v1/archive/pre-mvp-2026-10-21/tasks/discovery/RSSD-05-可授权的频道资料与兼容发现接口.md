# RSSD-05：可授权的频道资料与兼容发现接口

> 审阅：待审阅；实施：未开始；自动/人工验收：NOT_RUN。本文中的新增文件、接口、测试和命令是未来开发要求，本轮不执行。

## 目标与交付物

**目标：** 一个安全查询合同同时服务发现页和弹窗，批量补全当前用户状态且保持旧客户端可用。

**交付物：** 列表增量参数、只读详情、批量授权预览、动作判别联合、兼容能力扩展及前端服务。

## 范围与前置依赖

**范围：** HTTP/DTO/解析/查询键、错误码和新界面开关；在真实HTTP层验证旧字段/ACL/SQL。

**不包含：** 不实现页面交互，不写订阅业务，不改核心features键集合或另建HTTP客户端。

**前置依赖：** [RSSD-03](RSSD-03-中英文频道搜索与稳定分页.md)、[RSSD-04](RSSD-04-编辑精选与可信健康状态.md)、[RSSD-02.3](../catalog/RSSD-02.3-后台目录维护与回退版本保护.md)的已验收输出。

**必须引用的合同：** [开发合同](../../开发合同.md) C03、C04、C05、C06、C07、C08；[完整方案](../../完整方案.md)相应产品/A编号。无需重读其他任务正文；接口以共同合同为准。

## 具体文件与输入输出

- 修改：backend/api/rss/directory_http.py、backend/api/urls.py、backend/api/capabilities_views.py、backend/newsaggregator/settings.py
- 新增：backend/api/rss/directory_enrichment.py、frontend/src/types/rssDiscovery.ts、frontend/src/services/rssDiscoveryApi.ts
- 修改：frontend/src/services/{api.ts,workspaceApi.ts}、frontend/src/context/CapabilitiesContext.tsx
- 新增：backend/api/tests/rss/test_directory_http_v2.py、frontend/tests/services/rssDiscoveryApi.test.ts；扩展frontend/tests/services/capabilities.test.ts及context/CapabilitiesContext.test.tsx、backend/api/tests/test_public_policy.py

**输入：** DirectoryPage、本次viewer、当前授权/资格、服务端RSS_DISCOVERY_V2_ENABLED。

**输出：** C05 HTTP和C06前端两个查询函数/类型/机器错误码；现有capabilities的extensions.rss_discovery。

## 实现方案与开发步骤

**方案：** 数据库先做资料授权再分页；当前页批量查关系、至多3条授权标题、有效公共action。保留private,no-store。能力只加顶层extensions，核心features不变；扩展缺失/非法时仅新功能fail closed。WorkspaceError增量保留code且兼容旧构造。

- [ ] 1. 确认依赖输出、当前base/head与文件所有权；按C07准备无真实.env的隔离环境，读取适用AGENTS。
- [ ] 2. 先添加下表指定负例/契约断言；运行下列自动命令，保存原行为FAIL。环境/导入错误只记BLOCKED，不作为功能负例。
- [ ] 3. 按本卡文件、输入输出和方案实现最小改动；共同接口变化先同步开发合同及消费者。
- [ ] 4. 同命令运行至目标断言PASS，再做本卡列出的受影响回归；不扩大到无关全量测试。
- [ ] 5. 完成人工验收并记录实际版本/结果；缺前提记未测。更新总览对应项及C08证据，提交仅在另获授权后进行。

## 自动测试与通过条件

| 指定用例/检查 | 必须成立的断言 |
|---|---|
| `test_list_detail_and_facets_hide_withdrawn_origins` | 匿名/B用户无法通过资料、详情404、facets、健康或标题推断A私人来源。 |
| `test_page_sql_count_and_zero_side_effect` | 20条业务SQL≤12、50条增长≤2；GET网络/新增业务实体均0。 |
| `test_capability_extension_is_backward_compatible` | 核心features集合不变；新解析器接旧响应默认关闭，旧形状接扩展不破坏原能力。 |
| `test_parser_actions_and_machine_errors` | 两类action与unknown/null解析正确，400游标/409目录变化保留安全code，非法响应拒绝。 |

关键断言示意（变量由该用例的隔离fixture提供，不能直接当现成测试执行）：

```python
assert response['Cache-Control'] == 'private, no-store'
assert queries_20 <= 12 and queries_50 - queries_20 <= 2
assert legacy_features == new_response['features']
```

在C07环境执行：

```bash
PYTHONPATH=backend:crawler RUN_MAIN=true python -m pytest -q backend/api/tests/rss/test_directory_http_v2.py backend/api/tests/rss/test_directory_http.py backend/api/tests/test_public_policy.py
npm --prefix frontend run test:run -- tests/services/rssDiscoveryApi.test.ts tests/services/capabilities.test.ts tests/context/CapabilitiesContext.test.tsx
```

**预期：** 新增代码的目标断言先见原行为失败，实施后退出码0且断言全部通过；真实核验/基线/运营场景按本卡前提记录实际结果，不人为制造失败或把未运行记PASS。

**受影响回归与限制：** 前端typecheck/lint；保持api.ts核心严格校验和workspaceRequest Session/CSRF/viewer检查；SQL数字不得通过移除ACL达成。

## 人工验收步骤

1. 隔离服务分别以匿名/A/B请求同一目录与详情，对比自己的关系/预览而非其他用户数据。
2. 切换能力开关，检查顶层extensions及旧features；模拟无扩展旧响应，新功能关闭、原有页面能力正常。
3. 制造过期cursor和旧目录选择，观察安全机器码；对比20/50条SQL、响应体及GET前后实体数量。

每步记录PASS/FAIL/未测及候选版本；合成/隔离结果不代表生产验收。

## 完成标准与回退方式

**完成标准：** A10/A13/A14/A16/A18/A21及SQL门禁通过；新旧能力响应均有证据，05输出是06/07唯一DTO来源。

**回退：** 关闭扩展能力和新详情展示，保留旧接口/字段；保留安全授权补全和用户数据，不移除核心能力。

**交接：** 依C08给出变更文件、接口实际映射、base/head、命令/退出码、证据位置、未测和风险；不得只交“代码已写”。返回[任务总览](../../任务执行计划.md)。
