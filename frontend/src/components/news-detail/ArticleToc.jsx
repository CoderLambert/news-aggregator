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
                   bg-white border border-r-0 border-neutral-200 rounded-l-lg
                   shadow-md px-2 py-3
                   hover:bg-neutral-50 active:scale-95
                   transition-all"
      >
        <List className="size-4 text-neutral-600" />
        <span className="block text-[9px] text-neutral-500 mt-0.5 leading-none">目录</span>
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
                          w-56 max-h-[70vh] bg-white rounded-l-xl
                          border border-r-0 border-neutral-200 shadow-xl
                          flex flex-col overflow-hidden">
            {/* Header */}
            <div className="flex items-center justify-between px-3 py-2.5 border-b border-neutral-100 flex-shrink-0">
              <span className="text-xs font-semibold text-neutral-700">文章目录</span>
              <button
                type="button"
                onClick={() => setOpen(false)}
                aria-label="关闭目录"
                className="p-1 rounded hover:bg-neutral-100 transition-colors"
              >
                <X className="size-3.5 text-neutral-400" />
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
                      ? 'text-orange-600 font-semibold bg-orange-50'
                      : 'text-neutral-500 hover:text-neutral-800 hover:bg-neutral-50'}
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
