import { ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight } from 'lucide-react'

/**
 * Unified pagination component — refined and responsive.
 *
 * Mobile (<640px):
 *   - Pill-style buttons: << < [1] [2] [3] > >>
 *   - Active page has accent ring + dot indicator
 *   - 40px touch targets with smooth press animation
 *
 * Desktop (≥640px):
 *   - Segmented layout: [First] [Prev] [pages] [Next] [Last] + summary
 *   - Elegant hover/focus transitions
 *   - Page info pill with subtle background
 */
export function Pagination({ currentPage, totalPages, totalCount = 0, onPageChange, lang = 'zh' }) {
  if (totalPages <= 1) return null

  const pages = buildPageNumbers(currentPage, totalPages)

  return (
    <div className="flex flex-col items-center gap-4 mt-10 mb-8">
      {/* Button row */}
      <nav className="flex items-center gap-1" aria-label="Pagination">

        {/* First */}
        <NavButton
          onClick={() => onPageChange(1)}
          disabled={currentPage === 1}
          aria-label={lang === 'en' ? 'First page' : '首页'}
        >
          <ChevronsLeft className="w-4 h-4" />
        </NavButton>

        {/* Prev */}
        <NavButton
          onClick={() => onPageChange(currentPage - 1)}
          disabled={currentPage === 1}
          aria-label={lang === 'en' ? 'Previous page' : '上一页'}
        >
          <ChevronLeft className="w-4 h-4" />
        </NavButton>

        {/* Divider */}
        <span className="w-px h-5 bg-gray-200 mx-1 hidden sm:block" aria-hidden />

        {/* Page numbers */}
        <div className="flex items-center gap-0.5 sm:gap-1">
          {pages.map((p, idx) =>
            p === 'ellipsis' ? (
              <span
                key={`e-${idx}`}
                className="w-8 h-10 flex items-center justify-center text-xs text-gray-400 select-none"
                aria-hidden
              >
                ···
              </span>
            ) : (
              <PageNumber
                key={p}
                num={p}
                active={p === currentPage}
                onClick={() => onPageChange(p)}
              />
            )
          )}
        </div>

        {/* Divider */}
        <span className="w-px h-5 bg-gray-200 mx-1 hidden sm:block" aria-hidden />

        {/* Next */}
        <NavButton
          onClick={() => onPageChange(currentPage + 1)}
          disabled={currentPage === totalPages}
          aria-label={lang === 'en' ? 'Next page' : '下一页'}
        >
          <ChevronRight className="w-4 h-4" />
        </NavButton>

        {/* Last */}
        <NavButton
          onClick={() => onPageChange(totalPages)}
          disabled={currentPage === totalPages}
          aria-label={lang === 'en' ? 'Last page' : '尾页'}
        >
          <ChevronsRight className="w-4 h-4" />
        </NavButton>
      </nav>

      {/* Summary pill */}
      <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-gray-100 text-xs text-gray-500 select-none">
        <span className="inline-block w-1.5 h-1.5 rounded-full bg-gray-300" aria-hidden />
        <span>
          {lang === 'en'
            ? `${currentPage} / ${totalPages} · ${totalCount.toLocaleString()} results`
            : `第 ${currentPage}/${totalPages} 页 · 共 ${totalCount} 条`}
        </span>
      </div>
    </div>
  )
}

/**
 * Navigation button (first/last/prev/next) — compact icon style.
 */
function NavButton({ children, onClick, disabled, className = '', ...rest }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={`
        group inline-flex items-center justify-center
        w-10 h-10 rounded-xl
        text-gray-500
        transition-all duration-150
        hover:bg-gray-100 hover:text-gray-700
        active:scale-95
        disabled:opacity-30 disabled:cursor-not-allowed disabled:hover:bg-transparent disabled:hover:text-gray-500 disabled:active:scale-100
        ${className}
      `}
      {...rest}
    >
      {children}
    </button>
  )
}

/**
 * Page number button — refined with active state indicator.
 */
function PageNumber({ num, active, onClick }) {
  if (active) {
    return (
      <button
        type="button"
        aria-current="page"
        className="
          relative inline-flex flex-col items-center justify-center
          w-10 h-10 sm:w-9 sm:h-9
          rounded-xl
          bg-gray-900 text-white
          font-semibold text-sm
          shadow-sm shadow-gray-200
          transition-all duration-150
          active:scale-95
        "
      >
        {num}
        {/* Subtle dot below */}
        <span className="absolute -bottom-1 w-1 h-1 rounded-full bg-gray-400 hidden sm:block" />
      </button>
    )
  }

  return (
    <button
      type="button"
      onClick={onClick}
      className="
        inline-flex items-center justify-center
        w-10 h-10 sm:w-9 sm:h-9
        rounded-xl
        text-sm font-medium text-gray-600
        transition-all duration-150
        hover:bg-gray-100 hover:text-gray-900
        active:scale-95
      "
    >
      {num}
    </button>
  )
}

/**
 * Build sliding window of page numbers with ellipsis.
 * Returns an array of numbers and 'ellipsis' strings.
 */
function buildPageNumbers(current, total) {
  const result = []
  const maxVisible = 5

  // Small page count — show all
  if (total <= maxVisible + 2) {
    for (let i = 1; i <= total; i++) result.push(i)
    return result
  }

  const half = Math.floor(maxVisible / 2)
  let start = Math.max(2, current - half)
  let end = Math.min(total - 1, start + maxVisible - 1)
  if (end - start + 1 < maxVisible) {
    start = Math.max(2, end - maxVisible + 1)
  }

  result.push(1)
  if (start > 2) result.push('ellipsis')
  for (let i = start; i <= end; i++) result.push(i)
  if (end < total - 1) result.push('ellipsis')
  result.push(total)

  return result
}
