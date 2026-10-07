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
    ? { first: 'First page', previous: 'Previous page', next: 'Next page', last: 'Last page' }
    : { first: '首页', previous: '上一页', next: '下一页', last: '尾页' }

  return (
    <div className="mb-8 mt-10 flex flex-col items-center gap-4">
      <nav className="flex items-center gap-1" aria-label={lang === 'en' ? 'Pagination' : '分页'}>
        <NavButton onClick={() => onPageChange(1)} disabled={currentPage === 1} aria-label={labels.first}><ChevronsLeft className="size-4" /></NavButton>
        <NavButton onClick={() => onPageChange(currentPage - 1)} disabled={currentPage === 1} aria-label={labels.previous}><ChevronLeft className="size-4" /></NavButton>
        <span className="mx-1 hidden h-5 w-px bg-gray-200 sm:block" aria-hidden="true" />
        <div className="flex items-center gap-0.5 sm:gap-1">
          {pages.map((page, index) => page === 'ellipsis'
            ? <span key={`ellipsis-${index}`} className="flex h-10 w-8 select-none items-center justify-center text-xs text-gray-400" aria-hidden="true">···</span>
            : <PageNumber key={page} page={page} active={page === currentPage} onClick={() => onPageChange(page)} />)}
        </div>
        <span className="mx-1 hidden h-5 w-px bg-gray-200 sm:block" aria-hidden="true" />
        <NavButton onClick={() => onPageChange(currentPage + 1)} disabled={currentPage === totalPages} aria-label={labels.next}><ChevronRight className="size-4" /></NavButton>
        <NavButton onClick={() => onPageChange(totalPages)} disabled={currentPage === totalPages} aria-label={labels.last}><ChevronsRight className="size-4" /></NavButton>
      </nav>
      <div className="inline-flex select-none items-center gap-1.5 rounded-full bg-gray-100 px-3 py-1 text-xs text-gray-500">
        <span className="inline-block size-1.5 rounded-full bg-gray-300" aria-hidden="true" />
        <span>{lang === 'en' ? `${currentPage} / ${totalPages} · ${totalCount.toLocaleString()} results` : `第 ${currentPage}/${totalPages} 页 · 共 ${totalCount} 条`}</span>
      </div>
    </div>
  )
}

function NavButton({ children, onClick, disabled, ...rest }: ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button type="button" onClick={onClick} disabled={disabled} className="group inline-flex size-10 items-center justify-center rounded-xl text-gray-500 transition-all duration-150 hover:bg-gray-100 hover:text-gray-700 active:scale-95 disabled:cursor-not-allowed disabled:opacity-30 disabled:hover:bg-transparent" {...rest}>
      {children}
    </button>
  )
}

function PageNumber({ page, active, onClick }: { page: number; active: boolean; onClick: () => void }) {
  return (
    <button type="button" aria-current={active ? 'page' : undefined} onClick={onClick} className={`relative inline-flex size-10 items-center justify-center rounded-xl text-sm font-medium transition-all duration-150 active:scale-95 sm:size-9 ${active ? 'bg-gray-900 font-semibold text-white shadow-sm shadow-gray-200' : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'}`}>
      {page}
      {active && <span className="absolute -bottom-1 hidden size-1 rounded-full bg-gray-400 sm:block" aria-hidden="true" />}
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
