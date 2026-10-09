import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import FullContentFetchStatus from '@/components/news-detail/FullContentFetchStatus'

describe('FullContentFetchStatus', () => {
  const baseNews = { source_language: 'en', full_content: '' }

  it('shows the pending CTA without presenting the summary as original article text', () => {
    const onFetch = vi.fn()
    render(
      <FullContentFetchStatus
        news={{ ...baseNews, content: 'Summary must not appear as original', full_content_fetch_status: 'pending' }}
        articleLoading={false}
        onFetch={onFetch}
        onCancel={vi.fn()}
      />,
    )

    expect(screen.getByText('获取完整原文')).toBeInTheDocument()
    expect(screen.queryByText('Summary must not appear as original')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '获取完整原文' }))
    expect(onFetch).toHaveBeenCalledWith()
  })

  it('lets Chinese-source articles request their original body', () => {
    const onFetch = vi.fn()
    render(
      <FullContentFetchStatus
        news={{ source_language: 'zh', full_content: '', full_content_fetch_status: 'pending' }}
        articleLoading={false}
        onFetch={onFetch}
        onCancel={vi.fn()}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: '获取完整原文' }))
    expect(onFetch).toHaveBeenCalledWith()
  })

  it('shows the pending CTA for a whitespace-only cached body', () => {
    render(
      <FullContentFetchStatus
        news={{ ...baseNews, full_content: '  \n ', full_content_fetch_status: 'pending' }}
        articleLoading={false}
        onFetch={vi.fn()}
        onCancel={vi.fn()}
      />,
    )

    expect(screen.getByRole('button', { name: '获取完整原文' })).toBeInTheDocument()
  })

  it('shows the fetching state and supports canceling the local wait', () => {
    const onCancel = vi.fn()
    render(
      <FullContentFetchStatus
        news={{ ...baseNews, full_content_fetch_status: 'fetching' }}
        articleLoading
        onFetch={vi.fn()}
        onCancel={onCancel}
      />,
    )

    expect(screen.getByText(/正在获取原文内容/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '停止等待' }))
    expect(onCancel).toHaveBeenCalledOnce()
  })

  it('shows a network error with a retry action', () => {
    const onFetch = vi.fn()
    render(
      <FullContentFetchStatus
        news={{ ...baseNews, full_content_fetch_status: 'network_error' }}
        articleLoading={false}
        onFetch={onFetch}
        onCancel={vi.fn()}
      />,
    )

    expect(screen.getByRole('alert')).toHaveTextContent('网络或源站暂不可达，可稍后重试')
    fireEvent.click(screen.getByRole('button', { name: '重试' }))
    expect(onFetch).toHaveBeenCalledOnce()
  })

  it('shows validation failure without offering a retry', () => {
    render(
      <FullContentFetchStatus
        news={{ ...baseNews, full_content_fetch_status: 'validation_failed' }}
        articleLoading={false}
        onFetch={vi.fn()}
        onCancel={vi.fn()}
      />,
    )

    expect(screen.getByRole('alert')).toHaveTextContent('抓取内容未通过真实性校验')
    expect(screen.queryByRole('button', { name: '重试' })).not.toBeInTheDocument()
  })

  it('shows a retry action and the original article link after a fetch failure', () => {
    const onFetch = vi.fn()
    const sourceUrl = 'https://deepmind.google/blog/example/'

    render(
      <FullContentFetchStatus
        news={{ source_language: 'en', full_content: '', full_content_fetch_status: 'failed', url: sourceUrl }}
        articleLoading={false}
        onFetch={onFetch}
        onCancel={vi.fn()}
      />,
    )

    expect(screen.getByText('原文抓取失败，请稍后重试')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '阅读原文' })).toHaveAttribute('href', sourceUrl)
    fireEvent.click(screen.getByRole('button', { name: '重试' }))
    expect(onFetch).toHaveBeenCalledOnce()
  })

  it('shows a terminal fetch failure while preserving an existing article body', () => {
    render(
      <FullContentFetchStatus
        news={{ ...baseNews, full_content: 'Cached article body', full_content_fetch_status: 'network_error', full_content_fetch_error: 'source timed out' }}
        articleLoading={false}
        onFetch={vi.fn()}
        onCancel={vi.fn()}
      />,
    )

    expect(screen.getByRole('alert')).toHaveTextContent('source timed out')
    expect(screen.getByRole('alert')).toHaveTextContent('本次原文更新未完成')
    expect(screen.getByRole('alert')).toHaveTextContent('上次保存的正文仍可阅读')
    expect(screen.getByRole('alert')).not.toHaveTextContent('下方摘要')
  })

  it('offers to reattach to a server fetch after the user stops waiting', () => {
    const onFetch = vi.fn()
    const onResume = vi.fn()
    render(
      <FullContentFetchStatus
        news={{ source_language: 'en', full_content: '', full_content_fetch_status: 'fetching', url: 'https://example.com/article' }}
        articleLoading={false}
        onFetch={onFetch}
        onResume={onResume}
        onCancel={vi.fn()}
      />,
    )

    expect(screen.getByText(/不会重复发起抓取/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '继续查看' }))
    expect(onResume).toHaveBeenCalledWith()
    expect(onFetch).not.toHaveBeenCalled()
  })
})
