# RSSD-08：真实候选与隔离Miniflux闭环核验

> 审阅：待审阅；实施：未开始；自动/人工验收：NOT_RUN。本文中的新增文件、接口、测试和命令是未来开发要求，本轮不执行。

## 目标与交付物

**目标：** 证明真实Feed与引擎在指定隔离网络可用，区分候选数、连接成功和文章可读。

**交付物：** 24个不同精选的近期证据、网站发现/订阅/首次同步及unknown恢复的真引擎记录。

## 范围与前置依赖

**范围：** 专用Miniflux实例/DB/网络、受控Publisher、显式公开探测、资源数量与清理归属。

**不包含：** 不操作生产/真实用户库，不复制.env，不把隔离结果当生产可达，不开放未批准RSSHub能力。

**前置依赖：** [RSSD-07.2](../subscriptions/RSSD-07.2-公共频道订阅的分类与分组原子保存.md)的已验收输出。

**必须引用的合同：** [开发合同](../../开发合同.md) C04、C05、C07、C08；[完整方案](../../完整方案.md)相应产品/A编号。无需重读其他任务正文；接口以共同合同为准。

## 具体文件与输入输出

- 新增：ops/rss/discovery_v1/verify_live.py及隔离配置模板；复用tests/rss_engine_contract/{recovery_lab,live_self_service_review.py,contract.py}
- 新增：backend/api/tests/rss/test_discovery_live_guard.py（只测守卫，不发外网）
- 运行后新增：本功能evidence/<candidate-sha>/真实结果与受控证据

**输入：** 明确隔离实例标记/合成账号、精确候选SHA/目录hash、允许的公开探测清单。

**输出：** JSON结果包含目标identity、checked_at、环境/引擎/策略、parse/result/error及资源前后计数；可信健康由C04服务接收。

## 实现方案与开发步骤

**方案：** CLI默认禁止联网，必须--isolated且--allow-public-probes并验证专用lab marker。先用Publisher验多Feed/空/非法/重定向/断连，再显式核验受审24源；crawler关闭，出网/字节/并发/总时长有界。unknown先对账，只清理本次身份可证资源。

- [ ] 1. 确认依赖输出、当前base/head与文件所有权；按C07准备无真实.env的隔离环境，读取适用AGENTS。
- [ ] 2. 先添加下表指定负例/契约断言；运行下列自动命令，保存原行为FAIL。环境/导入错误只记BLOCKED，不作为功能负例。
- [ ] 3. 按本卡文件、输入输出和方案实现最小改动；共同接口变化先同步开发合同及消费者。
- [ ] 4. 同命令运行至目标断言PASS，再做本卡列出的受影响回归；不扩大到无关全量测试。
- [ ] 5. 完成人工验收并记录实际版本/结果；缺前提记未测。更新总览对应项及C08证据，提交仅在另获授权后进行。

## 自动测试与通过条件

| 指定用例/检查 | 必须成立的断言 |
|---|---|
| `test_live_guard_rejects_missing_marker_or_production` | 缺显式opt-in或实例/DB不属lab时，在任何网络/迁移前拒绝。 |
| `test_cleanup_requires_exact_created_identity` | 不按标题模糊删除，unknown未对账不能再create或盲清理。 |
| `真实引擎场景` | 多个/零候选、非法Feed、重定向、重复点击/双用户、unknown、首次同步均保存独立结果。 |

关键断言示意（变量由该用例的隔离fixture提供，不能直接当现成测试执行）：

```python
assert denied_probe_network_calls == 0
assert remote_feed_count_after_duplicate == remote_feed_count_after_first
assert result['connection_state'] == 'ready'
assert result['first_sync_news_count'] > 0 and result['authorized_article_read'] is True
```

在C07环境执行：

```bash
PYTHONPATH=backend:crawler RUN_MAIN=true python -m pytest -q backend/api/tests/rss/test_discovery_live_guard.py
python ops/rss/discovery_v1/verify_live.py --isolated --allow-public-probes
```

**预期：** 新增代码的目标断言先见原行为失败，实施后退出码0且断言全部通过；真实核验/基线/运营场景按本卡前提记录实际结果，不人为制造失败或把未运行记PASS。

**受影响回归与限制：** 第二条仅在已获隔离真引擎/公开探测授权并完成C07资源校验后运行；缺前提记NOT_RUN，不让单元测试自动访问外网。

## 人工验收步骤

1. 核对lab marker、实例/DB/网络和合成账户，确认不是现有运行栈。
2. 完成网站发现→候选→分类/分组确认→连接→文章读取，分别记录每步，不把Feed内摘要当完整正文。
3. 检查24不同Feed与六主分类、近7天证据；RSSHub未启用记NOT_RUN；核对清理清单仅含本次身份。

每步记录PASS/FAIL/未测及候选版本；合成/隔离结果不代表生产验收。

## 完成标准与回退方式

**完成标准：** A03/A11/A12/A15/A19/A23有真引擎证据；每个失败/未知/未运行如实记，不反复探测直到凑满通过。

**回退：** 终止本任务专用lab并保留证据；未知远端资源先对账，绝不停止/清理用户运行服务。

**交接：** 依C08给出变更文件、接口实际映射、base/head、命令/退出码、证据位置、未测和风险；不得只交“代码已写”。返回[任务总览](../../任务执行计划.md)。
