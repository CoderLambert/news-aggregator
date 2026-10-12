# 新闻列表慢网热修复（本地审核交付）

基线：只读 `git fetch origin main` 核对的 `8c2823e1fcf8cbea38e9bb7c4e98a33232025fbd`。
独立分支：`fix/news-list-slow-network`，目录 `/home/lambert/Documents/Codex/2026-10-12/task-3/repo`。
部署提交 `34bbe2b0f101a9c8423d66a5e296c223fc1d7d52` 包含此 main 基线；两者列表 serializer 的原正文契约相同。
当前 main 没有 deploy/nginx，故只带入部署提交的三个受管 Nginx 模板及对应模板回归测试，再修改压缩范围；没有带入部署代码或 BYOK 改动。
仓库、部署提交及工作目录祖先未发现 AGENTS.md 或 .agents/skills；组件变更按 React 最佳实践检查。

## 根因与最终接口契约

用户线上证据（未在远端复测）：首屏280,620字节、正文占94.4%，服务器约0.10秒，20KB/s时10秒仅传204,800字节，Axios10秒超时并重试失败。原 NewsListSerializer 无上限输出 content/content_zh，前端通用客户端10秒，部署模板没有 JSON gzip。传输时间而非应用健康检查能解释这个现象。

**裸 /api/news/ 默认返回轻量摘要。** NewsListSerializer 直接用 summary/summary_zh 替换 content/content_zh，每个最多300个Python Unicode字符；所有列表都不返回 content/content_zh/full_content/full_content_zh。其余列表元数据保持一致。省略 representation 与显式 representation=summary 同义；空值、full、legacy以及其他非法值返回400，且在语义/混合搜索执行前校验。不提供正文列表兼容模式，没有已核实消费者需要它；完整正文通过 /api/news/{id}/ 获取。

这是明确的列表响应契约迁移：外部列表消费者应使用 summary/summary_zh 显示预览，需要正文则按ID读取详情。后端与前端应协调发布。仓库内所有新闻列表入口（fetchNews、备用fetchSemanticSearch，包括搜索、筛选、分页）显式使用 summary 参数，同时裸API也已轻量，不依赖前端参数才修复。NewsCard原文/中文/双语及LocalSearch ArticleCard使用摘要字段。前端解析器为发布过渡期保留旧字段读取并截断的回退，但旧后端未更新时仍传大载荷，主要收益需要新后端生效。

详情保持完整content/content_zh/full_content。NewsSummary类型没有正文成员，NewsDetail明确声明正文；parseNewsDetail要求content/content_zh/full_content字段，拒绝摘要或旧列表对象冒充详情。列表/详情query key分离，useNewsDetail按ID取详情，导航state仅保存返回路径。NewsCard原有鼠标进入/聚焦预取走独立详情接口，未新增首屏逐条详情请求。聊天、翻译、全文抓取和TTS仍按ID/详情工作。

后端搜索仍检索完整正文；普通列表select_related(source, category)，语义/混合当前页select_related(...).in_bulk(page_ids)，共同使用NewsListSerializer，没有N+1。数据库查询仍读取正文列并在serializer截断；本次减少响应载荷，未优化数据库正文读取量。

fetchNews与fetchSemanticSearch单请求覆盖30,000ms；详情/分类仍10,000ms，全文抓取120,000ms、翻译180,000ms保持原值。AbortSignal继续传递；没有修改BYOK模型测试超时。

## 最终本地验证（2026-10-12）

- 后端相关70项与Nginx模板5项，合并75项全部通过（1条依赖弃用警告）。摘要测试26项覆盖空、299/300/301字符、中文/emoji、默认与显式摘要等价、详情完整正文、搜索/过滤/分页/回退、非法参数以及默认/显式摘要的语义/混合路径。向量结果使用替身，不调用模型。
- 20条与1条普通摘要列表均2次SQL；语义列表2次、混合列表3次（索引/向量使用替身），没有随条数增长的关系查询。
- 最终前端59文件382项通过；typecheck、lint、production build通过。
- 官方Nginx1.28.0用户态临时构建，受管模板本地替换端口/证书路径后nginx -t通过。实测Content-Encoding:gzip、Vary:Accept-Encoding、Cache-Control:no-store；解压与默认列表完全一致，默认/显式摘要内容一致。详情、模拟SSE及模拟私有JSON无压缩。
- 合成20篇文章：旧正文载荷513,599字节 → 默认摘要37,599字节（减少92.68%）→ 实际Nginx gzip1,147字节。**英文段落与中文正文大量重复，压缩率不能代表真实新闻；未采用用户预估112KB。** 最新脚本通过仅存在于测试WSGI包装器的端点重建旧正文载荷，生产API没有legacy/full模式。
- Chromium CDP下载/上传各20,480 bytes/s、100ms latency，实际Axios→独立Vite代理→Nginx→Django→临时SQLite：重建旧正文载荷10秒identity请求FAILURE/ECONNABORTED，10,002ms；**裸默认列表10秒identity请求SUCCESS，1,935ms**；前端fetchNews的30秒摘要identity请求SUCCESS，1,975ms；摘要gzip SUCCESS，221ms；额外12秒上游延迟SUCCESS，12,155ms。所有新列表请求20条且无content字段。
- 脚本在django.setup前设置既有测试保护和HF离线变量，并对EmbeddingService.preload、model属性、encode设置失败保护；启动及结束断言三个保护零次调用，最终报告为PASS: zero calls。成功验证轮次没有预热、模型加载或推理。
- 原始证据：verification/news-list-slow-network.json。
- NOT_RUN：腾讯服务器、远端运行测试、线上部署、生产文章压缩率、生产证书配置检查、完整SPA冷启动资产在20KB/s下的页面加载、真实语义模型/Provider Key调用、全量后端测试。

独立测试使用随机loopback端口、临时SQLite/证书/Nginx，结束停止自建进程；未更改/重启BYOK目录、5173/9528/9527/4000服务、tmux或Docker网关。

## 首次验证预热偏差记录

首次获准端口绑定的脚本遗漏测试保护，django.setup触发原仓库ApiConfig.ready→EmbeddingService.preload后台线程。源码创建SentenceTransformer(paraphrase-multilingual-MiniLM-L12-v2)，再执行encode('warmup', normalize_embeddings=True)。可见日志16:16:07.613开始加载、设备cuda:0；产生Hugging Face模型元数据HEAD与/api/agent-harnesses、/api/models等GET外部API请求；199项权重成功加载，Batches 1/1完成，16:16:32.899显示preloaded and ready。因此实际本地embedding推理已完成，不是只尝试预热。

发现后确认并SIGTERM停止本任务Python、临时Nginx与Vite进程；停止在预热完成之后，未记录信号精确时间。上述时间原样来自日志，时区未核实。未保留完整网络/缓存前后审计，无法准确确认当次是否下载了模型权重；加载进度本身不能证明下载，也不能断言没有下载。没有用户Provider Key、付费模型生成调用或腾讯连接。该次执行违反“不调用模型”约束，已如实报告；最终脚本修正与零调用证据见上。

## 复跑与审核后启用（部署动作未执行）

复跑需已有依赖或官方源，NGINX_BINARY指向独立用户态Nginx：

```sh
cd backend
python -m pytest api/tests/test_news_summary.py api/tests/test_search_index_recovery.py api/tests/test_chat_context.py api/tests/test_fetch_full.py api/tests/test_translation_jobs.py ../tests/backend/test_api_views.py -q
cd ..
PYTHONPATH=backend python -m pytest scripts/deploy/tests/test_nginx_templates.py -q
cd frontend
npm run test:run
npm run typecheck
npm run lint
npm run build
cd ..
NEWS_TEST_NGINX="$NGINX_BINARY" NEWS_TEST_REPORT=/tmp/news-list-report.json python scripts/verify_news_slow_network.py
```

1. 协调发布后端与前端；确认裸列表和显式摘要均无正文，详情返回完整正文，非法representation返回400。通知外部列表消费者迁移摘要字段；需要正文使用详情。无需数据库迁移。
2. 按既有部署流程安装受管news.lambert.host.conf与newshub-proxy.conf到原路径；bootstrap仅用于HTTP ACME。当前main缺少部署脚本，实际发布由主线程处理。
3. HTTPS server显式gzip off防止上层继承；仅精确/api/news/开启application/json gzip（min_length1024、level5、vary on），查询串不影响location匹配。Host/转发头清洗、no-store及SSE buffering/300s/gzip off保留；认证、详情、模型配置及私有API不启用JSON压缩。
4. 目标环境nginx -t后按既有流程reload；复核默认列表、gzip头与解压、详情、搜索分页及SSE首块及时送达。上述线上动作尚未执行。
5. 回滚应用和受管模板到部署前版本即可；无需迁移数据。
