import { useState } from 'react'
import { List, ChevronDown, ChevronRight } from 'lucide-react'

/**
 * ArticleToc — table of contents for article headings.
 *
 * Two presentation modes:
 *   Mobile: inline collapsible section below the article title
 *   Desktop: fixed right sidebar
 *
 * Props:
 *   - headings: { id, text, level }[] — flat list extracted by useArticleToc
 *   - activeId: string — id of the heading currently in viewport
 */
export default function ArticleToc({ headings, activeId }) {
  const [open, setOpen] = useState(false)

  if (headings.length < 2) return null

  function handleClick(id) {
    const el = document.getElementById(id)
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  }

  // Indent based on heading level: h1=0, h2=1, h3=2
  const indent = (level) => (level - 1) * 14

  const tocItems = (
    <nav aria-label="文章目录" className="space-y-0.5">
      {headings.map((h) => (
        <button
          key={h.id}
          type="button"
          onClick={() => handleClick(h.id)}
          className={`
            block w-full text-left text-xs leading-snug py-1.5 rounded transition-colors
            ${h.id === activeId
              ? 'text-orange-600 font-medium bg-orange-50'
              : 'text-neutral-500 hover:text-neutral-800 hover:bg-neutral-50'}
          `}
          style={{ paddingLeft: `${8 + indent(h.level)}px`, paddingRight: '8px' }}
        >
          <span className="line-clamp-2">{h.text}</span>
        </button>
      ))}
    </nav>
  )

  return (
    <>
      {/* ── Mobile / all: inline collapsible section below title ── */}
      <div className="lg:hidden mb-4">
        <button
          type="button"
          onClick={() => setOpen(!open)}
          className="w-full flex items-center gap-2 px-3 py-2.5 rounded-xl
                     bg-neutral-50 border border-neutral-200 text-sm
                     hover:bg-neutral-100 transition-colors"
        >
          <List className="size-4 text-neutral-500" />
          <span className="text-neutral-700 font-medium">文章目录</span>
          <span className="text-neutral-400 text-xs ml-auto">{headings.length} 节</span>
          <ChevronDown
            className={`size-4 text-neutral-400 transition-transform ${open ? 'rotate-180' : ''}`}
          />
        </button>
        {open && (
          <div className="mt-2 px-3 py-2 bg-white rounded-xl border border-neutral-200 shadow-sm
                          max-h-[40vh] overflow-y-auto chat-input-scroll">
            {tocItems}
          </div>
        )}
      </div>

      {/* ── Desktop: fixed right sidebar ── */}
      <aside className="hidden lg:block fixed right-[max(1rem,calc((100vw-48rem)/2-14rem))]
                         top-24 w-52 max-h-[calc(100vh-8rem)] overflow-y-auto
                         chat-input-scroll">
        <div className="flex items-center gap-1.5 mb-3 px-2">
          <ChevronRight className="size-3 text-neutral-400" />
          <span className="text-xs font-medium text-neutral-400 uppercase tracking-wider">目录</span>
        </div>
        {tocItems}
      </aside>
    </>
  )
}
