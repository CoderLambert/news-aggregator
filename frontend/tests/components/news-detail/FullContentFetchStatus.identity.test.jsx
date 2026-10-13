import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import FullContentFetchStatus from '@/components/news-detail/FullContentFetchStatus'

describe('article identity pending review', () => {
  it.each(['pending', 'queued', 'fetching', 'failed', 'success'])('hides source and fetch actions for %s with invalid identity', (status) => {
    const onFetch = vi.fn()
    render(<FullContentFetchStatus
      news={{ url: 'https://www.reuters.com/world/guessed-story/', full_content_error_code: 'invalid_identity',
        full_content_fetch_status: status, full_content_state: 'legacy', full_content: 'Old cached body',
        full_content_next_attempt_at: '2026-10-13T03:00:00Z' }}
      articleLoading={status === 'fetching'} onFetch={onFetch} onResume={vi.fn()} onCancel={vi.fn()}
    />)
    expect(screen.getByText('链接待核验')).toBeInTheDocument()
    expect(screen.getByText('核验真实链接后才能获取原文。')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: '阅读原文' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
    expect(onFetch).not.toHaveBeenCalled()
  })
})


it('offers source reading but no shared retry after the bounded attempts are exhausted', () => {
  render(<FullContentFetchStatus news={{ url: 'https://webkit.org/blog/123/article/',
    full_content_fetch_status: 'failed', full_content_retry_count: 5, full_content_state: 'legacy', full_content: 'Old valid body' }}
    onFetch={vi.fn()} />)
  expect(screen.getByText('正文尝试已达上限')).toBeInTheDocument()
  expect(screen.getByText('上次保存的正文仍可阅读，也可直接前往来源网站。')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: '阅读原文' })).toHaveAttribute('href', 'https://webkit.org/blog/123/article/')
  expect(screen.queryByRole('button')).not.toBeInTheDocument()
})
