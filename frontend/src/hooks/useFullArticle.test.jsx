import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'

import { useFullArticle } from './useFullArticle'
import { fetchFullArticle } from '../services/api'

vi.mock('../services/api', () => ({
  fetchFullArticle: vi.fn(),
}))

describe('useFullArticle', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('merges full-content fetch metadata on success', async () => {
    fetchFullArticle.mockResolvedValue({
      full_content: 'Real full article body',
      full_content_fetched_at: '2026-01-01T00:00:00Z',
      full_content_fetch_status: 'success',
      full_content_fetch_error: '',
      full_content_fetch_provider: 'jina',
      full_content_fetch_quality: 0.92,
      full_content_fetch_retry_count: 1,
      full_content_fetch_last_attempt: '2026-01-01T00:00:00Z',
    })
    const setNews = vi.fn(updater => updater({ id: 7, title: 'Existing' }))
    const { result } = renderHook(() => useFullArticle(7, setNews))

    await act(async () => {
      await result.current.handleFetchFullArticle()
    })

    expect(setNews).toHaveBeenCalledWith(expect.any(Function))
    expect(setNews.mock.results[0].value).toMatchObject({
      id: 7,
      title: 'Existing',
      full_content: 'Real full article body',
      full_content_fetched_at: '2026-01-01T00:00:00Z',
      full_content_fetch_status: 'success',
      full_content_fetch_error: '',
      full_content_fetch_provider: 'jina',
      full_content_fetch_quality: 0.92,
      full_content_fetch_retry_count: 1,
      full_content_fetch_last_attempt: '2026-01-01T00:00:00Z',
    })
    expect(result.current.articleError).toBe('')
  })

  it('merges backend status metadata from failed responses while preserving articleError', async () => {
    fetchFullArticle.mockRejectedValue({
      response: {
        data: {
          error: '源站超时',
          full_content_fetch_status: 'network_error',
          full_content_fetch_error: 'timeout',
          full_content_fetch_provider: 'scrapy',
          full_content_fetch_quality: 0,
          full_content_fetch_retry_count: 2,
          full_content_fetch_last_attempt: '2026-01-02T00:00:00Z',
        },
      },
    })
    const setNews = vi.fn(updater => updater({ id: 8, title: 'Existing' }))
    const { result } = renderHook(() => useFullArticle(8, setNews))

    await act(async () => {
      await result.current.handleFetchFullArticle()
    })

    await waitFor(() => expect(result.current.articleError).toBe('源站超时'))
    expect(setNews.mock.results[0].value).toMatchObject({
      id: 8,
      full_content_fetch_status: 'network_error',
      full_content_fetch_error: 'timeout',
      full_content_fetch_provider: 'scrapy',
      full_content_fetch_quality: 0,
      full_content_fetch_retry_count: 2,
      full_content_fetch_last_attempt: '2026-01-02T00:00:00Z',
    })
  })
})
