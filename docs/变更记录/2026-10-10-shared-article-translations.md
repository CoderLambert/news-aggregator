# 共享文章译文

- 日期：2026-10-10
- 分支：`main`
- 交付范围：为完整文章翻译增加站点共享副本，同时保留 ChatGPT 订阅译文的用户隔离。

## 变更目标

首次生成的完整公开文章译文可供其他读者复用，避免每位读者重复调用模型。个人账号仍可明确生成自己的译文，凭据和私有输出继续按账号隔离。

## 实际改动

| 文件或区域 | 模块 | 改动 |
| --- | --- | --- |
| `backend/api/models.py`、`backend/api/migrations/0026_shared_article_translations.py` | 数据模型 | 增加共享完整译文和数据库任务租约表，按文章、原文哈希、目标语言和提示版本建立唯一键。 |
| `backend/api/services/shared_translations.py` | 翻译服务 | 实现任务认领、租约续期、过期接管、原文校验、完整结果发布和等待 SSE。 |
| `backend/api/services/chatgpt_subscription.py`、`chatgpt_subscription_jobs.py`、`subscription_views.py`、`translation_jobs.py`、`llm_translator.py` | 后端任务与接口 | 私人翻译完成后复制完整结果到共享表；普通请求复用或等待共享任务；阻止截断或中断的 API 翻译进入共享存储。 |
| `backend/api/serializers.py`、`views.py`、`tts_service.py` | 详情、翻译与朗读 | 详情标明译文范围和来源；优先返回当前用户的私有译文，再回退到共享副本；朗读沿用相同选择规则。 |
| `backend/api/tests/test_shared_translations.py`、`test_chatgpt_subscription.py`、`test_live_attach.py` | 后端回归 | 覆盖跨用户复用、任务并发与过期接管、原文变化、失败结果、账号撤销及重新翻译。 |
| `frontend/src/components/news-detail/FullContentSection.tsx`、`src/hooks/useTranslation.ts`、`src/pages/NewsDetail.tsx`、`src/services/newsWorkflowApi.ts`、`src/types/news.ts` | 新闻详情页 | 展示共享/个人译文状态；共享任务等待时提示复用行为；在个人订阅可用时提供明确的个人重翻入口。 |
| `frontend/tests/components/news-detail/news-detail.test.jsx`、`tests/hooks/useTranslation.test.jsx`、`tests/pages/NewsDetail.navigation.test.jsx` | 前端回归 | 覆盖共享译文提示、等待状态、结果来源更新和首次失败后的重试行为。 |
| `docs/shared-article-translations.md`、`docs/chatgpt-subscription-oauth.md`、`docs/chinese-translation-tts-plan.md` | 设计与行为文档 | 记录共享副本的数据边界、兼容行为、任务约束及与订阅凭据隔离的关系。 |

## 关键实现

共享缓存键由新闻 ID、原文 SHA-256、目标语言和翻译版本组成。数据库唯一约束与租约令牌负责跨进程任务认领；工作线程定期续约，最长运行 30 分钟。只发布非空的完整结果，并在发布时再次核对原文哈希。已有共享结果保持首个有效版本；用户主动重翻保存个人版本，不覆盖共享结果。

详情读取优先选取当前用户和连接对应的私有结果，然后读取共享表；共享表不记录生成者或订阅连接。历史字段保留兼容读取，不自动导入旧个人译文。TTS 使用同一优先顺序。

## 行为与兼容性

新闻详情增加 `full_content_zh_scope` 和 `full_translation_personal_available`。完成 SSE 返回译文范围及提供方；共享任务等待事件不暴露其他用户的流式片段。迁移新增两张表，不修改历史译文数据或凭据。

## 验证

| 命令或检查 | 结果 |
| --- | --- |
| `./venv/bin/python -m pytest api/tests/test_shared_translations.py api/tests/test_chatgpt_subscription.py api/tests/test_live_attach.py -q`（在 `backend/`） | 通过，66 项。 |
| `npm run test:run -- tests/components/news-detail/news-detail.test.jsx tests/hooks/useTranslation.test.jsx tests/pages/NewsDetail.navigation.test.jsx`（在 `frontend/`） | 通过，31 项。 |
| `npm run typecheck`（在 `frontend/`） | 通过。 |
| `npm run lint`（在 `frontend/`） | 通过。 |
| `./venv/bin/python manage.py makemigrations --check --dry-run && ./venv/bin/python manage.py check`（在 `backend/`） | 通过；无未生成迁移，Django 检查无问题。 |
| `git diff --check` | 通过。 |

## 限制与后续

共享等待会占用一个 WSGI 请求线程；高并发部署需评估线程数或改用异步等待。供应商调用在进程崩溃后的重试仍可能重复计费，不能保证上游恰好一次计费。工作区的 `backend/db.sqlite3` 本地数据库变更以及 `docs/plans/` 下两份部署计划/提示词不属于本次功能交付，未纳入提交。
