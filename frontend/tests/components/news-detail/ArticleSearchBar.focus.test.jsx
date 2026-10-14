import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import ArticleSearchBar from '@/components/news-detail/ArticleSearchBar'

describe('article search focus and escape', () => {
  it('focuses search input and closes on Escape exactly once', () => {
    const close = vi.fn()
    render(<ArticleSearchBar query="" onQueryChange={vi.fn()}
      matchCount={0} currentIndex={0} onGoNext={vi.fn()} onGoPrev={vi.fn()} onClose={close} />)
    const input = screen.getByRole('textbox', { name: '搜索文章内容' })
    expect(input).toHaveFocus()
    fireEvent.keyDown(input, { key: 'Escape' })
    expect(close).toHaveBeenCalledTimes(1)
  })
})
