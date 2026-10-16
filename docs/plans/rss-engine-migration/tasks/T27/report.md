# T27 产品联合验收记录

日期：2026-10-16。合成全链浏览器 **PASS**；有限公开来源取样已运行，产品最终封存仍 **PARTIAL / BLOCKED**。本报告不是生产验收，也不替代 T26 的最终双库恢复证据。

业务基线 `9043a99`，叠加 root 的 initial_sync 文案修正 `da41523`（本分支 cherry-pick 为 `80ed9e465b1062567bb4aca87c5bc1b8c4c4f5ca`）。没有修改业务代码、DDL 或生产配置。

## 实际环境与隔离

- Python 3.12.14，共享解释器只读；Node 24.22.0（本机版本，并非计划中的 Node 22）；Chromium 152.0.7977.82；Vite 8.0.13 开发服务。
- Miniflux 2.3.3、PostgreSQL 17.6，沿用 `ops/rss/T00/compose.yaml` 固定 digest。浏览器项目 `newshub-rss-t27-eeb51bcc2c75`，公开来源项目 `newshub-rss-t27-public-5b426547ef`，均已 `down --volumes --remove-orphans`。
- SQLite、运行时目录、随机环回端口、账号、令牌、TLS CA 全为本次合成夹具；未读取活动工作区 DB、真实用户凭据或生产环境。应用进程没有引擎 token，只有独立 sync worker 持有它。
- 合成引擎允许访问本项目 publisher 容器；公开来源使用私网保护开启的 guarded 引擎。浏览器未 stub API，只将固定图片 URL 返回合成 SVG。真实 AI provider 边界换成固定回答，外部 TTS 调用禁用。

## 命令与结果

```bash
/tmp/newshub-rss-coordinator-venv/bin/python ops/rss/T27/run_browser.py \
  --output /tmp/rss-t27-browser-final2
# exit 0，全链 browser-evidence.status=passed
/tmp/newshub-rss-coordinator-venv/bin/python ops/rss/T27/sample_public.py \
  --output /tmp/rss-t27-public-evidence.json
# exit 0，5 feeds sampled + Uber failed；失败保留在结果中
/tmp/newshub-rss-coordinator-venv/bin/python -m pytest -q \
  tests/rss_engine_contract/test_product_acceptance.py
# 3 passed, 1 skipped；skip 是需要显式 allowlist 的 fresh live 包装器。
```

真正浏览器/Docker 执行由第一条命令完成；3 个 pytest 是已保存证据的一致性检查，不能冒充又跑了 3 次真实引擎。调试中的错误候选 fixture、错误 TTS method、目录搜索不存在的 WebKit seed、toast 精确定位器与登录限流均已修正为正确夹具/操作；最终 fresh 项目一次全链通过。

## 浏览器结果

证据：[结果](../../../../../ops/rss/T27/evidence/browser-evidence.json)、[网络](../../../../../ops/rss/T27/evidence/network.json)、[publisher audit](../../../../../ops/rss/T27/evidence/publisher-requests.jsonl)。

| 验收点 | 实际结果 |
| --- | --- |
| 首访、详情 GET、hover、关键词搜索 | passive 阶段全部请求 GET；无 fetch-full / rss-refetch / refresh / 隐式订阅；publisher 在该阶段没有 article 请求 |
| 原生正文 | 首访前已由真实引擎→worker→SQLite 存好；code DOM 与 clipboard 逐字符相同，包括双空格与尾换行；表格 alpha/42 与图片显示正确 |
| A/B/匿名 | 私有 A/B 对匿名 404；A→退出→B 原页面不再显示 A 标题，B 搜索无 A；B 的 A 详情、chat POST、tts GET 都 404 |
| 个人状态 | A 标已读、收藏后重载保留；B 相同公开 News 仍未读/未收藏；A 私有来源退订后详情和重载都 404 |
| AI | A 的真实 UI 请求通过真实权限/存储正文路径，fake provider 回答显示；B 越权请求在 provider 前拒绝；不是实际模型质量/计费验证 |
| 目录与发现 | Coding Horror 本地目录搜索；真实引擎网站发现分别返回 0 / 1 / 3 个候选；直接 RSS 加入两个个人分组并后台连接 |
| OPML | 上传→预览去重→只选一个 feed→两个 folder 映射到两个组→确认→已连接→导出；跳过 feed 未导出，两个分组保留 |
| 连接与修复 | 页面显示引擎可用、最近实际增量/全对账完成；显式管理员策略更新后点击重新获取，真实原文请求经 worker 写入后显示扩展正文，code 未变 |
| 移动端 | 390×844 下输入→Enter→Tab 焦点仍在 dialog→Escape 关闭；阅读页无横向溢出；浏览器 pageerror=0 |
| 受限来源 | summary_only fixture 只获取 feed，无 `/article/restricted` 请求；不宣称实际付费站点已获准 |

截图：[原生代码/表格](../../../../../ops/rss/T27/evidence/01-stored-code-table.png)、[授权 AI](../../../../../ops/rss/T27/evidence/02-alice-authorized-chat.png)、[连接状态](../../../../../ops/rss/T27/evidence/03-connection-health.png)、[三候选](../../../../../ops/rss/T27/evidence/04-discovery-three-candidates.png)、[直接连接](../../../../../ops/rss/T27/evidence/05-direct-connected.png)、[OPML 选择](../../../../../ops/rss/T27/evidence/06-opml-selection.png)、[OPML 进度](../../../../../ops/rss/T27/evidence/07-opml-progress.png)、[明确修复](../../../../../ops/rss/T27/evidence/08-explicit-repair.png)、[移动键盘](../../../../../ops/rss/T27/evidence/08-mobile-keyboard-dialog.png)、[移动阅读](../../../../../ops/rss/T27/evidence/09-mobile-reader.png)。

## 公开来源质量与延迟

[逐文章真实 URL、发布日期、HTML/Markdown 长度/hash、结构计数和延迟](../../../../../ops/rss/T27/evidence/public-samples.json)。没有保存第三方完整文章文本。所有 feed 此轮明确用 `feed / crawler=false`；非原生样本只对选中的条目显式 refetch。**这不是新默认自动摘要采集的证明**，该策略修正的独立补测另记。

| 来源 | 有界取样结果 | 范围与限制 |
| --- | --- | --- |
| Julia Evans atom.xml | 2 篇，18,931 / 11,318 Markdown 字符，10 / 11 code blocks | feed 原生内容；未额外抓原网页来取得同一正文 |
| WebKit feed | 2 篇，3,845 / 10,926 字符，9 / 40 headings | feed 原生内容；当前 feed 最早两条，并非宣称最新发布 |
| Martin Fowler atom | 2 篇，feed 567 / 453→提取 16,170 / 22,852 字符 | 显式提取有结构内容；第二篇含 2 个 table、2 个 code blocks |
| Uber Engineering RSS | 建 feed 失败 `create_unknown`，1.109 秒 | 保留失败，不从两个技术博客的分母删除 |
| DEV 当前 feed | 2 篇，提取 5,090 / 5,282 字符 | 第一篇有 5 个代码块与 1 个表格；不是旧 News 8555 的身份确认 |
| Hacker News | article / GitHub / video 各 1 篇，5,542 / 13,597 / 779 字符 | 视频仅页面内容，不是转录；当前 30 条 feed 无 self_post，未扩展无限采样 |

这里的 nonempty_readable 字段仅表示转换输出非空，不等于人工确认可读或完整。首轮 11 篇当时均 `manual_completeness=not_confirmed`；后续同 URL 的两篇原站对照见末节，其余仍未逐篇核对，不能报 90% 完整成功率。普通摘要来源第二站失败、HN self_post 缺样本都仍是覆盖缺口。

[指标](../../../../../ops/rss/T27/evidence/metrics.json)：本地目录 20 次实际浏览器 HTTP 请求 p50 25.361 ms / nearest-rank p95 156.424 ms / max 177.559 ms。Fowler 显式提取 n=2 p95 1.133 s；DEV n=2 p95 1.698 s；HN n=3 p95 1.428 s。小样本 p95 近似最大值，不是服务 SLA。合成 4-feed 从开始注册到同步可见及 seed 导入的整批时间 0.264 s，只有一次，不将它写成引擎落库→可见 p95；公开文章发布→可读总时延未测。

## 仍未封存的门禁

- DEV 旧 `/news/8555` 的真实 URL：没有授权的真实 DB 副本，NOT_VERIFIED。
- RSSHub GitHub Trending：缺可用 TLS/token 和维护路由实例，BLOCKED。
- 真实 AI/TTS provider：未提供凭据，未计费；只证明 fake provider 正文路径及越权 HTTP 拒绝，实际语音/模型输出质量 NOT_RUN。
- T26 双库/完整 app 恢复由协调者单独封存；此前 T00/T03/T08/T09 的故障证据只能按各自报告版本引用，不能冒充本次 SHA 全套重演。
- Node 22、生产 bundle、真实手机软键盘和真实用户手动验收未运行；此处是 Chromium viewport + 实际键盘事件。

没有发生错误文章覆盖、跨用户正文泄漏、代码文本改写或合成用户关系丢失；此结论限于上述实际执行范围。最终产品验收不因本报告的合成 PASS 自动变为 DONE。

## 策略修复后的有界补验

已普通 merge 协调者安全基线 `23de7332976da37d92759beaf952f9afdb25d80a`，测试业务树为 `294c7b13e42bae7b3418354a5560154981735ab3`。生产默认 gate=0 未改变；只有合成夹具显式 `RSS_FULL_CONTENT_ENABLED=1`，公开 SDK 只在本次工具中显式 `full_content_enabled=True`。

```bash
/tmp/newshub-rss-coordinator-venv/bin/python ops/rss/T27/run_browser.py \
  --automatic-summary --output /tmp/rss-t27-automatic-theme4
# exit 0；真实普通用户订阅→Miniflux自动提取→Sync→SPA
/tmp/newshub-rss-coordinator-venv/bin/python ops/rss/T27/sample_public.py \
  --supplement-github --output /tmp/rss-t27-github-supplement.json
# exit 0；一次feed模式创建，仅一条article显式refetch
/tmp/newshub-rss-coordinator-venv/bin/python -m pytest -q \
  tests/rss_engine_contract/test_product_acceptance.py
# 6 passed, 1 skipped in 0.02s；新增三个证据审计检查（含最终原站对照）
```

自动摘要：[结果](../../../../../ops/rss/T27/evidence/automatic/automatic-evidence.json)、[浏览器请求](../../../../../ops/rss/T27/evidence/automatic/automatic-network.json)、[publisher 时间序列](../../../../../ops/rss/T27/evidence/automatic/publisher-requests.jsonl)、[首屏](../../../../../ops/rss/T27/evidence/automatic/automatic-summary.png)、[实际滚动后的扩展段落](../../../../../ops/rss/T27/evidence/automatic/automatic-expanded.png)。普通非管理员 Bob 从真实“直接 RSS”界面订阅一个只含短摘要的单条 Feed；没有传 mode、没有调用 policy/refetch/fetch-full。引擎恰好请求一次该原文，时间早于第一条 News 读取；订阅是 personal，默认 full_content，后台落库后页面显示 Feed 中不存在的扩展段落及精确 code。最后一次运行订阅→connected 4.013 s、订阅→列表可见 29.944 s，pageerror=0。这是一个受控案例，不是互联网延迟 p95。首次补验也通过；随后为图片夹具、滚动段落及主题/TOC 补验重跑这个小案例，没有重跑整套浏览器。

[GitHub Blog 补样](../../../../../ops/rss/T27/evidence/github-supplement.json)：实际文章 [Building Git infrastructure for agent-scale development](https://github.blog/engineering/architecture-optimization/building-git-infrastructure-for-agent-scale-development/)，日期 2026-10-06；feed 模式创建 1.471 s，Feed Markdown 已有 11,866 字符，单条提取 0.920 s 后 16,301 字符、19 headings、9 images。**它是第二个成功取得公开技术博客内容的来源，但 Feed 原本很长，不足以证明第二个典型短摘要博客案例。** 人工完整性仍 not_confirmed；Uber 的失败与此前分母原样保留，不伪造综合成功率。

首轮 HN 视频/GitHub 外链的显式提取属于 **pre-policy（收紧前）证据**，不是新策略允许该操作的证明。未来采样脚本只对 subtype=article 做显式提取，非 article 保留 feed 内容。没有在新 gate 下重复这些禁止路径。

补验两个项目 `newshub-rss-t27-eec566b89bb8` 与 `newshub-rss-t27-public-1fc2278d25` 均清理；调试项目同样清理，无 `newshub-rss-t27-*` 容器/网络/卷残留。新增结果没有解除前述真实副本、RSSHub、付费 provider、人工完整性及最终封存限制。

## 两篇既有样本的原站对照

首轮清理时没有保留引擎正文，导致当时只能报告结构计数；这是取证缺口，**不是环境无法做人工对照**。按协调者授权，仅重新取得原有 1 篇 Julia、1 篇 Fowler 的相同 URL，各一次尝试；没有新增文章分母，没有追换来源。Julia 只取 feed 内容，Fowler 仅对指定 entry 提取一次。新隔离项目 `newshub-rss-t27-public-a4ee2dc1a3` 已清理。

```bash
/tmp/newshub-rss-coordinator-venv/bin/python ops/rss/T27/sample_public.py \
  --manual-repeat --retain-bodies /tmp/newshub-rss-t27-quality-20261016 \
  --output /tmp/rss-t27-quality-repeat.json
# exit 0，两篇旧URL均取得，hash均与首轮精确一致
/tmp/newshub-rss-coordinator-venv/bin/python ops/rss/T27/compare_retained.py \
  --bodies /tmp/newshub-rss-t27-quality-20261016 \
  --repeat-evidence /tmp/rss-t27-quality-repeat.json \
  --output /tmp/rss-t27-quality-review.json
# exit 0；原站页面正常只读浏览，再以HTML结构比较交叉核对
```

[再次取样](../../../../../ops/rss/T27/evidence/quality-repeat.json)及[对照结果](../../../../../ops/rss/T27/evidence/quality-review.json)。原站/引擎 HTML 与 Markdown 只暂存在上述权限隔离的 `/tmp` 目录供复核，不进 Git。此处是 Agent 阅读原站并逐项核对，**不是最终用户的人工签收**，也没有修改任何生产 verified 标记。

- **Julia 原生正文：本篇正文范围 PASS。** [原文](https://jvns.ca/blog/2024/11/18/how-to-import-a-javascript-library/)标题与 entry DTO 一致；首段引入、末段致谢均保留；原站 `main` 的归一化全文、60 段的顺序、20 个标题的顺序完全一致，10 个代码块逐字符一致，包含 importmap 的缩进和 shell 示例。代码、段落不靠长度推断。该原文没有 table，不能据此声称公开表格已人工验过；表格的精确保真仍来自前面的受控浏览器案例。
- **Fowler 提取：主体可读，完整性未通过。** [原文](https://martinfowler.com/articles/orchestrator-tax.html)标题 DTO 正确，叙事首尾和最后的问题列表保留；`main .paperBody` 的 42 个非空段落按原序保留、7 个主章节与 4 幅图保留。但原站标题下导语、作者简介、Related Work 与日期/修订信息未进入提取正文；原站末尾 Acknowledgments 在提取结果中跑到最前。原站显示日期 2026-07-16，而 Feed 日期为 2026-07-28，记录两者差异，不静默改写来源日期。该文无代码块/table。

两篇都重现首轮精确 canonical hash，所以缺失/顺序差异不是复查时文章变了，也不是 NewsHub 覆盖了另一篇文章。有效结论限于 **1 篇原生正文保留、1 篇提取主体可读但外围内容/顺序不完整**；未核对的其他样本仍 NOT_RUN，不能推 90% 或任何总体成功率。Fowler 差异应作为引擎抽取质量清单保留，本任务没有添加爬虫或修改正文来掩盖差异。


## 主题与真实目录控件补验

最终上述 `--automatic-summary` 运行同时完成：真实“切换深色”→“切换浅色”，两次代码逐字符不变、布局均为 266.89 × 129.17 CSS px，无页面横向溢出；前景分别为 rgb(225,228,232) / rgb(36,41,46)。已逐张观察[深色](../../../../../ops/rss/T27/evidence/automatic/automatic-dark.png)、[浅色](../../../../../ops/rss/T27/evidence/automatic/automatic-light.png)截图，代码、表格和图片可见；这是有限样例视觉检查，不是全站 WCAG 对比度认证。

合成原文增加两个真实 h2，实际“打开目录”显示文章标题层级；点击 Closing section 后目标 y 从 1631.41 移至 957.41、进入 1000px 视窗，[目录截图](../../../../../ops/rss/T27/evidence/automatic/automatic-toc.png)包含目标标题与真实控件。未伪造 TOC 按钮，未改业务代码，也未因此增加公网实验。

调试中两次节点滚动失败来自异步代码高亮替换 DOM，改为重取 locator 同步滚动；一次 20 秒轮询边界早于 worker 下一轮，调至有界 60 秒。最终 fresh 项目一次完整通过上述最小路径；失败项目亦清理。最终证据审计 **6 passed, 1 skipped**，`py_compile` 与 `git diff --check` 通过；skip 是未重复的全链 live pytest 包装器，真实浏览器由所列命令执行。
