const LIGHT_THEME = 'github-light'
const DARK_THEME = 'github-dark'

const LANGUAGE_ALIASES = {
  js: 'javascript',
  mjs: 'javascript',
  cjs: 'javascript',
  ts: 'typescript',
  py: 'python',
  rb: 'ruby',
  sh: 'bash',
  shell: 'bash',
  zsh: 'bash',
  yml: 'yaml',
  md: 'markdown',
  plaintext: 'text',
  txt: 'text',
}

const LANGUAGE_LOADERS = {
  bash: () => import('@shikijs/langs/bash'),
  css: () => import('@shikijs/langs/css'),
  diff: () => import('@shikijs/langs/diff'),
  dockerfile: () => import('@shikijs/langs/dockerfile'),
  go: () => import('@shikijs/langs/go'),
  graphql: () => import('@shikijs/langs/graphql'),
  html: () => import('@shikijs/langs/html'),
  java: () => import('@shikijs/langs/java'),
  javascript: () => import('@shikijs/langs/javascript'),
  json: () => import('@shikijs/langs/json'),
  jsx: () => import('@shikijs/langs/jsx'),
  markdown: () => import('@shikijs/langs/markdown'),
  python: () => import('@shikijs/langs/python'),
  ruby: () => import('@shikijs/langs/ruby'),
  rust: () => import('@shikijs/langs/rust'),
  sql: () => import('@shikijs/langs/sql'),
  tsx: () => import('@shikijs/langs/tsx'),
  typescript: () => import('@shikijs/langs/typescript'),
  xml: () => import('@shikijs/langs/xml'),
  yaml: () => import('@shikijs/langs/yaml'),
}

const loadedLanguages = new Set(['text'])
const languagePromises = new Map()
let highlighterPromise

export function normalizeShikiLanguage(language) {
  const key = String(language || '').trim().toLowerCase()
  return LANGUAGE_ALIASES[key] || key || 'text'
}

async function getHighlighter() {
  highlighterPromise ||= Promise.all([
    import('@shikijs/core'),
    import('@shikijs/engine-javascript'),
    import('@shikijs/themes/github-light'),
    import('@shikijs/themes/github-dark'),
  ]).then(([core, engine, lightTheme, darkTheme]) =>
    core.createHighlighterCore({
      themes: [lightTheme.default, darkTheme.default],
      langs: [],
      engine: engine.createJavaScriptRegexEngine(),
    })
  )
  return highlighterPromise
}

async function ensureLanguage(highlighter, language) {
  const lang = normalizeShikiLanguage(language)
  if (loadedLanguages.has(lang)) return lang

  const loadLanguage = LANGUAGE_LOADERS[lang]
  if (!loadLanguage) return 'text'

  if (!languagePromises.has(lang)) {
    languagePromises.set(
      lang,
      loadLanguage().then(async (module) => {
        await highlighter.loadLanguage(...module.default)
        loadedLanguages.add(lang)
      })
    )
  }

  await languagePromises.get(lang)
  return lang
}

function transformerLineNumbers() {
  return {
    name: 'line-numbers',
    line(node, line) {
      node.properties ||= {}
      node.properties['data-line'] = String(line)
    },
  }
}

export async function highlightCode(code, language) {
  const highlighter = await getHighlighter()
  const lang = await ensureLanguage(highlighter, language)

  return highlighter.codeToHtml(code, {
    lang,
    themes: {
      light: LIGHT_THEME,
      dark: DARK_THEME,
    },
    defaultColor: false,
    transformers: [transformerLineNumbers()],
  })
}
