# 个人频道分组、新能源医疗 RSS 与地区筛选

- 日期：2026-10-13
- 分支：main
- 交付范围：个人频道阅读配置及新增能源、医疗频道的采集和筛选；不包含运行数据库。

## 目标与实际变更

支持账号订阅频道、多分组归属与跨设备恢复首页阅读范围；新增 12 个新能源和 14 个医疗来源，并为现有来源设置国内／国际属性。

| 模块 | 实际变更 |
| --- | --- |
| models、channel_views、channel_catalog、0039–0042 迁移 | 订阅、分组、成员、偏好与地区字段；初始化频道目录，保留既有来源、文章和账号配置 |
| views、serializers、channel_articles | 列表及关键词、语义、混合搜索共享范围、屏蔽、去重与地区条件；支持一篇文章归属多个采集频道 |
| sector_feeds、source_policy、feed_support、source_dates、energy_keywords | 新来源策略、RSS 日期容错、新能源关键词筛选、明确的摘要阅读策略 |
| crawl、sector_feeds_spider、pipelines、category_map | 注册新增可采集频道及新能源、医疗健康分类 |
| full_content_status、article_fetcher、research | 限制摘要来源的正文获取与正文消费；医疗回答附真实来源信息 |
| 前端页面、组件、hooks、services、types | 频道管理和批量操作；首页阅读范围、地区筛选、URL 恢复、失败重试及账号缓存隔离；医疗提示、实际原文链接、摘要缺失和推断日期说明 |
| 后端、爬虫、前端测试 | 覆盖账号隔离、空范围、搜索一致性、迁移保留、跨频道去重、地区筛选与医疗阅读限制；适配迁移初始化来源的既有测试数据 |
| README | 更新频道管理、分类、采集策略与部署说明 |

## 实现与兼容性

个人接口使用登录会话和现有 CSRF 保护，组查询限定账号；同一频道可加入多个组，取消订阅移除全部归属，删除组保留订阅。首页切换阅读范围清除临时来源并重置分页，保留分类与搜索；空范围不扩大为全站内容。显式 URL 优先，未指定范围时恢复账号偏好。界面将未分组标为“未加入分组”。

地区按来源的市场／版本划分，与个人阅读范围独立取交集。迁移不自动订阅任何频道，也不改写历史来源网址或名称。来源目录 GET 不写数据库；FDA 候选保留但不开放新增订阅或采集。

IT之家、爱范儿只接收新能源关键词匹配项。医疗媒体、期刊及指定受限能源来源只使用标题、摘要和链接，既有正文也不能通过详情或正文队列绕过策略。医疗资讯与 AI 回答显示“新闻资讯，不构成医疗建议”并附实际原文链接。

## 验证

| 命令或检查 | 结果 |
| --- | --- |
| `PYTHONPATH=backend:crawler pytest`（隔离 Python 环境） | 实现阶段全套 1252 项通过；随后新增迁移和最终序列化改动专项 76 项通过 |
| `PYTHONPATH=backend:crawler pytest backend/api/tests/test_channels.py backend/api/tests/test_channel_migration.py backend/api/tests/test_sector_feeds.py backend/api/tests/test_sector_migration.py backend/api/tests/test_news_summary.py -q` | 提交前复核 88 项通过 |
| `npm --prefix frontend run test:run` | 511 项通过，71 个测试文件 |
| `npm --prefix frontend run typecheck`、`npm --prefix frontend run lint` | 实现阶段及提交前复核均通过 |
| `npm --prefix frontend run build` | 本地部署产物构建通过 |
| `git diff --check` | 通过 |
| 独立数据库端到端浏览器验收 | 分组／地区条件、目录 URL 恢复、医疗提示、真实原文链接、正文拒绝、移动端及搜索交集通过 |
| 本地部署验收 | SQLite 在线备份后更新镜像，0039–0042 已应用；四个服务健康；国内目录 5 个、国际目录 51 个；非法地区返回 400；移动端浏览器无页面异常 |
| 新增 RSS 实际采集 | 检查 25 个启用源，17 个返回已入库项目，共 605 次项目提交；此数字包含更新，不表示 605 篇独立新增文章 |

## 限制与后续

FDA 当前 RSS 链接待验证，保持停用。实际采集存在 robots、HTTP 403 和请求预算延后：The Lancet、NEJM、MedCity 本轮被阻止，其他延后来源由现有采集调度处理；不能据目录可见推断所有来源均采集成功。不绕过付费墙、robots 或安全 URL 校验。

用户决定暂时跳过既有“链接待核验”问题，本次不修改相关网络安全规则。不接入 openFDA、PubMed 或 ClinicalTrials 数据 API，不新增自定义 RSS、嵌套组、通知或共享组。

本地运行产生的 `backend/db.sqlite3` 变更保留在工作区，明确排除提交；构建产物、备份、临时验收用户及截图不纳入仓库。

## 实际文件清单

- `README.md`
- `backend/api/management/commands/crawl.py`
- `backend/api/models.py`
- `backend/api/serializers.py`
- `backend/api/services/article_fetcher/core.py`
- `backend/api/services/feed_support.py`
- `backend/api/services/full_content_status.py`
- `backend/api/services/news_ingestion.py`
- `backend/api/services/research/agent_loop.py`
- `backend/api/services/research/tools.py`
- `backend/api/services/source_dates.py`
- `backend/api/services/source_policy.py`
- `backend/api/tests/test_backfill_scrapy_command.py`
- `backend/api/tests/test_chat_context.py`
- `backend/api/tests/test_fetch_full.py`
- `backend/api/tests/test_fetch_full_command.py`
- `backend/api/tests/test_full_content_status_service.py`
- `backend/api/tests/test_full_content_worker.py`
- `backend/api/tests/test_ingestion_content_consumers.py`
- `backend/api/tests/test_ingestion_metrics.py`
- `backend/api/tests/test_live_attach.py`
- `backend/api/tests/test_news_ingestion.py`
- `backend/api/tests/test_news_summary.py`
- `backend/api/tests/test_request_budget.py`
- `backend/api/tests/test_structured_article_providers.py`
- `backend/api/urls.py`
- `backend/api/views.py`
- `crawler/news_crawler/category_map.py`
- `crawler/news_crawler/pipelines.py`
- `frontend/src/App.tsx`
- `frontend/src/components/NewsCard.tsx`
- `frontend/src/components/NewsChatAssistant.tsx`
- `frontend/src/components/chat/ChatMessageList.tsx`
- `frontend/src/components/chat/LazyNewsChatAssistant.tsx`
- `frontend/src/components/news-detail/FullContentFetchStatus.jsx`
- `frontend/src/components/research/ResearchMessageList.tsx`
- `frontend/src/context/AuthContext.tsx`
- `frontend/src/hooks/researchTask.ts`
- `frontend/src/hooks/useResearch.ts`
- `frontend/src/pages/LocalSearch.tsx`
- `frontend/src/pages/NewsDetail.tsx`
- `frontend/src/pages/NewsList.tsx`
- `frontend/src/services/api.ts`
- `frontend/src/services/newsQueries.ts`
- `frontend/src/types/news.ts`
- `frontend/src/types/research.ts`
- `frontend/tests/components/chat/ChatMessageList.test.jsx`
- `frontend/tests/pages/NewsDetail.navigation.test.jsx`
- `frontend/tests/pages/NewsList.auth.test.jsx`
- `frontend/tests/pages/NewsList.test.jsx`
- `tests/backend/test_api_views.py`
- `tests/backend/test_full_content_worker_process.py`
- `tests/crawler/test_source_matrix.py`
- `tests/crawler/test_source_retirement.py`
- `backend/api/channel_views.py`
- `backend/api/management/commands/sync_channel_catalog.py`
- `backend/api/migrations/0039_personal_channels.py`
- `backend/api/migrations/0040_initialize_channel_catalog.py`
- `backend/api/migrations/0041_source_region.py`
- `backend/api/migrations/0042_sector_channels.py`
- `backend/api/services/channel_articles.py`
- `backend/api/services/channel_catalog.py`
- `backend/api/services/energy_keywords.py`
- `backend/api/services/sector_feeds.py`
- `backend/api/tests/test_channel_migration.py`
- `backend/api/tests/test_channels.py`
- `backend/api/tests/test_sector_feeds.py`
- `backend/api/tests/test_sector_migration.py`
- `crawler/news_crawler/spiders/sector_feeds_spider.py`
- `frontend/src/components/ChannelConfirmationDialog.tsx`
- `frontend/src/components/NewsScopeBar.tsx`
- `frontend/src/components/RegionFilter.tsx`
- `frontend/src/hooks/useNewsScope.ts`
- `frontend/src/pages/ChannelsPage.tsx`
- `frontend/src/services/channelQueries.ts`
- `frontend/src/types/channels.ts`
- `frontend/tests/pages/Channels.integration.test.jsx`
