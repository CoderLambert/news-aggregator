# 阅读工作区主题、提交保护与正文权限

日期：2026-10-14。交付范围为用户授权的 NewsHub 本地修复；包含分组提交保护、首页/搜索/文章主题统一和独立正文权限。

## 实际变更

| 模块 | 文件或目录 | 行为 |
| --- | --- | --- |
| 分组工作区 | `frontend/src/pages/GroupWorkspace.tsx`、`frontend/tests/pages/GroupWorkspace.submission.test.tsx` | 同一事件内锁住提交，阻止请求期间关闭和重复提交；失败保留输入并说明服务器结果未确认 |
| 主题 | `frontend/src/components/news-detail/`、`NewsCard.tsx`、`NewsFilters.tsx`、`SearchBar.tsx`、`CategoryFilter.tsx`、`SourceFilter.tsx`、`frontend/src/pages/NewsDetail.tsx`、`NewsList.tsx`、`LocalSearch.tsx` | 标题/正文、卡片、提示、按钮和徽章共用现有主题变量，主操作统一绿色 |
| 正文权限 | `backend/api/models.py`、`migrations/0044_article_body_access.py`、`services/body_access.py`、`serializers.py`、`views.py` | `api.view_article_body` 可授予用户/用户组，超级管理员默认具备；已有有效正文直接读 |
| 持久化抓取 | `services/article_content.py`、`full_content_status.py`、`full_content_worker.py`、`article_fetcher/core.py`、`source_policy.py` | 缺失正文按权限请求，记录请求者，执行与持久化前核对权限，复用重复任务 |
| 前端正文状态 | `frontend/src/types/news.ts`、`hooks/useFullArticle.ts`、`news-detail/FullContentFetchStatus.jsx`、`pages/NewsDetail.tsx` | 使用服务端权限与可获取状态，旧 unsupported 状态不遮蔽新的失败提示 |
| 回归与说明 | `backend/api/tests/test_body_access.py`、`frontend/tests/components/news-detail/BodyAccess.test.jsx`、`frontend/tests/pages/NewsDetail.navigation.test.jsx`、`MarkdownContent.source-list.test.jsx`、`docs/features/smart-workspace/ARTICLE-BODY-ACCESS.md` | 验证权限隔离、授权/撤权、任务复用、页面失败反馈并说明发布前提 |

## 边界与兼容

没有权限的账号继续遵循现有频道策略。新权限放开仅摘要频道的站内显示和按需尝试；不绕过明确停采来源、未登记来源、私网/非法链接、文章类型限制、真实性校验、来源限流、有限重试或站点只读模式。客户端参数不能授予权限。修改文章身份时清除旧请求者授权。列表只在授权时返回正文覆盖标记，抓取资格仅在详情响应返回，继续满足现有摘要载荷预算和固定查询数。

分组请求失败或超时不等于后台取消，因此提示先刷新确认结果后决定重试。

发布必须先备份数据库，执行0044迁移，再更新前后端并按现有发布文档启用正文抓取worker；channel_worker不承担正文抓取。

## 验证

- 最终前端78文件545测试、TypeScript、ESLint、Vite构建及git diff --check通过。
- 后端正文/权限/队列/安全相关103测试、来源策略44测试通过；Django check与迁移一致性检查通过。
- 后端完整回归：`pytest -q tests/ backend/api/tests/ scripts/deploy/tests/` 在隔离测试数据库与宿主权限下1618项通过（98.15秒）。沙箱内异步线程唤醒会停滞；同一crawler专项宿主权限10项通过。另有摘要载荷预算回归与权限专项45项通过；没有放宽原有测试阈值。
- Chrome实际验收：深浅色首页/搜索/文章；有权限时直接显示已有人工正文；缺失正文服务不可用时明确报错并保留摘要/重试。隔离测试数据库迁移前已备份并验证恢复。
- 分组专项实际验收：保存时快速Escape和重复Enter不关闭弹窗、不重复创建；失败保留输入，恢复后重试成功。

## 未验证内容

真实来源正文抓取成功、真实付费模型和生产部署未执行。权限不保证来源可获取，不将本地服务不可用的失败反馈记为抓取成功。本次提交与合并不包含任何生产部署或真实凭据配置。
