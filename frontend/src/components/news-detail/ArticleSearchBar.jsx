import { Search, X, ChevronUp, ChevronDown } from 'lucide-react'

/**
 * ArticleSearchBar — floating search bar for page-internal text search.
 *
 * Keyboard: Enter = next, Shift+Enter = prev, Escape = close
 */
export default function ArticleSearchBar({
  query, onQueryChange, matchCount, currentIndex,
  onGoNext, onGoPrev, onClose,
}) {
  function handleKeyDown(e) {
    if (e.key === 'Escape') {
      onClose()
    } else if (e.key === 'Enter') {
      e.preventDefault()
      if (e.shiftKey) onGoPrev()
      else onGoNext()
    }
  }

  const hasMatches = matchCount > 0
  const displayIndex = hasMatches ? currentIndex + 1 : 0

  return (
    <div className="fixed top-0 left-0 right-0 z-50 bg-white/90 backdrop-blur-xl border-b border-neutral-100 shadow-[0_1px_3px_rgba(0,0,0,0.06)]">
      <div className="max-w-3xl mx-auto flex items-center gap-2.5 px-4 py-2.5">
        <Search className="size-4 text-neutral-400 flex-shrink-0" />
        <input
          type="text"
          value={query}
          onChange={(e) => onQueryChange(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="搜索文章内容…"
          aria-label="搜索文章内容"
          className="flex-1 bg-transparent border-none outline-none text-sm text-neutral-900
                     placeholder-neutral-400 min-w-0"
          autoFocus
        />
        {query && (
          <>
            <span className="text-xs text-neutral-500 whitespace-nowrap tabular-nums font-medium">
              {hasMatches ? `${displayIndex} / ${matchCount}` : '无结果'}
            </span>
            <div className="flex items-center border border-neutral-200 rounded-lg overflow-hidden">
              <button
                type="button"
                onClick={onGoPrev}
                disabled={!hasMatches}
                aria-label="上一个匹配"
                className="p-1 hover:bg-neutral-50 active:bg-neutral-100 disabled:opacity-25 disabled:cursor-not-allowed transition-colors"
              >
                <ChevronUp className="size-3.5" />
              </button>
              <div className="w-px h-4 bg-neutral-200" />
              <button
                type="button"
                onClick={onGoNext}
                disabled={!hasMatches}
                aria-label="下一个匹配"
                className="p-1 hover:bg-neutral-50 active:bg-neutral-100 disabled:opacity-25 disabled:cursor-not-allowed transition-colors"
              >
                <ChevronDown className="size-3.5" />
              </button>
            </div>
          </>
        )}
        <button
          type="button"
          onClick={onClose}
          aria-label="关闭搜索"
          className="p-1 -mr-1 rounded-lg hover:bg-neutral-100 active:bg-neutral-200 transition-colors"
        >
          <X className="size-4 text-neutral-500" />
        </button>
      </div>
    </div>
  )
}
