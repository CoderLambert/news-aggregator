import { isValidElement, useEffect, useRef, useState } from 'react'
import type { CSSProperties, ReactNode } from 'react'
import ReactMarkdown from 'react-markdown'
import type { Components } from 'react-markdown'
import type { Element, ElementContent } from 'hast'
import type { Plugin } from 'unified'
import remarkGfm from 'remark-gfm'
import { Check, Copy, ExternalLink, Newspaper } from 'lucide-react'
import { Button } from '@/components/ui/button'
import MermaidBlock from './MermaidBlock'
import { highlightCode, normalizeShikiLanguage } from '@/lib/shiki'

const IMG_STYLE = { maxHeight: '480px', objectFit: 'contain' } satisfies CSSProperties
const MAX_HIGHLIGHT_CHARS = 80_000

type MarkdownNode = {
  type: string
  value?: string
  children?: MarkdownNode[]
}

function splitLegacySummaryParagraphs(node: MarkdownNode) {
  if (!node.children) return

  const children: MarkdownNode[] = []
  for (const child of node.children) {
    const [text] = child.children ?? []
    if (
      child.type === 'paragraph'
      && child.children?.length === 1
      && text?.type === 'text'
      && typeof text.value === 'string'
    ) {
      const paragraphs = text.value.split(/\u3000{2,}/).filter((part) => part.trim())
      if (paragraphs.length > 1) {
        children.push(...paragraphs.map((value) => ({
          ...child,
          children: [{ ...text, value }],
        })))
        continue
      }
    }

    splitLegacySummaryParagraphs(child)
    children.push(child)
  }
  node.children = children
}

// Historical Chinese feed summaries used repeated ideographic spaces as
// paragraph separators. Parse Markdown first, then split only plain-text
// paragraph nodes on the explicitly opted-in summary path. Inline code and
// code blocks remain opaque AST nodes; no Markdown source is rewritten.
const remarkLegacySummaryParagraphs: Plugin = () => (tree) => {
  splitLegacySummaryParagraphs(tree as MarkdownNode)
}

/**
 * extractCodeText — walks a `<pre>` element's children to recover the raw
 * source text. react-markdown hands us a children tree like:
 *   <pre><code className="language-js">{ "const x = 1\n" }</code></pre>
 * but the exact shape can vary (highlighter plugins, nested spans). We
 * just stringify the leaf text so the copy payload always matches what
 * the user actually sees on screen.
 */
function extractCodeText(node: ReactNode): string {
  if (node == null || typeof node === 'boolean') return ''
  if (typeof node === 'string' || typeof node === 'number') return String(node)
  if (Array.isArray(node)) return node.map(extractCodeText).join('')
  if (isValidElement<{ children?: ReactNode }>(node)) return extractCodeText(node.props.children)
  return ''
}

function extractLanguage(node: ReactNode): string {
  if (node == null || typeof node === 'boolean') return ''
  if (Array.isArray(node)) {
    for (const child of node) {
      const lang = extractLanguage(child)
      if (lang) return lang
    }
    return ''
  }

  const className = isValidElement<{ className?: string }>(node) ? node.props.className ?? '' : ''
  const match = String(className).match(/(?:^|\s)language-([^\s]+)/)
  return match?.[1] || ''
}

function isExplodedCodeBlock(code: string) {
  const lines = String(code || '').split('\n')
  const nonEmpty = lines.map((line) => line.trim()).filter(Boolean)
  if (nonEmpty.length < 8) return false

  const shortLines = nonEmpty.filter((line) => line.length <= 24 && !/\s{2,}/.test(line)).length
  const codeTokens = nonEmpty.filter((line) => /^(from|import|def|class|await|const|let|var|return|if|for|while|print|[{}()[\].,;:=]|#|\/\/)/.test(line)).length
  return shortLines / nonEmpty.length >= 0.72 && codeTokens >= 3
}

function inferExplodedLanguage(lines: string[]) {
  const tokens = lines.map((line) => line.trim()).filter(Boolean)
  const joined = ` ${tokens.join(' ')} `

  if (/\b(from|def|print|asyncio|True|False|None)\b/.test(joined)) return 'python'
  if (/\b(const|let|var|await|async|newPage|import)\b/.test(joined) || tokens.includes(';')) return 'javascript'
  return 'text'
}

function formatTokenLine(tokens: string[]) {
  let value = tokens.filter(Boolean).join(' ')
  value = value.replace(/\s+([,;:)\]}.])/g, '$1')
  value = value.replace(/\s+\(/g, '(')
  value = value.replace(/([([{.])\s+/g, '$1')
  value = value.replace(/\s*\.\s*/g, '.')
  value = value.replace(/\s*([=+*/<>-])\s*/g, ' $1 ')
  value = value.replace(/\s+,/g, ',')
  value = value.replace(/,([^\s)\]}])/g, ', $1')
  value = value.replace(/:([^\s])/g, ': $1')
  value = value.replace(/\s{2,}/g, ' ')
  return value.trim()
}

function splitExplodedLines(code: string) {
  return String(code || '').split('\n').map((line) => line.trim()).filter(Boolean)
}

function repairExplodedPython(code: string) {
  const tokens = splitExplodedLines(code)
  const statements = []

  for (let i = 0; i < tokens.length;) {
    const token = tokens[i]

    if (token === 'from' && tokens[i + 1] && tokens[i + 2] === 'import' && tokens[i + 3]) {
      statements.push(formatTokenLine(tokens.slice(i, i + 4)))
      i += 4
      continue
    }

    if (token === 'import' && tokens[i + 1]) {
      statements.push(formatTokenLine(tokens.slice(i, i + 2)))
      i += 2
      continue
    }

    if (token.startsWith('#')) {
      statements.push(token)
      i += 1
      continue
    }

    const current = []
    let depth = 0
    while (i < tokens.length) {
      const part = tokens[i]
      current.push(part)
      if (part === '(' || part === '[' || part === '{') depth += 1
      if (part === ')' || part === ']' || part === '}') depth = Math.max(0, depth - 1)
      i += 1

      if (depth === 0 && part === ')') break
      if (depth === 0 && i < tokens.length) {
        const next = tokens[i]
        const nextAfter = tokens[i + 1]
        if (['from', 'import', 'def', 'class', 'return', 'async', 'await'].includes(next)) break
        if (/^[A-Za-z_]\w*$/.test(next) && nextAfter === '=') break
      }
    }

    if (current.length) statements.push(formatTokenLine(current))
  }

  return statements.join('\n')
}

function repairExplodedJavaScript(code: string) {
  const tokens = splitExplodedLines(code)
  const statements = []

  for (let i = 0; i < tokens.length;) {
    const current = []
    let depth = 0
    while (i < tokens.length) {
      const part = tokens[i]
      current.push(part)
      if (part === '(' || part === '[' || part === '{') depth += 1
      if (part === ')' || part === ']' || part === '}') depth = Math.max(0, depth - 1)
      i += 1
      if (depth === 0 && part === ';') break
      if (depth === 0 && i < tokens.length && ['import', 'const', 'let', 'var', 'await', 'return'].includes(tokens[i])) break
    }
    if (current.length) statements.push(formatTokenLine(current))
  }

  return statements.join('\n')
}

function repairExplodedCodeBlock(code: string) {
  if (!isExplodedCodeBlock(code)) return code

  const language = inferExplodedLanguage(String(code).split('\n'))
  if (language === 'python') return repairExplodedPython(code)
  if (language === 'javascript') return repairExplodedJavaScript(code)
  return formatTokenLine(splitExplodedLines(code))
}

function inferCodeLanguage(code: string) {
  const value = String(code || '').trim()
  if (!value) return 'text'

  if ((value.startsWith('{') || value.startsWith('['))) {
    try {
      JSON.parse(value)
      return 'json'
    } catch {
      // Continue with other heuristics.
    }
  }

  if (/^\s*<(!doctype|html|head|body|div|span|script|style|[a-z][\w:-]*\s|\/[a-z][\w:-]*>)/i.test(value)) {
    return 'html'
  }

  if (/\b(SELECT|INSERT|UPDATE|DELETE|CREATE|ALTER|DROP)\b[\s\S]*\b(FROM|INTO|TABLE|WHERE|VALUES)\b/i.test(value)) {
    return 'sql'
  }

  if (/^\s*([\w.-]+:\s*[^\n]+\n){2,}/.test(value)) {
    return 'yaml'
  }

  if (/^\s*(from\s+[\w.]+\s+import\s+\w+|import\s+[\w.]+|def\s+\w+\s*\(|class\s+\w+[(:]|if\s+__name__\s*==|print\s*\()/m.test(value)) {
    return 'python'
  }

  if (/\b(interface|type)\s+\w+\s*[=<{]|:\s*(string|number|boolean|unknown|Record<|Promise<)|as\s+const\b/.test(value)) {
    return 'typescript'
  }

  if (/^\s*(import\s+.+\s+from\s+['"]|export\s+|const\s+\w+\s*=|let\s+\w+\s*=|var\s+\w+\s*=|function\s+\w+\s*\(|console\.log\s*\(|[\w.]+\s*=>)/m.test(value)) {
    return value.includes('</') || /<[A-Z][\w]*[\s>]/.test(value) ? 'jsx' : 'javascript'
  }

  if (/^\s*(#!\/?(?:usr\/bin\/env\s+)?(?:bash|sh|zsh)|(?:npm|pnpm|yarn|bun|pip|python|node|curl|wget|git|docker|kubectl)\s+)/m.test(value)) {
    return 'bash'
  }

  if (/^\s*(package\s+\w+|func\s+\w+\s*\(|import\s+\(|fmt\.Print)/m.test(value)) {
    return 'go'
  }

  if (/^\s*(fn\s+\w+\s*\(|let\s+mut\s+|use\s+\w+::|impl\s+\w+)/m.test(value)) {
    return 'rust'
  }

  if (/^\s*(public\s+class\s+|class\s+\w+\s*\{|import\s+java\.)/m.test(value)) {
    return 'java'
  }

  if (/^\s*[.#]?[\w-]+\s*\{[\s\S]*:[\s\S]*\}/.test(value)) {
    return 'css'
  }

  return 'text'
}

function resolveCodeLanguage(children: ReactNode, code: string) {
  const declared = normalizeShikiLanguage(extractLanguage(children))
  return declared === 'text' ? inferCodeLanguage(code) : declared
}

/**
 * CodeBlock — replaces the plain <pre> used by react-markdown.
 *
 * Adds an Apple-style floating "复制代码" button in the top-right that
 * flips to "已复制" for ~1.5s on success. Inline code is unaffected —
 * react-markdown only routes fenced blocks through `pre`.
 */
function CodeBlock({ children }: { children?: ReactNode }) {
  const rawCode = extractCodeText(children).replace(/\n$/, '')
  const code = repairExplodedCodeBlock(rawCode)
  const language = resolveCodeLanguage(children, code)

  if (language === 'mermaid') {
    return <MermaidBlock code={code} />
  }

  return <HighlightedCodeBlock code={code} language={language} />
}

function HighlightedCodeBlock({ code, language }: { code: string; language: string }) {
  const [copied, setCopied] = useState(false)
  const [highlighted, setHighlighted] = useState({ key: '', html: '' })
  const copyTimerRef = useRef<number | null>(null)
  const highlightKey = `${language}::${code}`
  const isOversized = code.length > MAX_HIGHLIGHT_CHARS

  useEffect(() => {
    let cancelled = false

    async function highlight() {
      try {
        const html = await highlightCode(code, language)
        if (!cancelled) setHighlighted({ key: highlightKey, html })
      } catch {
        if (!cancelled) setHighlighted({ key: highlightKey, html: '' })
      }
    }

    if (code && !isOversized) {
      highlight()
    }

    return () => {
      cancelled = true
    }
  }, [code, highlightKey, isOversized, language])

  const handleCopy = async () => {
    try {
      if (!navigator.clipboard?.writeText) return
      await navigator.clipboard.writeText(code)
      setCopied(true)
      if (copyTimerRef.current !== null) window.clearTimeout(copyTimerRef.current)
      copyTimerRef.current = window.setTimeout(() => setCopied(false), 1500)
    } catch {
      // Copy is optional; keep the reader flow uninterrupted if clipboard fails.
    }
  }

  const hasHighlight = highlighted.key === highlightKey && highlighted.html

  useEffect(() => () => {
    if (copyTimerRef.current !== null) window.clearTimeout(copyTimerRef.current)
  }, [])

  return (
    <div className="md-code-block group relative not-prose">
      <div className="md-pre-header">
        <span className="md-lang-badge">{language}</span>
        {isOversized && <span className="md-size-badge">大代码块</span>}
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={handleCopy}
          aria-label={copied ? '已复制' : '复制代码'}
          className="md-copy-btn"
        >
          {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
          {copied ? '已复制' : '复制'}
        </Button>
      </div>
      {hasHighlight && !isOversized ? (
        <div className="md-shiki-html" dangerouslySetInnerHTML={{ __html: highlighted.html }} />
      ) : (
        <pre className="md-pre-plain">
          <code className={language === 'text' ? undefined : `language-${language}`}>{code}</code>
        </pre>
      )}
    </div>
  )
}

// ── Source list helpers ───────────────────────────────────────────────────

/**
 * Extract plain text from a react-markdown AST node.
 */
function extractSourceText(node: ElementContent): string {
  if (node.type === 'text') return node.value
  if (node.type !== 'element' || node.tagName === 'a') return ''
  return node.children.map(extractSourceText).join('')
}

/**
 * Extract { href, label } pairs from <a> tags in a react-markdown AST node.
 */
interface SourceLink {
  href: string
  label: string
}

function extractSourceLinks(node: ElementContent): SourceLink[] {
  if (node.type !== 'element') return []
  if (node.tagName === 'a') {
    const href = typeof node.properties.href === 'string' ? node.properties.href : ''
    const isInternal = href.startsWith('/') && !href.startsWith('//')
    const isHttp = /^https?:\/\//i.test(href)
    if (!href || (!isInternal && !isHttp)) return []
    return [{ href, label: node.children.map(extractSourceText).join('').trim() || href }]
  }
  return node.children.flatMap(extractSourceLinks)
}

function getOrderedListItems(node: ElementContent | undefined): Element[] {
  if (node?.type !== 'element' || node.tagName !== 'ol') return []
  const items: Element[] = []
  for (const child of node.children) {
    if (child.type === 'text' && child.value.trim() === '') continue
    if (child.type !== 'element' || child.tagName !== 'li') return []
    items.push(child)
  }
  return items
}

function countAnchorElements(node: ElementContent): number {
  if (node.type !== 'element') return 0
  const current = node.tagName === 'a' ? 1 : 0
  return current + node.children.reduce((count, child) => count + countAnchorElements(child), 0)
}

function isFullyRenderableSourceItem(item: Element): boolean {
  const links = extractSourceLinks(item)
  return links.length > 0 && links.length === countAnchorElements(item)
}

/**
 * A single source reference rendered as a clickable card.
 */
function SourceItem({ index, text, links }: { index: number; text: string; links: SourceLink[] }) {
  // Clean up the text: remove leading punctuation/colons from the label
  const cleanText = text.replace(/^[\s：:—\-–]+/, '').trim()
  return (
    <div className="group flex items-start gap-2.5 px-3 py-2 rounded-lg border border-border
                    hover:border-violet-200 hover:bg-violet-50/30 transition-all duration-150">
      {/* Index number */}
      <span className="flex-shrink-0 w-5 h-5 rounded-full bg-muted group-hover:bg-violet-100
                       flex items-center justify-center text-[11px] font-medium text-muted-foreground
                       group-hover:text-violet-500 transition-colors">
        {index}
      </span>

      {/* Source text */}
      {cleanText && (
        <span className="text-[13px] text-muted-foreground leading-snug pt-0.5">
          {cleanText}
        </span>
      )}

      {/* Link buttons */}
      <div className="flex items-center gap-1 ml-auto flex-shrink-0">
        {links.map((link, i) => (
          <a
            key={i}
            href={link.href}
            target={link.href.startsWith('/') ? undefined : '_blank'}
            rel={link.href.startsWith('/') ? undefined : 'noopener noreferrer'}
            title={link.href}
            className="inline-flex items-center gap-1 px-2 py-1 rounded-md text-[11px] font-medium
                       border border-border text-muted-foreground
                       hover:text-violet-600 hover:border-violet-200 hover:bg-violet-50
                       transition-all duration-150"
          >
            {link.href.startsWith('/news/')
              ? <Newspaper className="w-3 h-3" />
              : <ExternalLink className="w-3 h-3" />
            }
            {link.href.startsWith('/news/') ? '详情' : '原文'}
          </a>
        ))}
      </div>
    </div>
  )
}

const MD_COMPONENTS: Components = {
  h1: ({ children }) => (
    <h1 className="text-2xl font-bold text-foreground mt-8 mb-4 pb-2 border-b border-border break-words">
      {children}
    </h1>
  ),
  h2: ({ children }) => (
    <h2 className="text-xl font-semibold text-foreground mt-7 mb-3 pb-1 border-b border-border break-words">
      {children}
    </h2>
  ),
  h3: ({ children }) => (
    <h3 className="text-lg font-semibold text-foreground mt-6 mb-2 break-words">{children}</h3>
  ),
  h4: ({ children }) => (
    <h4 className="text-base font-semibold text-neutral-800 mt-5 mb-2 break-words">{children}</h4>
  ),
  p: ({ children }) => (
    <p className="text-base leading-[1.9] text-neutral-700 mb-5 text-left break-words">
      {children}
    </p>
  ),
  a: ({ href, children }) => {
    const isExternal = href && (href.startsWith('http://') || href.startsWith('https://'))
    return (
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        className="text-blue-600 hover:text-blue-800 underline decoration-blue-300 hover:decoration-blue-600 underline-offset-2 transition-colors break-all inline-flex items-center gap-0.5"
      >
        {children}
        {isExternal && <ExternalLink className="w-3 h-3 flex-shrink-0 opacity-60" />}
      </a>
    )
  },
  strong: ({ children }) => <strong className="font-semibold text-foreground">{children}</strong>,
  em: ({ children }) => <em className="text-neutral-700 italic">{children}</em>,
  blockquote: ({ children }) => (
    <blockquote className="border-l-4 border-violet-300 bg-violet-50/50 rounded-r-lg pl-4 py-3 pr-3 my-4 text-neutral-700 break-words">
      {children}
    </blockquote>
  ),
  ul: ({ children }) => (
    <ul className="list-disc list-outside ml-5 mb-5 space-y-1.5 text-base leading-[1.9] text-neutral-700 break-words">
      {children}
    </ul>
  ),
  ol: ({ children, node }) => {
    const listItems = getOrderedListItems(node)
    const useSourceItems = listItems.length > 0 && listItems.every(isFullyRenderableSourceItem)

    if (useSourceItems) {
      return (
        <div className="my-4 space-y-2">
          {listItems.map((child, i) => {
            const text = extractSourceText(child).trim()
            const links = extractSourceLinks(child)
            if (!text && links.length === 0) return null
            return (
              <SourceItem key={i} index={i + 1} text={text} links={links} />
            )
          })}
        </div>
      )
    }

    return (
      <ol className="list-decimal list-outside ml-5 mb-5 space-y-1.5 text-base leading-[1.9] text-neutral-700 break-words">
        {children}
      </ol>
    )
  },
  li: ({ children }) => <li className="pl-1 break-words">{children}</li>,
  code: ({ className, children }) => <code className={className}>{children}</code>,
  // Fenced code blocks come through `pre`. The CodeBlock wrapper adds Shiki
  // highlighting and the hover-visible copy button.
  pre: CodeBlock,
  table: ({ children }) => (
    <div className="overflow-x-auto my-4 rounded-lg border border-border">
      <table className="min-w-full text-[14px]">{children}</table>
    </div>
  ),
  thead: ({ children }) => <thead className="bg-muted">{children}</thead>,
  th: ({ children }) => (
    <th className="px-4 py-2.5 text-left font-semibold text-neutral-700 border-b border-border">
      {children}
    </th>
  ),
  td: ({ children }) => (
    <td className="px-4 py-2.5 text-neutral-700 border-b border-border">{children}</td>
  ),
  hr: () => <hr className="my-6 border-border" />,
  img: ({ src, alt }) => (
    <span className="my-6 block text-center">
      <img
        src={src}
        alt={alt || ''}
        className="max-w-full h-auto rounded-lg mx-auto shadow-sm"
        style={IMG_STYLE}
      />
      {alt && <span className="block text-xs text-muted-foreground mt-2">{alt}</span>}
    </span>
  ),
}

const REMARK_PLUGINS = [remarkGfm]
const LEGACY_SUMMARY_REMARK_PLUGINS = [remarkGfm, remarkLegacySummaryParagraphs]

/**
 * Apple-style article body Markdown renderer.
 * All custom components and plugin arrays are module-level constants — no
 * per-render allocation, so React Compiler / memo work properly.
 */
export default function MarkdownContent({
  content,
  legacySummarySpacing = false,
}: {
  content: string
  legacySummarySpacing?: boolean
}) {
  return (
    <div className="article-markdown prose prose-gray mx-auto w-full max-w-[74ch] overflow-hidden">
      <ReactMarkdown remarkPlugins={legacySummarySpacing ? LEGACY_SUMMARY_REMARK_PLUGINS : REMARK_PLUGINS} components={MD_COMPONENTS}>
        {content}
      </ReactMarkdown>
    </div>
  )
}
