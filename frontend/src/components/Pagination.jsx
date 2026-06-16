import { ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight } from 'lucide-react'

/**
 * Unified pagination component — responsive and mobile-friendly.
 *
 * Mobile (<640px):
 *   - Only shows << < [page] > >> buttons with chevrons
 *   - 44px minimum touch targets
 *
 * Desktop (≥640px):
 *   - Shows first/last text labels
 *   - Sliding window of numbered pages with ellipsis
 *   - Page info summary
 *
 * @param {number} currentPage  — current page (1-based)
 * @param {number} totalPages   — total page count
 * @param {number} totalCount   — total item count (for summary)
 * @param {function} onPageChange — callback(newPage)
 * @param {string} [lang='zh']  — 'zh' or 'en'
 */
export function Pagination({ currentPage, totalPages, totalCount = 0, onPageChange, lang = 'zh' }) {
  if (totalPages <= 1) return null

  const t = lang === 'en'
    ? { first: 'First', prev: 'Previous', next: 'Next', last: 'Last', page: 'Page', of: 'of', items: 'items' }
    : { first: '首页', prev: '上一页', next: '下一页', last: '尾页', page: '第', of: '页', items: '条' }

  // Build sliding window of page numbers
  const pages = buildPageNumbers(currentPage, totalPages, { maxVisible: 5 })

  return (
    <div className="flex flex-col items-center gap-3 mt-10 mb-6 sm:mt-12">
      {/* Button row */}
      <nav className="flex items-center justify-center gap-1 sm:gap-1.5" aria-label="Pagination">
        {/* First — hidden on mobile */}
        <PageButton
          onClick={() => onPageChange(1)}
          disabled={currentPage === 1}
          className="hidden sm:inline-flex px-3 py-2 text-sm"
          aria-label={t.first}
        >
          <ChevronsLeft className="w-4 h-4" />
          <span className="ml-1">{t.first}</span>
        </PageButton>
        {/* Mobile-only compact first */}
        <PageButton
          onClick={() => onPageChange(1)}
          disabled={currentPage === 1}
          className="sm:hidden w-11 h-11"
          aria-label={t.first}
        >
          <ChevronsLeft className="w-4 h-4" />
        </PageButton>

        {/* Prev */}
        <PageButton
          onClick={() => onPageChange(currentPage - 1)}
          disabled={currentPage === 1}
          className="w-11 h-11 sm:w-auto sm:px-3 sm:py-2 sm:text-sm"
          aria-label={t.prev}
        >
          <ChevronLeft className="w-4 h-4 sm:mr-1" />
          <span className="hidden sm:inline">{t.prev}</span>
        </PageButton>

        {/* Page numbers */}
        {pages.map((p, idx) =>
          p === 'ellipsis' ? (
            <span key={`e-${idx}`} className="w-9 h-11 sm:h-9 flex items-center justify-center text-sm text-gray-400 select-none" aria-hidden>
              …
            </span>
          ) : (
            <PageButton
              key={p}
              onClick={() => onPageChange(p)}
              active={p === currentPage}
              className="w-11 h-11 sm:w-9 sm:h-9 text-sm"
              aria-label={lang === 'en' ? `Page ${p}` : `第${p}页`}
              aria-current={p === currentPage ? 'page' : undefined}
            >
              {p}
            </PageButton>
          )
        )}

        {/* Next */}
        <PageButton
          onClick={() => onPageChange(currentPage + 1)}
          disabled={currentPage === totalPages}
          className="w-11 h-11 sm:w-auto sm:px-3 sm:py-2 sm:text-sm"
          aria-label={t.next}
        >
          <span className="hidden sm:inline">{t.next}</span>
          <ChevronRight className="w-4 h-4 sm:ml-1" />
        </PageButton>

        {/* Last — hidden on mobile */}
        <PageButton
          onClick={() => onPageChange(totalPages)}
          disabled={currentPage === totalPages}
          className="hidden sm:inline-flex px-3 py-2 text-sm"
          aria-label={t.last}
        >
          <span className="mr-1">{t.last}</span>
          <ChevronsRight className="w-4 h-4" />
        </PageButton>
        {/* Mobile-only compact last */}
        <PageButton
          onClick={() => onPageChange(totalPages)}
          disabled={currentPage === totalPages}
          className="sm:hidden w-11 h-11"
          aria-label={t.last}
        >
          <ChevronsRight className="w-4 h-4" />
        </PageButton>
      </nav>

      {/* Summary — subtle, below */}
      <p className="text-xs text-gray-400 select-none">
        {lang === 'en'
          ? `${t.page} ${currentPage} / ${totalPages} · ${totalCount} ${t.items}`
          : `第 ${currentPage} / ${totalPages} 页 · 共 ${totalCount} ${t.items}`}
      </p>
    </div>
  )
}

/**
 * Base page button with consistent styling.
 */
function PageButton({ children, onClick, disabled, active = false, className = '', ...rest }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`
        inline-flex items-center justify-center rounded-lg font-medium transition-all
        disabled:opacity-40 disabled:cursor-not-allowed
        ${active
          ? 'bg-gray-900 text-white shadow-sm'
          : 'bg-white border border-gray-200 text-gray-600 hover:bg-gray-50 hover:border-gray-300'
        }
        ${className}
      `}
      {...rest}
    >
      {children}
    </button>
  )
}

/**
 * Build a sliding window of page numbers with ellipsis.
 * Returns an array of numbers and 'ellipsis' strings.
 *
 * Example (maxVisible=5, totalPages=20, currentPage=10):
 *   [1, 'ellipsis', 8, 9, 10, 11, 12, 'ellipsis', 20]
 */
function buildPageNumbers(current, total, { maxVisible = 5 } = {}) {
  const result = []

  if (total <= maxVisible + 2) {
    // Show all pages
    for (let i = 1; i <= total; i++) result.push(i)
    return result
  }

  // Always show first page
  result.push(1)

  const half = Math.floor(maxVisible / 2)
  let start = Math.max(2, current - half)
  let end = Math.min(total - 1, start + maxVisible - 1)

  // Adjust start if we hit the end boundary
  if (end - start + 1 < maxVisible) {
    start = Math.max(2, end - maxVisible + 1)
  }

  // Ellipsis before window
  if (start > 2) result.push('ellipsis')
  // Guard: if start === 2, skip ellipsis, just show 2
  if (start === 2) start = 2

  for (let i = start; i <= end; i++) {
    result.push(i)
  }

  // Ellipsis after window
  if (end < total - 1) result.push('ellipsis')

  // Always show last page
  result.push(total)

  return result
}
