import { useState } from 'react'
import { List, ChevronRight } from 'lucide-react'

/**
 * ArticleToc — table of contents sidebar for article headings.
 *
 * Props:
 *   - headings: { id, text, level }[] — flat list extracted by useArticleToc
 *   - activeId: string — id of the heading currently in viewport
 *
 * Mobile: collapsible bottom sheet.
 * Desktop: fixed right sidebar (only visible when there are 2+ headings).
 */
export default function ArticleToc({ headings, activeId }) {
  const [open, setOpen] = useState(false)

  if (headings.length < 2) return null

  function handleClick(id) {
    const el = document.getElementById(id)
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'start' })
      // Close on mobile after navigation
      setOpen(false)
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
            block w-full text-left text-xs leading-snug py-1 rounded transition-colors
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
      {/* Mobile: floating button + bottom sheet */}
      <div className="lg:hidden">
        {/* Floating trigger button */}
        <button
          type="button"
          onClick={() => setOpen(!open)}
          aria-label={open ? '关闭目录' : '打开目录'}
          className="fixed bottom-20 right-4 z-40 w-10 h-10 rounded-full
                     bg-white shadow-lg border border-neutral-200
                     flex items-center justify-center
                     active:scale-95 transition-transform"
        >
          <List className="size-5 text-neutral-600" />
        </button>

        {/* Backdrop */}
        {open && (
          <div
            className="fixed inset-0 z-40 bg-black/20"
            onClick={() => setOpen(false)}
          />
        )}

        {/* Bottom sheet */}
        <div className={`fixed bottom-0 left-0 right-0 z-50 bg-white rounded-t-2xl shadow-xl
                         border-t border-neutral-200 max-h-[50vh] overflow-y-auto
                         transition-transform duration-300
                         ${open ? 'translate-y-0' : 'translate-y-full'}`}
        >
          <div className="flex items-center justify-between px-4 py-3 border-b border-neutral-100">
            <span className="text-sm font-medium text-neutral-800">文章目录</span>
            <button
              type="button"
              onClick={() => setOpen(false)}
              aria-label="关闭目录"
              className="p-1 rounded hover:bg-neutral-100"
            >
              ✕
            </button>
          </div>
          <div className="px-4 py-3">{tocItems}</div>
        </div>
      </div>

      {/* Desktop: right sidebar */}
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
