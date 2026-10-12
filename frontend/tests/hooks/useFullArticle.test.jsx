import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'
import { QueryClient } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { AuthContext } from '@/context/AuthContext'
import { useFullArticle } from '@/hooks/useFullArticle'
import { fetchFullArticle, fetchFullArticleStatus } from '@/services/newsWorkflowApi'
import { CapabilitiesTestProvider, fullCapabilities } from '../helpers/capabilities'

vi.mock('@/services/newsWorkflowApi', async (importOriginal) => ({
  ...await importOriginal(),
  fetchFullArticle: vi.fn(),
  fetchFullArticleStatus: vi.fn(),
}))

function makeWrapper(getUser = () => ({ id: 12, username: 'reader' }), capabilities = fullCapabilities()) {
  return function Wrapper({ children }) {
    return (
      <CapabilitiesTestProvider value={capabilities}>
        <AuthContext.Provider value={{ user: getUser(), loading: false, login: vi.fn(), register: vi.fn(), logout: vi.fn(), refresh: vi.fn() }}>
          {children}
        </AuthContext.Provider>
      </CapabilitiesTestProvider>
    )
  }
}

function makeStrictWrapper(capabilities = fullCapabilities()) {
  return function StrictWrapper({ children }) {
    return (
      <StrictMode>
        <CapabilitiesTestProvider value={capabilities}>
          <AuthContext.Provider value={{ user: { id: 12, username: 'reader' }, loading: false, login: vi.fn(), register: vi.fn(), logout: vi.fn(), refresh: vi.fn() }}>
            {children}
          </AuthContext.Provider>
        </CapabilitiesTestProvider>
      </StrictMode>
    )
  }
}

describe('useFullArticle', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    window.sessionStorage.clear()
  })
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

  it('does not fetch or attach to an active full-content task when the capability is disabled', async () => {
    const news = { id: 7, full_content: '', full_content_fetch_status: 'fetching' }
    const setNews = vi.fn()
    const { result } = renderHook(() => useFullArticle(7, setNews, news), {
      wrapper: makeWrapper(() => ({ id: 12, username: 'reader' }), fullCapabilities({ fetch_full: false })),
    })

    await act(async () => { expect(await result.current.handleFetchFullArticle()).toBe(false) })
    expect(fetchFullArticle).not.toHaveBeenCalled()
    expect(fetchFullArticleStatus).not.toHaveBeenCalled()
  })

  it('aborts an in-flight full-content request when its capability turns off', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    let signal
    fetchFullArticle.mockImplementation((_id, _force, requestSignal) => {
      signal = requestSignal
      return new Promise(() => {})
    })
    function Wrapper({ children }) {
      return (
        <CapabilitiesTestProvider client={client}>
          <AuthContext.Provider value={{ user: { id: 12, username: 'reader' }, loading: false, login: vi.fn(), register: vi.fn(), logout: vi.fn(), refresh: vi.fn() }}>
            {children}
          </AuthContext.Provider>
        </CapabilitiesTestProvider>
      )
    }
    const { result } = renderHook(() => useFullArticle(7, vi.fn(), { id: 7, full_content: '' }), { wrapper: Wrapper })
    act(() => { void result.current.handleFetchFullArticle() })
    await waitFor(() => expect(fetchFullArticle).toHaveBeenCalledOnce())

    act(() => client.setQueryData(['capabilities'], fullCapabilities({ fetch_full: false })))
    await waitFor(() => expect(signal.aborted).toBe(true))
    expect(result.current.articleLoading).toBe(false)
  })

  it('automatically fetches an empty pending article once per tab session', async () => {
    fetchFullArticle.mockResolvedValue({
      full_content: 'Automatically fetched body',
      full_content_fetch_status: 'success',
      full_content_retry_count: 1,
    })
    const news = {
      id: 2341, source_language: 'zh', content: '', full_content: '', full_content_fetch_status: 'pending',
      full_content_retry_count: 0, last_full_content_attempt: null,
    }
    const setNews = vi.fn((updater) => updater(news))
    const { rerender } = renderHook(({ record }) => useFullArticle(record.id, setNews, record), {
      initialProps: { record: news }, wrapper: makeWrapper(),
    })

    await waitFor(() => expect(fetchFullArticle).toHaveBeenCalledTimes(1))
    rerender({ record: { ...news } })
    expect(fetchFullArticle).toHaveBeenCalledTimes(1)
    expect(fetchFullArticle).toHaveBeenCalledWith(2341, false, expect.any(AbortSignal))
  })

  it('still starts one auto-fetch under React StrictMode effect replay', async () => {
    fetchFullArticle.mockResolvedValue({ full_content: 'StrictMode body', full_content_fetch_status: 'success' })
    const news = {
      id: 2351, source_language: 'zh', content: '', full_content: '', full_content_fetch_status: 'pending',
      full_content_retry_count: 0, last_full_content_attempt: null,
    }
    const setNews = vi.fn((updater) => updater(news))

    renderHook(() => useFullArticle(2351, setNews, news), { wrapper: makeStrictWrapper() })

    await waitFor(() => expect(fetchFullArticle).toHaveBeenCalledTimes(1))
  })

  it('auto-fetches a pending full body even when a summary already exists', async () => {
    fetchFullArticle.mockResolvedValue({ full_content: 'Full body', full_content_fetch_status: 'success' })
    const news = {
      id: 3033, source_language: 'zh', content: 'Existing summary', full_content: '',
      full_content_fetch_status: 'pending', full_content_retry_count: 0, last_full_content_attempt: null,
    }
    const setNews = vi.fn((updater) => updater(news))

    renderHook(() => useFullArticle(news.id, setNews, news), { wrapper: makeWrapper() })

    await waitFor(() => expect(fetchFullArticle).toHaveBeenCalledOnce())
    expect(fetchFullArticle).toHaveBeenCalledWith(3033, false, expect.any(AbortSignal))
  })

  it('does not auto-fetch when the article already has a full body', () => {
    const news = {
      id: 2341, source_language: 'en', content: 'Summary', full_content: 'Cached body',
      full_content_fetch_status: 'success', full_content_retry_count: 0,
    }

    renderHook(() => useFullArticle(news.id, vi.fn(), news), { wrapper: makeWrapper() })

    expect(fetchFullArticle).not.toHaveBeenCalled()
  })

  it('reattaches to an active server fetch without posting another fetch request', async () => {
    fetchFullArticleStatus
      .mockResolvedValueOnce({ full_content: '', full_content_fetch_status: 'fetching' })
      .mockResolvedValueOnce({ full_content: 'Server result', full_content_fetch_status: 'success' })
    const news = { id: 2341, source_language: 'en', content: '', full_content: '', full_content_fetch_status: 'fetching' }
    const setNews = vi.fn((updater) => updater(news))

    renderHook(() => useFullArticle(2341, setNews, news), { wrapper: makeWrapper() })

    await waitFor(() => expect(fetchFullArticleStatus).toHaveBeenCalledTimes(2), { timeout: 3000 })
    expect(fetchFullArticle).not.toHaveBeenCalled()
    expect(setNews.mock.results.at(-1).value).toMatchObject({
      id: 2341, full_content: 'Server result', full_content_fetch_status: 'success',
    })
  })

  it('does not automatically restart after the user cancels waiting', async () => {
    let requestSignal
    fetchFullArticle.mockImplementation((_id, _force, signal) => {
      requestSignal = signal
      return new Promise(() => {})
    })
    const news = {
      id: 2342, source_language: 'en', content: '', full_content: '', full_content_fetch_status: 'pending',
      full_content_retry_count: 0, last_full_content_attempt: null,
    }
    const setNews = vi.fn()
    const { result, rerender } = renderHook(() => useFullArticle(2342, setNews, news), { wrapper: makeWrapper() })

    await waitFor(() => expect(requestSignal).toBeInstanceOf(AbortSignal))
    act(() => result.current.cancelFetch())
    rerender()

    expect(requestSignal.aborted).toBe(true)
    expect(fetchFullArticle).toHaveBeenCalledTimes(1)
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

  it('resets matching request state across an article 42 to 43 to 42 transition', async () => {
    const requests = []
    fetchFullArticle.mockImplementation((_id, _force, signal) => new Promise((resolve) => {
      requests.push({ resolve, signal })
    }))
    const setNews = vi.fn()
    const { result, rerender } = renderHook(({ id }) => useFullArticle(id, setNews), {
      initialProps: { id: '42' }, wrapper: makeWrapper(),
    })

    let firstRequest
    act(() => { firstRequest = result.current.handleFetchFullArticle() })
    await waitFor(() => expect(requests).toHaveLength(1))
    expect(result.current.articleLoading).toBe(true)

    rerender({ id: '43' })
    expect(requests[0].signal.aborted).toBe(true)
    expect(result.current.articleLoading).toBe(false)
    rerender({ id: '42' })
    expect(result.current.articleLoading).toBe(false)

    let secondRequest
    act(() => { secondRequest = result.current.handleFetchFullArticle() })
    await waitFor(() => expect(requests).toHaveLength(2))
    await act(async () => {
      requests[0].resolve({ full_content: 'late first owner response' })
      await firstRequest
    })
    expect(setNews).not.toHaveBeenCalled()
    expect(result.current.articleLoading).toBe(true)

    await act(async () => {
      requests[1].resolve({ full_content: 'current article body' })
      await secondRequest
    })
    expect(setNews).toHaveBeenCalledOnce()
    expect(result.current.articleLoading).toBe(false)
  })

  it('resets matching request state for account A to B to A and rejects the late A response', async () => {
    let currentUser = { id: 12, username: 'reader-a' }
    const requests = []
    fetchFullArticle.mockImplementation((_id, _force, signal) => new Promise((resolve) => {
      requests.push({ resolve, signal })
    }))
    const setNews = vi.fn((updater) => updater({ id: 42 }))
    const { result, rerender } = renderHook(() => useFullArticle('42', setNews), {
      wrapper: makeWrapper(() => currentUser),
    })

    let firstRequest
    act(() => { firstRequest = result.current.handleFetchFullArticle() })
    await waitFor(() => expect(requests).toHaveLength(1))
    currentUser = { id: 13, username: 'reader-b' }
    rerender()
    expect(requests[0].signal.aborted).toBe(true)
    expect(result.current.articleLoading).toBe(false)

    currentUser = { id: 12, username: 'reader-a' }
    rerender()
    expect(result.current.articleLoading).toBe(false)
    let secondRequest
    act(() => { secondRequest = result.current.handleFetchFullArticle() })
    await waitFor(() => expect(requests).toHaveLength(2))

    await act(async () => {
      requests[0].resolve({ full_content: 'late A response' })
      await firstRequest
    })
    expect(setNews).not.toHaveBeenCalled()
    expect(result.current.articleLoading).toBe(true)
    await act(async () => {
      requests[1].resolve({ full_content: 'current A response' })
      await secondRequest
    })
    expect(setNews).toHaveBeenCalledOnce()
    expect(result.current.articleLoading).toBe(false)
  })

  it('preserves the cached body and translation when a forced fetch fails after returning 202', async () => {
    let currentNews = {
      id: 7, source_language: 'en', full_content: 'old body', full_content_zh: 'old translation',
      full_content_zh_fetched_at: 'old date', full_content_fetch_status: 'success',
    }
    fetchFullArticle.mockResolvedValue({ full_content: 'old body', full_content_fetch_status: 'fetching' })
    fetchFullArticleStatus.mockResolvedValue({
      full_content: 'old body', full_content_fetch_status: 'network_error', full_content_fetch_error: 'source timed out',
    })
    const setNews = vi.fn((updater) => {
      currentNews = typeof updater === 'function' ? updater(currentNews) : updater
      return currentNews
    })
    const { result } = renderHook(() => useFullArticle(7, setNews, currentNews), { wrapper: makeWrapper() })

    await act(async () => { await result.current.handleFetchFullArticle(true) })

    expect(fetchFullArticle).toHaveBeenCalledWith(7, true, expect.any(AbortSignal))
    expect(currentNews).toMatchObject({
      full_content: 'old body', full_content_zh: 'old translation', full_content_zh_fetched_at: 'old date',
      full_content_fetch_status: 'network_error',
    })
    expect(result.current.articleError).toBe('source timed out')
  })

  it('resumes a stopped forced fetch with status GETs only and clears translation when the body changed', async () => {
    let currentNews = {
      id: 7, source_language: 'en', content: 'summary', full_content: 'old body',
      full_content_zh: 'old translation', full_content_zh_fetched_at: 'old date', full_content_fetch_status: 'success',
    }
    let resolveFirstStatus
    fetchFullArticle.mockResolvedValue({ full_content: 'old body', full_content_fetch_status: 'fetching' })
    fetchFullArticleStatus
      .mockImplementationOnce(() => new Promise((resolve) => { resolveFirstStatus = resolve }))
      .mockResolvedValueOnce({ full_content: 'updated body', full_content_fetch_status: 'success' })
    const setNews = vi.fn((updater) => {
      currentNews = typeof updater === 'function' ? updater(currentNews) : updater
      return currentNews
    })
    const { result } = renderHook(() => useFullArticle(7, setNews, currentNews), { wrapper: makeWrapper() })

    let pendingRequest
    act(() => { pendingRequest = result.current.handleFetchFullArticle(true) })
    await waitFor(() => expect(fetchFullArticleStatus).toHaveBeenCalledOnce())
    act(() => result.current.cancelFetch())
    await act(async () => {
      resolveFirstStatus({ full_content: 'old body', full_content_fetch_status: 'fetching' })
      await pendingRequest
    })

    await act(async () => { await result.current.resumeExistingFetch() })

    expect(fetchFullArticle).toHaveBeenCalledWith(7, true, expect.any(AbortSignal))
    expect(fetchFullArticle).toHaveBeenCalledOnce()
    expect(fetchFullArticleStatus).toHaveBeenCalledTimes(2)
    expect(currentNews).toMatchObject({
      full_content: 'updated body', full_content_zh: '', full_content_zh_fetched_at: null,
      full_content_fetch_status: 'success',
    })
  })

  it('keeps the cached translation when a stopped forced fetch resumes to a failure', async () => {
    let currentNews = {
      id: 7, source_language: 'en', content: 'summary', full_content: 'old body',
      full_content_zh: 'old translation', full_content_zh_fetched_at: 'old date', full_content_fetch_status: 'success',
    }
    let resolveFirstStatus
    fetchFullArticle.mockResolvedValue({ full_content: 'old body', full_content_fetch_status: 'fetching' })
    fetchFullArticleStatus
      .mockImplementationOnce(() => new Promise((resolve) => { resolveFirstStatus = resolve }))
      .mockResolvedValueOnce({
        full_content: 'old body', full_content_fetch_status: 'network_error', full_content_fetch_error: 'source unavailable',
      })
    const setNews = vi.fn((updater) => {
      currentNews = typeof updater === 'function' ? updater(currentNews) : updater
      return currentNews
    })
    const { result } = renderHook(() => useFullArticle(7, setNews, currentNews), { wrapper: makeWrapper() })

    let pendingRequest
    act(() => { pendingRequest = result.current.handleFetchFullArticle(true) })
    await waitFor(() => expect(fetchFullArticleStatus).toHaveBeenCalledOnce())
    act(() => result.current.cancelFetch())
    await act(async () => {
      resolveFirstStatus({ full_content: 'old body', full_content_fetch_status: 'fetching' })
      await pendingRequest
    })

    await act(async () => { await result.current.resumeExistingFetch() })

    expect(fetchFullArticle).toHaveBeenCalledWith(7, true, expect.any(AbortSignal))
    expect(fetchFullArticle).toHaveBeenCalledOnce()
    expect(fetchFullArticleStatus).toHaveBeenCalledTimes(2)
    expect(currentNews).toMatchObject({
      full_content: 'old body', full_content_zh: 'old translation', full_content_zh_fetched_at: 'old date',
      full_content_fetch_status: 'network_error',
    })
    expect(result.current.articleError).toBe('source unavailable')
  })

  it('treats a click event passed to the handler as a non-forced fetch', async () => {
    fetchFullArticle.mockResolvedValue({ full_content: 'body', full_content_fetch_status: 'success' })
    const { result } = renderHook(() => useFullArticle(7, vi.fn()), { wrapper: makeWrapper() })

    await act(async () => { await result.current.handleFetchFullArticle({ type: 'click' }) })

    expect(fetchFullArticle).toHaveBeenCalledWith(7, false, expect.any(AbortSignal))
  })

  it('invalidates the cached translation only after a successful forced full fetch', async () => {
    fetchFullArticle.mockResolvedValue({ full_content: 'refreshed body', full_content_fetch_status: 'success' })
    const setNews = vi.fn((updater) => updater({
      id: 7, full_content: 'old body', full_content_zh: 'old translation', full_content_zh_fetched_at: 'old date',
    }))
    const { result } = renderHook(() => useFullArticle(7, setNews), { wrapper: makeWrapper() })
    await act(async () => { await result.current.handleFetchFullArticle(true) })
    expect(setNews.mock.results[0].value).toMatchObject({
      full_content: 'refreshed body', full_content_zh: '', full_content_zh_fetched_at: null,
    })
  })

  it('keeps a translation after a successful forced fetch when the body is unchanged', async () => {
    fetchFullArticle.mockResolvedValue({ full_content: 'same body', full_content_fetch_status: 'success' })
    const setNews = vi.fn((updater) => updater({
      id: 7, full_content: 'same body', full_content_zh: 'valid translation', full_content_zh_fetched_at: 'saved date',
    }))
    const { result } = renderHook(() => useFullArticle(7, setNews), { wrapper: makeWrapper() })

    await act(async () => { await result.current.handleFetchFullArticle(true) })

    expect(setNews.mock.results[0].value).toMatchObject({
      full_content: 'same body', full_content_zh: 'valid translation', full_content_zh_fetched_at: 'saved date',
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
