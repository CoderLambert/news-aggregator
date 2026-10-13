import { useState } from 'react'
import { List, X } from 'lucide-react'

/**
 * ArticleToc — fixed floating panel on the right edge of the screen.
 *
 * A small "目录" tab on the right edge, clicking opens a panel with
 * the heading outline. Active heading highlighted in orange.
 *
 * Works on both mobile and desktop. Always visible when there are 2+ headings.
 */
export default function ArticleToc({ headings, activeId }) {
  const [open, setOpen] = useState(false)

  if (headings.length < 2) return null

  function handleClick(id) {
    const el = document.getElementById(id)
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  const indent = (level) => (level - 1) * 12

  return (
    <>
      {/* ── Tab trigger — always visible on the right edge ── */}
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-label={open ? '关闭目录' : '打开目录'}
        className="fixed right-0 top-1/2 -translate-y-1/2 z-40
                   bg-card border border-r-0 border-border rounded-l-lg
                   shadow-md px-2 py-3
                   hover:bg-secondary active:scale-95
                   transition-all"
      >
        <List className="size-4 text-muted-foreground" />
        <span className="block text-[9px] text-muted-foreground mt-0.5 leading-none">目录</span>
      </button>

      {/* ── Panel ── */}
      {open && (
        <>
          {/* Backdrop on mobile */}
          <div
            className="fixed inset-0 z-40 bg-black/10 lg:bg-transparent"
            onClick={() => setOpen(false)}
          />

          <div className="fixed right-0 top-1/2 -translate-y-1/2 z-50
                          w-56 max-h-[70vh] bg-card rounded-l-xl
                          border border-r-0 border-border shadow-xl
                          flex flex-col overflow-hidden">
            {/* Header */}
            <div className="flex items-center justify-between px-3 py-2.5 border-b border-border flex-shrink-0">
              <span className="text-xs font-semibold text-foreground">文章目录</span>
              <button
                type="button"
                onClick={() => setOpen(false)}
                aria-label="关闭目录"
                className="p-1 rounded hover:bg-secondary transition-colors"
              >
                <X className="size-3.5 text-muted-foreground" />
              </button>
            </div>

            {/* Heading list */}
            <nav aria-label="文章目录" className="overflow-y-auto chat-input-scroll p-2 flex-1">
              {headings.map((h) => (
                <button
                  key={h.id}
                  type="button"
                  onClick={() => handleClick(h.id)}
                  className={`
                    block w-full text-left text-[11px] leading-snug py-1.5 rounded
                    transition-colors
                    ${h.id === activeId
                      ? 'text-primary font-semibold bg-primary/10'
                      : 'text-muted-foreground hover:text-foreground hover:bg-secondary'}
                  `}
                  style={{ paddingLeft: `${6 + indent(h.level)}px`, paddingRight: '6px' }}
                >
                  <span className="line-clamp-2">{h.text}</span>
                </button>
              ))}
            </nav>
          </div>
        </>
      )}
    </>
  )
}
