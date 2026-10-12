# 新闻列表慢网热修复（本地审核交付）

基线：只读 `git fetch origin main` 核对的 `8c2823e1fcf8cbea38e9bb7c4e98a33232025fbd`。
独立分支：`fix/news-list-slow-network`，目录 `/home/lambert/Documents/Codex/2026-10-12/task-3/repo`。
部署提交 `34bbe2b0f101a9c8423d66a5e296c223fc1d7d52` 包含此 main 基线；两者列表 serializer 的正文契约相同。
当前 main 没有 deploy/nginx，故只带入部署提交的三个受管 Nginx 模板及对应模板回归测试，再修改压缩范围；没有带入部署代码或 BYOK 改动。
仓库、部署提交及工作目录祖先未发现 AGENTS.md 或 .agents/skills；组件变更按 React 最佳实践检查。

## 根因与契约

用户线上证据（未在远端复测）：首屏 280,620 字节、正文占94.4%，服务器约0.10秒，20KB/s时10秒仅传204,800字节，Axios10秒超时并重试失败。代码确认 NewsListSerializer 无上限输出 content/content_zh，前端通用客户端10秒，部署模板没有 JSON gzip。传输时间而非应用健康检查能解释这个现象。

为避免无区别破坏公共契约，新增显式 `representation=summary` 列表投影；旧参数省略时仍返回原列表正文。所有仓库前端新闻列表入口（fetchNews、fetchSemanticSearch，包括搜索、筛选、分页）固定使用新投影。新投影返回 `summary`、`summary_zh`，每个最多300个Python Unicode字符，不返回 content/content_zh/full_content/full_content_zh；其余列表元数据保持一致。

NewsCard 原文/中文/双语显示以及 LocalSearch ArticleCard 使用摘要字段。前端解析器在后端先后发布的过渡期可以读取旧字段并截断；此兼容回退不能减少旧后端在网络上的字节，需要发布后端才能获得主要收益。未迁移的外部旧列表调用仍有大载荷，必须主动加 representation=summary；不宣称所有无参数列表调用已缩小。

详情保持完整 content/content_zh/full_content。NewsSummary 类型没有正文成员，NewsDetail 明确声明正文；parseNewsDetail 要求 content/content_zh/full_content 字段，拒绝新摘要和旧列表对象冒充详情。新闻列表和详情 query key 分离，useNewsDetail 只按ID取详情，导航 state 仅保存返回路径。聊天、翻译、全文抓取和TTS仍按ID/详情工作。后端搜索仍检索完整正文；所有序列化路径继续 select_related(source, category)，没有逐条详情请求或 N+1。

fetchNews 和 fetchSemanticSearch 单请求覆盖30,000ms；详情/分类仍10,000ms，全文抓取120,000ms、翻译180,000ms保持原值。AbortSignal继续传递；没有改 BYOK 模型测试超时。

## 本地验证（2026-10-12）

- 后端相关回归53项和Nginx模板5项，最终合并运行58项全部通过（有1条依赖弃用警告）；其中摘要测试9项，语义/混合真实列表路径使用替身向量结果、无模型调用。摘要边界覆盖空、299/300/301字符及中文/emoji，详情完整正文、旧契约、搜索/过滤/分页/回退。
- 20条和1条普通摘要列表均2次SQL；语义列表2次、混合列表3次（搜索索引/向量使用替身）。未发生随条数增长的关系查询。
- 最终前端完整回归59文件382项通过；typecheck、lint、production build通过。
- Nginx受管模板5项回归通过。实际官方Nginx1.28.0用户态临时构建的 `nginx -t` 通过；合成请求实测 Content-Encoding:gzip、Vary:Accept-Encoding、Cache-Control:no-store，解压内容完全一致；详情、模拟SSE及模拟私有JSON无压缩。
- 合成20篇文章（重复英文段落和中文正文；不是生产数据）：旧列表513,599字节 → 新摘要37,599字节（减少92.68%）→ 实际Nginx gzip1,144字节。重复度高，gzip比率不能外推到生产文章；没有采用用户预估112KB作为实测。
- Chromium CDP下载/上传各20,480 bytes/s、100ms latency，实际前端Axios模块→独立Vite代理→Nginx→Django→临时SQLite：旧10秒identity请求 FAILURE/ECONNABORTED，10,001ms；新30秒摘要identity SUCCESS 1,936ms；新摘要gzip SUCCESS 219ms；额外12秒上游延迟 SUCCESS 12,157ms。每次新请求20条且无content字段。机器可读证据见 verification/news-list-slow-network.json。
- NOT_RUN：腾讯服务器、远端运行测试、线上部署、生产文章压缩率、生产证书配置检查、完整SPA冷启动资产在20KB/s下的页面加载、真实语义模型/Provider Key调用、全量后端测试。

独立测试只用随机loopback端口、临时SQLite/证书/Nginx，结束时停止自建进程；未更改/重启BYOK目录、5173/9528/9527/4000服务、tmux或Docker网关。初次脚本遗漏测试保护，仓库启动钩子意外触发Hugging Face元数据请求和本地embedding预热；已停止该次进程。最终脚本在django.setup之前设置既有测试保护和HF离线环境，成功验证轮次没有模型调用。没有Provider Key、付费模型请求或腾讯连接。

复跑（使用已有依赖或官方源，NGINX_BINARY为独立用户态Nginx路径）：

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

## 审核后启用说明（未执行）

1. 将后端与前端作为同一热修复发布，确认浏览器请求带 representation=summary，响应含双语摘要且无正文。无数据库迁移。
2. 在既有部署流程中安装受管 news.lambert.host.conf 与 newshub-proxy.conf 到原路径。bootstrap模板保持HTTP ACME用途，不承载应用。当前main缺少部署脚本，实际部署由主线程按既有发布流程完成。
3. 新 HTTPS server 显式gzip off阻止上层继承；仅精确location = /api/news/打开application/json gzip（min_length1024、level5、vary on）。查询串不影响精确location匹配。原Host、转发头清洗、Cache-Control以及SSE buffering/300s/gzip off保留。其余认证、详情、模型配置及私有API不启用JSON压缩；新闻列表仅含公开文章与状态元数据。
4. 在目标环境执行 nginx -t 后按既有流程reload；检查正常列表、带gzip请求的Content-Encoding/Vary及完整解压、详情正文、搜索分页、SSE首块及时送达。这些线上动作尚未执行。
5. 回滚应用和受管模板到部署前版本即可；无需迁移数据。外部消费者可以保持旧契约，或显式迁移到摘要投影。
