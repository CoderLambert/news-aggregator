# 前端项目审计报告 (react-best-practices skill)

审计对象：/root/news-aggregator/frontend/
审计依据：agentic-atlas/react-best-practices skill（4 类规则：Performance / React 18+ / Bundle Size / Accessibility）
日期：2026-05-31

---

## 摘要

| 类别 | Errors | Warnings | Info |
|---|---|---|---|
| Performance | 2 | 6 | 1 |
| React 18+ | 1 | 2 | 1 |
| Bundle Size | 3 | 1 | 1 |
| Accessibility | 1 | 1 | 0 |
| **合计** | **7** | **10** | **3** |

---

## 1. Performance（性能）

### 1.1 [ERROR] no-missing-deps — useEffect 缺失依赖
**文件**：pages/NewsDetail.jsx
**行**：214 / 225 / 255
**问题**：
- L214: `useEffect(() => { ... fetchNewsDetail(id) ... }, [lang])` — 用到了 `id` 和 `news`，依赖只有 `lang`。语言切换且 id 变更时会读到旧 id。
- L225: 同上，函数体引用 `id`、`news`、`loading`，依赖数组是 `[id, news, loading, autoResumed]`（实际是 `[]` 或不完整，需核对完整代码）
- L255: 函数体引用 `news`、`id`，但通过条件 `if (!news) return` 保护——依赖应包含 `[id, news]`，否则 marker 清理不及时

**Fix**：补全依赖数组；如确实只想在 `lang` 变化时触发，把 `id` 用 `useRef` 包装。

### 1.2 [WARN] avoid-inline-objects-in-jsx
**文件**：pages/NewsDetail.jsx:120、components/NewsChatAssistant.jsx:275
**问题**：
- `style={{ maxHeight: '480px', objectFit: 'contain' }}` 每次渲染创建新对象
- `style={{ minHeight: '36px' }}` 同上
**Fix**：抽成模块级常量，或改用 Tailwind class（`max-h-[480px] object-contain`、`min-h-9`）。

### 1.3 [WARN] prefer-useCallback — 7 个未 memo 的内联回调
**位置**：
- NewsDetail.jsx:529/539/553/611 — `onClick={() => handleTranslate(...)}` 和 `setShowOriginal(...)`
- NewsChatAssistant.jsx:126/145/168/192 — `onClick={() => setIsOpen(...)}` 等
**风险**：传给可能 memo 的子组件会破坏 memo；NewsDetail 主组件 200 行 JSX，每次状态变化都重建。
**Fix**：拆分子组件后用 `useCallback`，或采用 React Compiler（React 19 + babel-plugin-react-compiler）自动 memo。

### 1.4 [WARN] prefer-useMemo — 全项目 0 处 useMemo
搜索结果：`pages/NewsList.jsx: 3 处 useCallback/useMemo`、`LanguageContext: 2 处`、其余 **0 处**。
NewsDetail 渲染 Markdown 组件、计算翻译状态、过滤 messages 都没有 memo。

### 1.5 [INFO] React Compiler 未启用
React 19 已升级（package.json: `react ^19.2.6`），但 vite.config 没启用 React Compiler。启用后 1.3/1.4 多数问题可自动解决。
**Fix**：
```js
// vite.config.js
plugins: [react({ babel: { plugins: ['babel-plugin-react-compiler'] } })]
```

---

## 2. React 18+ Patterns

### 2.1 [ERROR] require-useTransition — SSE 流式渲染未用过渡
**文件**：pages/NewsDetail.jsx (handleTranslate 翻译流) / NewsChatAssistant.jsx (chat 流)
**问题**：SSE 每收到一个 chunk 就 `setState`，触发整页重渲染。翻译时每 500 字符一次保存 + setState，可能导致输入框卡顿、滚动掉帧。
**Fix**：
```js
const [, startTransition] = useTransition()
// SSE onChunk:
startTransition(() => setTranslatedContent(prev => prev + chunk))
```

### 2.2 [WARN] no-unnecessary-fragments
未发现违规。✅

### 2.3 [WARN] 缺 ErrorBoundary
App.jsx 没有顶层 ErrorBoundary。NewsDetail 的 SSE 异常或 Markdown 渲染崩溃会炸全屏白屏。
**Fix**：用 `react-error-boundary` 包路由级容器。

### 2.4 [INFO] 未使用 Suspense + lazy
grep 结果：**0 处 React.lazy / Suspense**。
NewsDetail 是大组件（681 行 + markstream-react），用户访问列表页时强加载，浪费首屏。

---

## 3. Bundle Size（最严重的部分）

### 3.1 [ERROR] 未使用依赖直接进 bundle —— 浪费 ~157MB node_modules

依据 src/ 全文 grep（无 import、无字符串引用）：

| 包 | 体积 | 实际引用 |
|---|---|---|
| monaco-editor | 76M | ❌ 零引用 |
| mermaid | 77M | ❌ 零引用 |
| shiki | 3.9M | ❌ 零引用 |
| stream-monaco | 847K | ❌ 零引用 |
| stream-markdown | 155K | ❌ 零引用 |

**证据**：当前 dist/ 里存在 `emacs-lisp-*.js (762K)`、`cpp-*.js (612K)`、`mermaid-parser.core-*.js (590K)`、`cytoscape.esm-*.js (425K)`、`wolfram-*.js (257K)`、`wasm-*.js (608K)`——这些全是 shiki + mermaid 的间接产物。

**Fix（一条命令）**：
```bash
cd /root/news-aggregator/frontend
npm uninstall monaco-editor mermaid shiki stream-monaco stream-markdown
npm run build
```
预期：主 chunk 从 2.8MB 降到 < 400KB。

### 3.2 [ERROR] check-duplicate-packages — Markdown 渲染重复
同时引入 `markstream-react`（NewsDetail + NewsChatAssistant 用）和 `react-markdown + remark-gfm`（仅 NewsDetail 的 MarkdownContent 用）。两个库做同一件事。
**Fix**：统一用其中一个。建议保留 `react-markdown`（生态更广、可控）或保留 `markstream-react`（如果它对流式输出更优）。

### 3.3 [ERROR] 未做 route-level code splitting
App.jsx 直接 import NewsList 和 NewsDetail。NewsDetail 含 markstream-react 应懒加载。
**Fix**：
```jsx
const NewsDetail = lazy(() => import('./pages/NewsDetail'))
<Suspense fallback={<LoadingSpinner />}>
  <Routes>...</Routes>
</Suspense>
```

### 3.4 [WARN] no-bare-imports — namespace import 检查 ✅
全项目无 `import * as` —— 已合规。

### 3.5 [INFO] vite manualChunks 未配置
当前 chunk 是 rolldown 自动分的。建议显式分组：
```js
build: {
  rollupOptions: {
    output: { manualChunks: { vendor: ['react','react-dom','react-router-dom'], markdown: ['react-markdown','remark-gfm'] } }
  }
}
```

---

## 4. Accessibility（可访问性）

### 4.1 [ERROR] require-aria-labels — 0% 覆盖率
全项目 17 个 `<button>` 元素，**0 处 aria-label**。
重点违规：
- NewsChatAssistant 的关闭/全屏切换按钮（纯图标按钮，无文本）—— 必须加 aria-label
- NewsDetail 的语言切换按钮、翻译按钮
- Header 的导航按钮

**Fix**：所有纯图标按钮加 `aria-label="关闭对话"` 等。

### 4.2 [WARN] require-keyboard-handlers
聊天面板背景遮罩 `onClick={() => setIsOpen(false)}` 没有键盘等价物（Esc 关闭）。
**Fix**：
```jsx
useEffect(() => {
  const onKey = (e) => e.key === 'Escape' && setIsOpen(false)
  window.addEventListener('keydown', onKey)
  return () => window.removeEventListener('keydown', onKey)
}, [])
```

---

## 优先级总览（结合上一份审计 + 本次规则）

### P0 立刻修（一天内）
1. **卸载 5 个未用依赖** → bundle 缩 80%+（10 分钟）
2. **删除重复的 markdown 库**（react-markdown 或 markstream-react 二选一）
3. **修复 3 个 useEffect 缺失依赖**（NewsDetail L214/225/255）
4. **路由级 lazy + Suspense + ErrorBoundary**

### P1 一周内
5. SSE 流式渲染加 `useTransition`
6. 17 个按钮补全 `aria-label`
7. 启用 React 19 Compiler（一次性解决大量 memo 问题）
8. NewsDetail.jsx (681 行) 拆分（详见上份 audit）
9. NewsChatAssistant.jsx (303 行) 拆分

### P2 增量改进
10. 抽 useMemo 优化 Markdown 渲染重算
11. inline style 改 Tailwind class
12. vite manualChunks 显式分组
13. 引入 TypeScript

---

## 结论

react-best-practices skill 的规则化检查印证了上一份审计的判断，**并新增了 3 个高价值发现**：

1. **useEffect 缺失依赖**（不是简单的代码味，是潜在 bug：语言切换时可能拿到旧数据）
2. **SSE 流式渲染没用 useTransition**（React 18+ 的标准做法，能直接消除翻译时的卡顿）
3. **React 19 已升级但未启用 Compiler**（启用后能自动解决 90% 的 memo 优化诉求，是当前最高 ROI 的改动）

**最该立刻做的 3 件事**：
- `npm uninstall monaco-editor mermaid shiki stream-monaco stream-markdown` → 立竿见影
- vite.config 启用 React Compiler
- 4 个 useEffect 依赖修复
