# 前端项目审计报告

审计对象：/root/news-aggregator/frontend/
代码规模：约 1661 行 (src/)，14 个文件
日期：2026-05-31

---

## 总体结论

**需要重构，但属于"针对性重构"而非"推倒重来"。**

项目骨架合理（Vite + React + Tailwind + react-router 标准 SPA），但有 3 个明显的代码债：
1. NewsDetail.jsx 上帝组件（681 行 / 16 hook 调用 / 7 个 useState 集中在主组件）
2. 依赖严重冗余（76M monaco + 77M mermaid 完全未使用，但被打进 bundle）
3. API 层只完成一半（services/api.js 存在但 chat/translate 仍直接 fetch）

按 P0/P1/P2 优先级共 11 项，预计 1-2 天可完成。

---

## P0 - 必须立刻修（影响包体积/可维护性硬伤）

### 1. 卸载未使用的重量级依赖（节省 ~157MB node_modules，bundle 应能从 2.8MB 降到 <500KB）

实际代码 grep 验证：以下 8 个依赖在 src/ 里**零引用**：
- monaco-editor (76M) ❌
- mermaid (77M) ❌
- stream-monaco (847K) ❌
- stream-markdown (155K) ❌
- shiki (3.9M) ❌

实际使用的只有：markstream-react、react-markdown、remark-gfm。

动作：
```bash
cd /root/news-aggregator/frontend
npm uninstall monaco-editor mermaid stream-monaco stream-markdown shiki
npm run build  # 验证 chunk 大小
```

之前 build 警告 `dist-C2_jK7vH.js 2,861.96 kB` 几乎全是这几个未用库。

### 2. 修复 API 层散落（统一收口到 services/api.js）

services/api.js 已经定义了 3 个 axios 实例和 6 个导出函数，但实际还有 4 处直连 fetch：

| 位置 | 接口 | 应迁移为 |
|---|---|---|
| NewsChatAssistant.jsx:19 | GET /api/news/{id}/chat/ | `chatHistory(id)` |
| NewsChatAssistant.jsx:46 | DELETE /api/news/{id}/chat/ | `clearChat(id)` |
| NewsChatAssistant.jsx:70 | POST /api/news/{id}/chat/ (SSE) | `chatStream(id, body)` |
| NewsDetail.jsx:299 | POST /api/news/{id}/translate/ (SSE) | `translateStream(id, body)` |

SSE 接口因为要读 ReadableStream 不能直接 axios，但应在 api.js 里封装 `fetch + 流式解析` 的工具函数，让组件只调 `chatStream(id).onChunk(...)`，不再关心 URL/header/parser。

### 3. NewsDetail.jsx 上帝组件拆分（681 行 → 主组件 < 200 行）

当前主组件（行 192-681）承担：
- 新闻数据加载（news/loading/error）
- 全文抓取（articleLoading/articleError + handleFetchFullArticle）
- 翻译流（translating/translateError/translationProgress + handleTranslate，SSE 解析 ~100 行）
- 中英切换显示
- 4 个 useEffect 的副作用编排
- JSX 渲染（200+ 行）

拆分方案：
```
pages/NewsDetail.jsx                # 主组件，只负责组合，目标 < 180 行
├── hooks/
│   ├── useNewsDetail.js            # 数据加载状态机
│   ├── useArticleFetch.js          # 全文抓取
│   └── useTranslateStream.js       # 翻译 SSE（含进度）
└── components/news-detail/
    ├── MarkdownContent.jsx         # 已在文件内部，提出来 (~120 行)
    ├── TranslationStatus.jsx       # 已在文件内部，提出来 (~60 行)
    ├── ArticleHeader.jsx           # 标题/来源/日期/分类
    ├── ArticleActions.jsx          # 抓全文/重新翻译按钮
    └── ArticleBody.jsx             # 正文+译文切换
```

---

## P1 - 应该尽快修（影响开发体验/扩展性）

### 4. 缺失的目录约定

当前 src/ 只有：components/、pages/、services/、context/、assets/
应新增：
- `src/hooks/` — 业务 hook（useNewsDetail、useTranslateStream、useChatStream...）
- `src/utils/` — 纯函数（如 SSE 解析、内容清理、日期格式化）
- `src/constants/` — 枚举/常量（API 路径前缀、状态码、语言 key 等）

`LANG_KEY` 现在从 context 文件 export 给 api.js 用，这是反向依赖，应迁到 `constants/`。

### 5. NewsChatAssistant.jsx 拆分（303 行 → 主 ~120 行）

11 个 hook 调用，混合了：会话加载、SSE 流、面板开关、滚动控制、清空操作。

```
components/chat/
├── NewsChatAssistant.jsx     # 面板容器+开关
├── ChatMessageList.jsx       # 消息列表+自动滚动
├── ChatInput.jsx             # 输入框+发送
└── ../hooks/useChatStream.js # SSE 流式+会话状态
```

### 6. 路径别名 @/

Vite 加 `resolve.alias`：`{ '@': '/src' }`，避免 `../../services/api` 这种深路径。

### 7. 引入 TypeScript（用户偏好已记录）

新文件全部用 .tsx/.ts；存量文件渐进迁移。需要：
- `npm i -D typescript @types/node`
- `tsconfig.json`（target ES2022，jsx react-jsx，strict true）
- vite-plugin 已自带 TS 支持，无需额外配置

### 8. ErrorBoundary + Suspense

App.jsx 只有 BrowserRouter + 直接挂载页面。应加：
- 顶层 `<ErrorBoundary>` 防止 NewsDetail SSE 异常炸全屏
- 路由级 lazy + Suspense（NewsDetail 是大组件，懒加载能让首屏 NewsList 更快）

---

## P2 - 长期优化（不紧急但有价值）

### 9. 单元测试基建（用户偏好已记录："功能开发先写单测"）

当前 0 测试。建议：
- Vitest + @testing-library/react + jsdom
- 优先覆盖：services/api.js、hooks/useTranslateStream（SSE 解析逻辑）、MarkdownContent 渲染

### 10. Prettier + lint-staged

eslint.config.js 已有，但没格式化器、没 pre-commit。建议加 `prettier + husky + lint-staged`。

### 11. Tailwind 重复 class 抽取

MarkdownContent 里每个标签都重复写 `break-words text-[15px] leading-[1.8] text-gray-700`。可在 `index.css` 用 `@layer components` 抽 `.prose-news h1` 等语义类。

---

## 重构推荐顺序（最小风险路径）

第 1 步（10 分钟，零风险）：卸载 5 个未用依赖 → 重新 build，验证 bundle 体积下降
第 2 步（30 分钟）：补齐 services/api.js，把 4 处直 fetch 迁过来
第 3 步（半天）：NewsDetail.jsx 拆分 → 建立 hooks/ 和 components/news-detail/ 目录
第 4 步（2 小时）：NewsChatAssistant.jsx 拆分
第 5 步（半天）：引入 TypeScript + 路径别名 + ErrorBoundary
第 6 步（按需）：单测、Prettier、Tailwind 抽类

每一步都可独立提交、独立验证，不必一次做完。
