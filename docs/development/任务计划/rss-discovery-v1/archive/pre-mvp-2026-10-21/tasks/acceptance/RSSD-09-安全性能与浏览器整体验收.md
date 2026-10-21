# RSSD-09：安全性能与浏览器整体验收

> 审阅：待审阅；实施：未开始；自动/人工验收：NOT_RUN。本文中的新增文件、接口、测试和命令是未来开发要求，本轮不执行。

## 目标与交付物

**目标：** 从真实用户操作与不可信输入验证整个发现闭环，证明容量目标及权限没有退化。

**交付物：** A01～A23回归结果、首批/10k性能对比、三角色桌面/412px浏览器证据和未测清单。

## 范围与前置依赖

**范围：** 安全负例、只读零副作用、资源受限性能、IME/键盘/焦点/换号/刷新/重试。

**不包含：** 不修改阈值/放宽ACL求通过，不重建CI体系，不用mock代替浏览器或生产。

**前置依赖：** [RSSD-08](RSSD-08-真实候选与隔离Miniflux闭环核验.md)的已验收输出。

**必须引用的合同：** [开发合同](../../开发合同.md) C01～C08及完整方案6.1～6.5；[完整方案](../../完整方案.md)相应产品/A编号。无需重读其他任务正文；接口以共同合同为准。

## 具体文件与输入输出

- 新增：backend/api/tests/rss/test_discovery_security_v2.py、ops/rss/discovery_v1/{benchmark.py,browser_acceptance.py}
- 复用：既有backend目录/订阅/运行时测试、frontend/tests/features/rss/，以及仓库已有浏览器工具
- 运行后新增：本功能evidence/<candidate-sha>/安全/性能/浏览器数据及截图/trace

**输入：** 同一候选的01～08输出、隔离服务、固定50查询、首批和10k夹具、00基线。

**输出：** 各场景PASS/FAIL/NOT_RUN/BLOCKED、p95/p99/SQL/字节、原始命令退出码与browser trace。

## 实现方案与开发步骤

**方案：** 安全测试覆盖拨号层SSRF/重定向/DNS、凭据URL、HTML/XML、撤回/私人共享/版本竞态。性能脚本只接受隔离本地服务，固定2vCPU/4GiB、10并发、1000请求；浏览器脚本复用现有工具，桌面1440×900与412×915各跑匿名/普通/管理员。

- [ ] 1. 确认依赖输出、当前base/head与文件所有权；按C07准备无真实.env的隔离环境，读取适用AGENTS。
- [ ] 2. 先添加下表指定负例/契约断言；运行下列自动命令，保存原行为FAIL。环境/导入错误只记BLOCKED，不作为功能负例。
- [ ] 3. 按本卡文件、输入输出和方案实现最小改动；共同接口变化先同步开发合同及消费者。
- [ ] 4. 同命令运行至目标断言PASS，再做本卡列出的受影响回归；不扩大到无关全量测试。
- [ ] 5. 完成人工验收并记录实际版本/结果；缺前提记未测。更新总览对应项及C08证据，提交仅在另获授权后进行。

## 自动测试与通过条件

| 指定用例/检查 | 必须成立的断言 |
|---|---|
| `test_discovery_network_and_metadata_attacks` | 内网/loopback/链路本地/元数据地址、DNS/重定向与XML/HTML输入被原防线拒绝，不能mock绕过实际拨号层。 |
| `test_catalog_gets_have_zero_side_effect` | 500次GET外部调用/新增Feed/Source/订阅均0。 |
| `性能门禁` | p95≤300ms、p99≤800ms，20条SQL≤12、50条增长≤2，20条≤80KiB。 |
| `浏览器验收` | 两入口精选/搜索/分页/详情/确认，IME/焦点/换号/旧选择/丢响应重试和首次文章均有实际步骤结果。 |

关键断言示意（变量由该用例的隔离fixture提供，不能直接当现成测试执行）：

```python
assert outside_http_calls == feed_delta == source_delta == subscription_delta == 0
assert p95_ms <= 300 and p99_ms <= 800
assert sql_20 <= 12 and sql_50 - sql_20 <= 2
```

在C07环境执行：

```bash
PYTHONPATH=backend:crawler RUN_MAIN=true python -m pytest -q backend/api/tests/rss/test_discovery_security_v2.py
python ops/rss/discovery_v1/benchmark.py --isolated --entries 10000 --concurrency 10 --requests 1000
python ops/rss/discovery_v1/browser_acceptance.py --isolated
```

**预期：** 新增代码的目标断言先见原行为失败，实施后退出码0且断言全部通过；真实核验/基线/运营场景按本卡前提记录实际结果，不人为制造失败或把未运行记PASS。

**受影响回归与限制：** 脚本新增时固定参数与输出schema；保留原协议/权限测试。只有输入变更、失败或未决问题才补跑相关检查；不把三角色组件测试算浏览器通过。

## 人工验收步骤

1. 普通用户完成推荐→搜索→详情→订阅→添加记录→文章；管理员也验证相同用户边界，匿名只浏览并走登录返回。
2. 在桌面/412px使用中文IME、键盘、Escape、后退/刷新、快速改词和账号切换，逐步记PASS/FAIL/未测。
3. 核对性能原始样本、资源限制、0副作用计数与00同口径基线；没有测量就不声明更快。

每步记录PASS/FAIL/未测及候选版本；合成/隔离结果不代表生产验收。

## 完成标准与回退方式

**完成标准：** 全部硬验收对应真实证据且无未解释FAIL；缺真引擎/浏览器/性能项标NOT_RUN并阻止宣称完整验收。

**回退：** 关闭新展示、固定旧安全目录；只回收本任务隔离资源，保留失败证据，用户文章/关系不动。

**交接：** 依C08给出变更文件、接口实际映射、base/head、命令/退出码、证据位置、未测和风险；不得只交“代码已写”。返回[任务总览](../../任务执行计划.md)。
