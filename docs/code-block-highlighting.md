# Markdown 代码块语法高亮实现文档

## 概述

新闻详情页使用 `markstream-react` 的 `NodeRenderer` 渲染 Markdown 内容。代码块高亮通过 **Monaco Editor + Shiki** 实现：

- **Shiki**：VS Code 同款的语法分析引擎，生成 TextMate Token
- **Monaco Editor**：VS Code 的编辑器内核，负责渲染和交互
- **stream-monaco**：桥接层，将 Shiki 的主题和语法分析注入 Monaco

## 依赖关系

```
markstream-react (0.0.49)
  └── peerDependency: stream-monaco (>=0.0.40)
        ├── peerDependency: monaco-editor (>=0.52.2 <0.56.0)
        ├── dependency: @shikijs/monaco (^3.23.0)
        └── dependency: shiki (^3.23.0)
```

### 新增的 3 个包

| 包名 | 版本 | 作用 |
|---|---|---|
| `monaco-editor` | 0.55.1 | Monaco 编辑器内核（渲染引擎） |
| `stream-monaco` | 0.0.40 | Monaco + Shiki 的流式高亮桥接层 |
| `@shikijs/monaco` | 3.23.0 | Shiki 到 Monaco 的语法高亮适配（自动安装） |

## 实现原理

### 加载流程

```
1. NodeRenderer 挂载
   └── 检测页面中是否有 code_block 节点

2. 懒加载 stream-monaco（requestIdleCallback）
   └── import("stream-monaco")
   └── ensureMonacoWorkers() 自动配置 Monaco Worker 环境

3. useMonaco() 初始化
   └── registerMonacoThemes() 注册 vitesse-light / vitesse-dark
   └── shikiToMonaco() 将 Shiki TextMate 语法注入 Monaco

4. createEditor() 创建只读编辑器实例
   └── 应用主题（darkTheme / lightTheme）
   └── 应用 monacoOptions 配置
   └── 渲染语法高亮代码
```

### 主题系统

`themes` 数组是关键——它告诉 Shiki 需要预注册哪些主题到 Monaco 中：

```
themes: ['vitesse-dark', 'vitesse-light']
  → registerMonacoThemes() 调用
    → shiki.getTheme('vitesse-dark') → monaco.editor.defineTheme()
    → shiki.getTheme('vitesse-light') → monaco.editor.defineTheme()
```

如果只传 `darkTheme` / `lightTheme` 而不传 `themes`，主题不会被注册，高亮失效。

## 代码实现

### NewsDetail.jsx 完整配置

```jsx
import NodeRenderer from 'markstream-react'
import 'markstream-react/index.css'

<NodeRenderer
  content={news.content || ''}
  // ─── 代码块 UI 配置 ───
  codeBlockProps={{
    showHeader: true,           // 显示语言标签栏
    showCopyButton: true,       // 一键复制按钮
    showCollapseButton: false,  // 折叠按钮
    showFontSizeButtons: false, // 字号控制
    showTooltips: true,         // 悬停提示
  }}
  // ─── 主题 + Monaco 配置 ───
  codeBlockThemes={{
    // ⚠️ themes 数组必须传入，否则主题不会被 Shiki 注册
    themes: ['vitesse-dark', 'vitesse-light'],
    darkTheme: 'vitesse-dark',
    lightTheme: 'vitesse-light',
    monacoOptions: {
      fontSize: 14,
      fontFamily: "'JetBrains Mono', 'Fira Code', 'Cascadia Code', 'Source Code Pro', Menlo, Consolas, monospace",
      padding: { top: 12, bottom: 12 },
      lineNumbers: 'on',
      wordWrap: 'on',
      minimap: { enabled: false },
      scrollbar: { vertical: 'hidden', horizontal: 'hidden' },
      scrollBeyondLastLine: false,
      overviewRulerLanes: 0,
      hideCursorInOverviewRuler: true,
      renderLineHighlight: 'none',
      renderLineHighlightOnlyWhenFocus: true,
      contextmenu: false,
      readOnly: true,
      domReadOnly: true,
      mouseWheelZoom: false,
      smoothScrolling: true,
      cursorBlinking: 'blink',
      cursorSmoothCaretAnimation: 'on',
    },
  }}
/>
```

## 可用主题列表

`stream-monaco` 内置以下 Shiki 主题（部分常用）：

### 暗色主题
`vitesse-dark`, `one-dark-pro`, `material-theme-darker`, `github-dark`, `dracula-soft`, `catppuccin-mocha`, `catppuccin-macchiato`, `tokyo-night`, `monokai`, `nord`, `rose-pine`, `min-dark`, `poimandres`, `slack-dark`

### 亮色主题
`vitesse-light`, `one-light`, `material-theme-lighter`, `github-light`, `catppuccin-latte`, `min-light`, `rose-pine-dawn`, `snazzy-light`, `material-theme-lightest`

## Monaco Options 说明

### 展示类

| 选项 | 类型 | 说明 |
|---|---|---|
| `fontSize` | number | 字号 |
| `fontFamily` | string | 等宽字体栈 |
| `padding` | `{top, bottom}` | 编辑器内边距 |
| `lineNumbers` | `'on' \| 'off'` | 行号显示 |
| `wordWrap` | `'on' \| 'off'` | 自动换行 |

### 隐藏冗余元素（新闻展示场景）

| 选项 | 值 | 说明 |
|---|---|---|
| `minap.enabled` | false | 隐藏代码地图 |
| `scrollbar` | `{vertical: 'hidden'}` | 隐藏滚动条 |
| `scrollBeyondLastLine` | false | 禁止滚过末尾 |
| `overviewRulerLanes` | 0 | 隐藏概览标尺 |
| `contextmenu` | false | 禁用右键菜单 |

### 只读模式

| 选项 | 值 | 说明 |
|---|---|---|
| `readOnly` | true | Monaco 只读 |
| `domReadOnly` | true | DOM 层只读 |

### 视觉细节

| 选项 | 值 | 说明 |
|---|---|---|
| `renderLineHighlight` | `'none'` | 不突出当前行 |
| `cursorBlinking` | `'blink'` | 光标闪烁 |
| `smoothScrolling` | true | 平滑滚动 |

## 常见问题

### 代码块没有高亮

1. 检查 `stream-monaco` 和 `monaco-editor` 是否已安装
2. 确认 `codeBlockThemes.themes` 数组已传入主题名
3. 打开浏览器控制台，查看是否有 Monaco Worker 加载失败

### Monaco Worker 404

Vite 需要能正确解析 Monaco Worker 路径。`stream-monaco` 的 `ensureMonacoWorkers()` 会自动处理，但某些构建配置可能需要额外设置。常见解决方案：

```js
// vite.config.js
export default defineConfig({
  optimizeDeps: {
    exclude: ['monaco-editor'],  // 让 Monaco 走 ESM 路径
    include: ['@shikijs/monaco'],
  },
})
```

### 暗色/亮色不切换

通过 `isDark` prop 控制：

```jsx
<NodeRenderer
  content={news.content}
  isDark={true}  // 切换暗色模式
/>
```

## 与 Vue 版本对比

| Vue 语法 | React (markstream-react) 语法 |
|---|---|
| `:is-dark="isDark"` | `isDark={isDark}` |
| `:code-block-props="{...}"` | `codeBlockProps={{...}}` |
| `:code-block-themes="{...}"` | `codeBlockThemes={{...}}` |
| `:content="doc"` | `content={doc}` |

## 文件变更清单

```
frontend/package.json                  # 新增 monaco-editor, stream-monaco
frontend/src/pages/NewsDetail.jsx      # NodeRenderer 添加高亮配置
```
