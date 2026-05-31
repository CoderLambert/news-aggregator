import { Search, X, ChevronUp, ChevronDown } from 'lucide-react'

/**
 * ArticleSearchBar — floating search bar for page-internal text search.
 *
 * Props:
 *   - query: string — current search text
 *   - onQueryChange: (q: string) => void
 *   - matchCount: number — total matches found
 *   - currentIndex: number — 0-based index of current match (-1 if none)
 *   - onGoNext: () => void — jump to next match
 *   - onGoPrev: () => void — jump to previous match
 *   - onClose: () => void — dismiss the search bar
 *
 * Keyboard:
 *   - Enter = goNext, Shift+Enter = goPrev
 *   - Escape = close
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
    <div className="sticky top-0 z-30 bg-white/95 backdrop-blur-sm border-b border-neutral-200 shadow-sm">
      <div className="max-w-3xl mx-auto flex items-center gap-2 px-3 py-2">
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
            <span className="text-xs text-neutral-500 whitespace-nowrap tabular-nums">
              {hasMatches ? `${displayIndex} / ${matchCount}` : '0 / 0'}
            </span>
            <button
              type="button"
              onClick={onGoPrev}
              disabled={!hasMatches}
              aria-label="上一个匹配"
              className="p-1 rounded hover:bg-neutral-100 disabled:opacity-30 disabled:cursor-not-allowed
                         transition-colors"
            >
              <ChevronUp className="size-3.5" />
            </button>
            <button
              type="button"
              onClick={onGoNext}
              disabled={!hasMatches}
              aria-label="下一个匹配"
              className="p-1 rounded hover:bg-neutral-100 disabled:opacity-30 disabled:cursor-not-allowed
                         transition-colors"
            >
              <ChevronDown className="size-3.5" />
            </button>
          </>
        )}
        <button
          type="button"
          onClick={onClose}
          aria-label="关闭搜索"
          className="p-1 rounded hover:bg-neutral-100 transition-colors ml-0.5"
        >
          <X className="size-4 text-neutral-500" />
        </button>
      </div>
    </div>
  )
}
