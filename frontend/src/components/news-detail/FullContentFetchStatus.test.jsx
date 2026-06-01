import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

import FullContentFetchStatus from './FullContentFetchStatus'

describe('FullContentFetchStatus', () => {
  const baseNews = { source_language: 'en', full_content: '' }

  it('shows pending CTA without rendering summary as original article', () => {
    const onFetch = vi.fn()
    render(
      <FullContentFetchStatus
        news={{ ...baseNews, content: 'Summary must not appear as original', full_content_fetch_status: 'pending' }}
        articleLoading={false}
        onFetch={onFetch}
      />,
    )

    expect(screen.getByText('获取完整原文')).toBeInTheDocument()
    expect(screen.queryByText('Summary must not appear as original')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '加载原文' }))
    expect(onFetch).toHaveBeenCalledTimes(1)
  })

  it('shows fetching loading state', () => {
    render(
      <FullContentFetchStatus
        news={{ ...baseNews, full_content_fetch_status: 'fetching' }}
        articleLoading={false}
        onFetch={vi.fn()}
      />,
    )

    expect(screen.getByText(/正在获取原文内容/)).toBeInTheDocument()
  })

  it('shows network error copy with retry button', () => {
    const onFetch = vi.fn()
    render(
      <FullContentFetchStatus
        news={{ ...baseNews, full_content_fetch_status: 'network_error' }}
        articleLoading={false}
        onFetch={onFetch}
      />,
    )

    expect(screen.getByRole('alert')).toHaveTextContent('网络或源站暂不可达，可稍后重试')
    fireEvent.click(screen.getByRole('button', { name: '重试' }))
    expect(onFetch).toHaveBeenCalledTimes(1)
  })

  it('shows validation failure copy without forcing retry', () => {
    render(
      <FullContentFetchStatus
        news={{ ...baseNews, full_content_fetch_status: 'validation_failed' }}
        articleLoading={false}
        onFetch={vi.fn()}
      />,
    )

    expect(screen.getByRole('alert')).toHaveTextContent('抓取内容未通过真实性校验，等待规则优化')
    expect(screen.queryByRole('button', { name: '重试' })).not.toBeInTheDocument()
  })

  it('shows generic failure with retry', () => {
    render(
      <FullContentFetchStatus
        news={{ ...baseNews, full_content_fetch_status: 'failed' }}
        articleLoading={false}
        onFetch={vi.fn()}
      />,
    )

    expect(screen.getByRole('alert')).toHaveTextContent('原文抓取失败，请稍后重试')
    expect(screen.getByRole('button', { name: '重试' })).toBeInTheDocument()
  })
})
