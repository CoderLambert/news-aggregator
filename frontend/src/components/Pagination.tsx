import type { ButtonHTMLAttributes } from 'react'
import { ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight } from 'lucide-react'
import type { Language } from '@/types/news'

type PageToken = number | 'ellipsis'

interface PaginationProps {
  currentPage: number
  totalPages: number
  totalCount?: number
  onPageChange: (page: number) => void
  lang?: Language
}

export function Pagination({ currentPage, totalPages, totalCount = 0, onPageChange, lang = 'zh' }: PaginationProps) {
  if (totalPages <= 1) return null
  const pages = buildPageNumbers(currentPage, totalPages)
  const labels = lang === 'en'
    ? { first: 'First page', previous: 'Previous page', next: 'Next page', last: 'Last page', pagination: 'Pagination' }
    : { first: '首页', previous: '上一页', next: '下一页', last: '尾页', pagination: '分页导航' }

  const pageSummary = lang === 'en'
    ? `Page ${currentPage} of ${totalPages}`
    : `第 ${currentPage} / ${totalPages} 页`
  const resultSummary = lang === 'en'
    ? `${totalCount.toLocaleString('en-US')} results`
    : `共 ${totalCount.toLocaleString('zh-CN')} 条内容`

  return (
    <div className="mb-8 mt-10 flex justify-center px-2 sm:px-0">
      <nav
        className="w-full max-w-sm overflow-hidden rounded-2xl border border-border/80 bg-card/90 shadow-sm backdrop-blur-sm sm:w-auto sm:max-w-none"
        aria-label={labels.pagination}
      >
        <div className="flex items-center justify-between gap-1 p-1.5 sm:justify-center">
          <NavButton className="hidden sm:inline-flex" onClick={() => onPageChange(1)} disabled={currentPage === 1} aria-label={labels.first} title={labels.first}>
            <ChevronsLeft className="size-4" aria-hidden="true" />
          </NavButton>
          <NavButton onClick={() => onPageChange(currentPage - 1)} disabled={currentPage === 1} aria-label={labels.previous} title={labels.previous}>
            <ChevronLeft className="size-4" aria-hidden="true" />
            <span className="sm:hidden">{lang === 'en' ? 'Prev' : '上一页'}</span>
          </NavButton>

          <span className="mx-1 hidden h-5 w-px bg-border sm:block" aria-hidden="true" />
          <span className="min-w-24 text-center text-sm font-semibold tabular-nums text-foreground sm:hidden" aria-live="polite">
            {pageSummary}
          </span>

          <div className="hidden items-center gap-1 sm:flex">
          {pages.map((page, index) => page === 'ellipsis'
              ? <span key={`ellipsis-${index}`} className="flex size-9 select-none items-center justify-center text-sm text-muted-foreground/70" aria-hidden="true">…</span>
              : <PageNumber key={page} page={page} active={page === currentPage} lang={lang} onClick={() => onPageChange(page)} />)}
          </div>

          <span className="mx-1 hidden h-5 w-px bg-border sm:block" aria-hidden="true" />
          <NavButton onClick={() => onPageChange(currentPage + 1)} disabled={currentPage === totalPages} aria-label={labels.next} title={labels.next}>
            <span className="sm:hidden">{lang === 'en' ? 'Next' : '下一页'}</span>
            <ChevronRight className="size-4" aria-hidden="true" />
          </NavButton>
          <NavButton className="hidden sm:inline-flex" onClick={() => onPageChange(totalPages)} disabled={currentPage === totalPages} aria-label={labels.last} title={labels.last}>
            <ChevronsRight className="size-4" aria-hidden="true" />
          </NavButton>
        </div>

        <div className="flex items-center justify-center gap-2 border-t border-border/70 bg-muted/35 px-4 py-2 text-xs text-muted-foreground">
          <span className="hidden tabular-nums sm:inline">{pageSummary}</span>
          <span className="hidden size-1 rounded-full bg-primary/45 sm:inline-block" aria-hidden="true" />
          <span>{resultSummary}</span>
        </div>
      </nav>
    </div>
  )
}

function NavButton({ children, className = '', ...props }: ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      type="button"
      className={`inline-flex min-h-11 items-center justify-center gap-1 rounded-xl px-3 text-sm font-medium text-muted-foreground transition-[color,background-color,transform] hover:bg-accent hover:text-foreground active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-35 sm:size-9 sm:min-h-0 sm:px-0 ${className}`}
      {...props}
    >
      {children}
    </button>
  )
}

function PageNumber({ page, active, lang, onClick }: { page: number; active: boolean; lang: Language; onClick: () => void }) {
  const pageLabel = lang === 'en'
    ? `${active ? 'Current page, ' : ''}Page ${page}`
    : `${active ? '当前页，' : ''}第 ${page} 页`

  return (
    <button
      type="button"
      aria-current={active ? 'page' : undefined}
      aria-label={pageLabel}
      onClick={onClick}
      className={`inline-flex size-9 items-center justify-center rounded-xl text-sm tabular-nums transition-[color,background-color,box-shadow,transform] active:scale-95 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${active ? 'bg-primary font-semibold text-primary-foreground shadow-sm' : 'font-medium text-muted-foreground hover:bg-accent hover:text-foreground'}`}
    >
      {page}
    </button>
  )
}

function buildPageNumbers(current: number, total: number): PageToken[] {
  const result: PageToken[] = []
  const maxVisible = 5
  if (total <= maxVisible + 2) return Array.from({ length: total }, (_, index) => index + 1)
  const half = Math.floor(maxVisible / 2)
  let start = Math.max(2, current - half)
  const end = Math.min(total - 1, start + maxVisible - 1)
  if (end - start + 1 < maxVisible) start = Math.max(2, end - maxVisible + 1)
  result.push(1)
  if (start > 2) result.push('ellipsis')
  for (let page = start; page <= end; page++) result.push(page)
  if (end < total - 1) result.push('ellipsis')
  result.push(total)
  return result
}
