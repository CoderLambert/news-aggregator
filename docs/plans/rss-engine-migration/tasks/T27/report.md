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

这里的 nonempty_readable 字段仅表示转换输出非空，不等于人工确认可读或完整。11 篇均 `manual_completeness=not_confirmed`；人工完整性没有足够逐篇原站对照证据，不能报 90% 完整成功率。普通摘要来源第二站失败、HN self_post 缺样本都仍是覆盖缺口。

[指标](../../../../../ops/rss/T27/evidence/metrics.json)：本地目录 20 次实际浏览器 HTTP 请求 p50 25.361 ms / nearest-rank p95 156.424 ms / max 177.559 ms。Fowler 显式提取 n=2 p95 1.133 s；DEV n=2 p95 1.698 s；HN n=3 p95 1.428 s。小样本 p95 近似最大值，不是服务 SLA。合成 4-feed 从开始注册到同步可见及 seed 导入的整批时间 0.264 s，只有一次，不将它写成引擎落库→可见 p95；公开文章发布→可读总时延未测。

## 仍未封存的门禁

- DEV 旧 `/news/8555` 的真实 URL：没有授权的真实 DB 副本，NOT_VERIFIED。
- RSSHub GitHub Trending：缺可用 TLS/token 和维护路由实例，BLOCKED。
- 真实 AI/TTS provider：未提供凭据，未计费；只证明 fake provider 正文路径及越权 HTTP 拒绝，实际语音/模型输出质量 NOT_RUN。
- T26 双库/完整 app 恢复由协调者单独封存；此前 T00/T03/T08/T09 的故障证据只能按各自报告版本引用，不能冒充本次 SHA 全套重演。
- Node 22、生产 bundle、真实手机软键盘和真实用户手动验收未运行；此处是 Chromium viewport + 实际键盘事件。

没有发生错误文章覆盖、跨用户正文泄漏、代码文本改写或合成用户关系丢失；此结论限于上述实际执行范围。最终产品验收不因本报告的合成 PASS 自动变为 DONE。
