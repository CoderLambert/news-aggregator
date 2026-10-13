import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { Pagination } from '@/components/Pagination'

describe('Pagination', () => {
  it('renders the current page and formatted result summary', () => {
    render(<Pagination currentPage={6} totalPages={12} totalCount={1234} onPageChange={vi.fn()} />)

    expect(screen.getByRole('navigation', { name: '分页导航' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '当前页，第 6 页' })).toHaveAttribute('aria-current', 'page')
    expect(screen.getAllByText('第 6 / 12 页')).toHaveLength(2)
    expect(screen.getByText('共 1,234 条内容')).toBeInTheDocument()
  })

  it('changes pages and disables boundary controls', () => {
    const onPageChange = vi.fn()
    const { rerender } = render(<Pagination currentPage={1} totalPages={8} totalCount={80} onPageChange={onPageChange} />)

    expect(screen.getByRole('button', { name: '首页' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '上一页' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: '下一页' }))
    expect(onPageChange).toHaveBeenCalledWith(2)

    rerender(<Pagination currentPage={8} totalPages={8} totalCount={80} onPageChange={onPageChange} />)
    expect(screen.getByRole('button', { name: '下一页' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '尾页' })).toBeDisabled()
  })

  it('does not render when there is only one page', () => {
    const { container } = render(<Pagination currentPage={1} totalPages={1} totalCount={3} onPageChange={vi.fn()} />)

    expect(container).toBeEmptyDOMElement()
  })
})
