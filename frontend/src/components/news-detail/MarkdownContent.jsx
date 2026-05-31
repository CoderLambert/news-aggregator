import { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Check, Copy } from 'lucide-react'

import { Button } from '@/components/ui/button'

const IMG_STYLE = { maxHeight: '480px', objectFit: 'contain' }

/**
 * extractCodeText — walks a `<pre>` element's children to recover the raw
 * source text. react-markdown hands us a children tree like:
 *   <pre><code className="language-js">{ "const x = 1\n" }</code></pre>
 * but the exact shape can vary (highlighter plugins, nested spans). We
 * just stringify the leaf text so the copy payload always matches what
 * the user actually sees on screen.
 */
function extractCodeText(node) {
  if (node == null || typeof node === 'boolean') return ''
  if (typeof node === 'string' || typeof node === 'number') return String(node)
  if (Array.isArray(node)) return node.map(extractCodeText).join('')
  if (node.props?.children !== undefined) return extractCodeText(node.props.children)
  return ''
}

/**
 * CodeBlock — replaces the plain <pre> used by react-markdown.
 *
 * Adds an Apple-style floating "复制代码" button in the top-right that
 * flips to "已复制" for ~1.5s on success. Inline code is unaffected —
 * react-markdown only routes fenced blocks through `pre`.
 */
function CodeBlock({ children }) {
  const [copied, setCopied] = useState(false)

  const handleCopy = async () => {
    const code = extractCodeText(children).replace(/\n$/, '')
    try {
      // Modern path. Falls back silently if clipboard API is unavailable
      // (e.g. non-HTTPS context, very old browser).
      await navigator.clipboard?.writeText(code)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    } catch {
      // Swallow — copying is a nice-to-have. We could surface a toast here
      // if/when the project adopts one.
    }
  }

  return (
    <div className="relative group my-4">
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={handleCopy}
        aria-label={copied ? '已复制' : '复制代码'}
        className="absolute top-2 right-2 h-7 px-2 text-xs bg-white/90 backdrop-blur-sm border-gray-200 text-gray-600 opacity-0 group-hover:opacity-100 focus:opacity-100 transition-opacity"
      >
        {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
        {copied ? '已复制' : '复制'}
      </Button>
      <pre className="bg-gray-50 rounded-xl p-4 overflow-x-auto border border-gray-200 font-mono text-[13px] leading-[1.6]">
        {children}
      </pre>
    </div>
  )
}

const MD_COMPONENTS = {
  h1: ({ children }) => (
    <h1 className="text-2xl font-bold text-gray-900 mt-8 mb-4 pb-2 border-b border-gray-200 break-words">
      {children}
    </h1>
  ),
  h2: ({ children }) => (
    <h2 className="text-xl font-semibold text-gray-800 mt-7 mb-3 pb-1 border-b border-gray-100 break-words">
      {children}
    </h2>
  ),
  h3: ({ children }) => (
    <h3 className="text-lg font-semibold text-gray-800 mt-6 mb-2 break-words">{children}</h3>
  ),
  h4: ({ children }) => (
    <h4 className="text-base font-semibold text-gray-700 mt-5 mb-2 break-words">{children}</h4>
  ),
  p: ({ children }) => (
    <p className="text-[15px] leading-[1.8] text-gray-700 mb-4 text-justify break-words">
      {children}
    </p>
  ),
  a: ({ href, children }) => (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="text-blue-600 hover:text-blue-800 underline decoration-blue-300 hover:decoration-blue-600 underline-offset-2 transition-colors break-all"
    >
      {children}
    </a>
  ),
  strong: ({ children }) => <strong className="font-semibold text-gray-900">{children}</strong>,
  em: ({ children }) => <em className="text-gray-600 italic">{children}</em>,
  blockquote: ({ children }) => (
    <blockquote className="border-l-4 border-violet-300 bg-violet-50/50 rounded-r-lg pl-4 py-3 pr-3 my-4 text-gray-600 break-words">
      {children}
    </blockquote>
  ),
  ul: ({ children }) => (
    <ul className="list-disc list-outside ml-5 mb-4 space-y-1.5 text-[15px] leading-[1.8] text-gray-700 break-words">
      {children}
    </ul>
  ),
  ol: ({ children }) => (
    <ol className="list-decimal list-outside ml-5 mb-4 space-y-1.5 text-[15px] leading-[1.8] text-gray-700 break-words">
      {children}
    </ol>
  ),
  li: ({ children }) => <li className="pl-1 break-words">{children}</li>,
  code: ({ className, children }) => {
    const isInline = !className
    return isInline ? (
      <code className="px-1.5 py-0.5 bg-gray-100 text-rose-600 rounded text-[0.85em] font-mono break-all">
        {children}
      </code>
    ) : (
      <code className={className}>{children}</code>
    )
  },
  // Fenced code blocks come through `pre`. The CodeBlock wrapper adds the
  // hover-visible copy button while preserving the existing <pre> styling.
  pre: CodeBlock,
  table: ({ children }) => (
    <div className="overflow-x-auto my-4 rounded-lg border border-gray-200">
      <table className="min-w-full text-[14px]">{children}</table>
    </div>
  ),
  thead: ({ children }) => <thead className="bg-gray-50">{children}</thead>,
  th: ({ children }) => (
    <th className="px-4 py-2.5 text-left font-semibold text-gray-700 border-b border-gray-200">
      {children}
    </th>
  ),
  td: ({ children }) => (
    <td className="px-4 py-2.5 text-gray-600 border-b border-gray-100">{children}</td>
  ),
  hr: () => <hr className="my-6 border-gray-200" />,
  img: ({ src, alt }) => (
    <figure className="my-6 text-center">
      <img
        src={src}
        alt={alt || ''}
        className="max-w-full h-auto rounded-lg mx-auto shadow-sm"
        style={IMG_STYLE}
      />
      {alt && <figcaption className="text-xs text-gray-400 mt-2">{alt}</figcaption>}
    </figure>
  ),
}

const REMARK_PLUGINS = [remarkGfm]

/**
 * Apple-style article body Markdown renderer.
 * All custom components and plugin arrays are module-level constants — no
 * per-render allocation, so React Compiler / memo work properly.
 */
export default function MarkdownContent({ content }) {
  return (
    <div className="article-markdown prose prose-gray max-w-none w-full overflow-hidden">
      <ReactMarkdown remarkPlugins={REMARK_PLUGINS} components={MD_COMPONENTS}>
        {content}
      </ReactMarkdown>
    </div>
  )
}
