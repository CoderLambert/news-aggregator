import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'
import { AuthContext } from '@/context/AuthContext'
import { useFullArticle } from './useFullArticle'
import { fetchFullArticle } from '@/services/newsWorkflowApi'

vi.mock('@/services/newsWorkflowApi', async (importOriginal) => ({
  ...await importOriginal(),
  fetchFullArticle: vi.fn(),
}))

function makeWrapper(getUser = () => ({ id: 12, username: 'reader' })) {
  return function Wrapper({ children }) {
    return (
      <AuthContext.Provider value={{ user: getUser(), loading: false, login: vi.fn(), register: vi.fn(), logout: vi.fn(), refresh: vi.fn() }}>
        {children}
      </AuthContext.Provider>
    )
  }
}

describe('useFullArticle', () => {
  beforeEach(() => vi.clearAllMocks())
  afterEach(() => vi.restoreAllMocks())

  it('merges the fetched body and supported metadata into the matching detail', async () => {
    fetchFullArticle.mockResolvedValue({
      full_content: 'Real full article body',
      full_content_fetched_at: '2026-01-01T00:00:00Z',
      full_content_fetch_status: 'success',
      full_content_fetch_error: '',
      full_content_fetch_provider: 'jina',
      full_content_quality_score: 0.92,
      full_content_retry_count: 1,
      last_full_content_attempt: '2026-01-01T00:00:00Z',
    })
    const setNews = vi.fn((updater) => updater({ id: 7, title: 'Existing' }))
    const { result } = renderHook(() => useFullArticle(7, setNews), { wrapper: makeWrapper() })

    await act(async () => { await result.current.handleFetchFullArticle() })

    expect(fetchFullArticle).toHaveBeenCalledWith(7, false, expect.any(AbortSignal))
    expect(setNews.mock.results[0].value).toMatchObject({
      id: 7, title: 'Existing', full_content: 'Real full article body',
      full_content_fetched_at: '2026-01-01T00:00:00Z', full_content_fetch_status: 'success',
      full_content_quality_score: 0.92,
    })
    expect(result.current.articleError).toBe('')
  })

  it('preserves fetch metadata from an API failure without replacing article content', async () => {
    fetchFullArticle.mockRejectedValue(Object.assign(new Error('request failed'), {
      isAxiosError: true,
      response: { data: {
        error: '源站超时', full_content_fetch_status: 'network_error', full_content_fetch_error: 'timeout',
        full_content_fetch_provider: 'scrapy', full_content_quality_score: 0, full_content_retry_count: 2,
        last_full_content_attempt: '2026-01-02T00:00:00Z',
      } },
    }))
    const setNews = vi.fn((updater) => updater({ id: 8, title: 'Existing', full_content: 'kept' }))
    const { result } = renderHook(() => useFullArticle(8, setNews), { wrapper: makeWrapper() })

    await act(async () => { await result.current.handleFetchFullArticle() })

    expect(result.current.articleError).toBe('源站超时')
    expect(setNews.mock.results[0].value).toMatchObject({
      id: 8, full_content: 'kept', full_content_fetch_status: 'network_error',
      full_content_fetch_error: 'timeout', full_content_fetch_provider: 'scrapy',
      full_content_quality_score: 0, full_content_retry_count: 2,
    })
  })

  it('cancels on account switch and ignores a late response from the previous viewer', async () => {
    let currentUser = { id: 12, username: 'reader-a' }
    let resolveRequest
    let requestSignal
    fetchFullArticle.mockImplementation((_id, _force, signal) => {
      requestSignal = signal
      return new Promise((resolve) => { resolveRequest = resolve })
    })
    const setNews = vi.fn()
    const { result, rerender } = renderHook(({ id }) => useFullArticle(id, setNews), {
      initialProps: { id: '42' }, wrapper: makeWrapper(() => currentUser),
    })

    let request
    act(() => { request = result.current.handleFetchFullArticle() })
    await waitFor(() => expect(requestSignal).toBeInstanceOf(AbortSignal))
    currentUser = { id: 13, username: 'reader-b' }
    rerender({ id: '42' })

    expect(requestSignal.aborted).toBe(true)
    await act(async () => {
      resolveRequest({ full_content: 'late article', full_content_fetch_status: 'success' })
      await request
    })
    expect(setNews).not.toHaveBeenCalled()
    expect(result.current.articleLoading).toBe(false)
  })

  it('aborts a fetch when the route changes to another article', async () => {
    let resolveRequest
    let requestSignal
    fetchFullArticle.mockImplementation((_id, _force, signal) => {
      requestSignal = signal
      return new Promise((resolve) => { resolveRequest = resolve })
    })
    const setNews = vi.fn()
    const { result, rerender } = renderHook(({ id }) => useFullArticle(id, setNews), {
      initialProps: { id: '42' }, wrapper: makeWrapper(),
    })
    let request
    act(() => { request = result.current.handleFetchFullArticle() })
    await waitFor(() => expect(requestSignal).toBeInstanceOf(AbortSignal))
    rerender({ id: '43' })
    expect(requestSignal.aborted).toBe(true)
    await act(async () => {
      resolveRequest({ full_content: 'article 42', full_content_fetch_status: 'success' })
      await request
    })
    expect(setNews).not.toHaveBeenCalled()
    expect(result.current.articleLoading).toBe(false)
  })

  it('invalidates the cached translation only after a successful forced full fetch', async () => {
    fetchFullArticle.mockResolvedValue({ full_content: 'refreshed body' })
    const setNews = vi.fn((updater) => updater({
      id: 7, full_content: 'old body', full_content_zh: 'old translation', full_content_zh_fetched_at: 'old date',
    }))
    const { result } = renderHook(() => useFullArticle(7, setNews), { wrapper: makeWrapper() })
    await act(async () => { await result.current.handleFetchFullArticle(true) })
    expect(setNews.mock.results[0].value).toMatchObject({
      full_content: 'refreshed body', full_content_zh: '', full_content_zh_fetched_at: null,
    })
  })

  it('does not turn a repeated click into cancellation, and cancelFetch aborts explicitly', async () => {
    let requestSignal
    fetchFullArticle.mockImplementation((_id, _force, signal) => {
      requestSignal = signal
      return new Promise(() => {})
    })
    const { result } = renderHook(() => useFullArticle(7, vi.fn()), { wrapper: makeWrapper() })
    act(() => { void result.current.handleFetchFullArticle() })
    await waitFor(() => expect(requestSignal).toBeInstanceOf(AbortSignal))
    await expect(result.current.handleFetchFullArticle()).resolves.toBe(false)
    expect(requestSignal.aborted).toBe(false)
    act(() => result.current.cancelFetch())
    expect(requestSignal.aborted).toBe(true)
    expect(result.current.articleLoading).toBe(false)
  })
})
