import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import { AuthContext } from '@/context/AuthContext'
import { usePreferencesStore } from '@/stores/preferences'
import { useNewsDetail } from './useNewsDetail'
import * as api from '@/services/api'

const story = (id, title) => ({
  id, title, content: 'summary', title_zh: '', content_zh: '', author: null,
  publish_time: '2026-10-06T09:00:00Z', source: 8, source_name: 'Example source', source_type: 'news',
  source_language: 'en', category: 2, category_name: 'Technology', url: 'https://example.com/story', cover_image: null,
  created_at: '2026-10-06T09:00:00Z', related_to: null, translation_status: '', translation_error: '',
  translation_retry_count: 0, full_content_fetch_status: '', full_content_fetch_error: '', full_content_fetch_provider: '',
  full_content_quality_score: null, full_content_retry_count: 0, last_full_content_attempt: null,
  source_url: 'https://example.com/story', full_content: '', full_content_fetched_at: null,
  full_content_zh: '', full_content_zh_fetched_at: null, full_content_zh_source: null, full_translation_active: false,
})

function makeWrapper(client, getUser = () => ({ id: 12, username: 'reader' })) {
  return function Wrapper({ children }) {
    return (
      <QueryClientProvider client={client}>
        <AuthContext.Provider value={{ user: getUser(), loading: false, login: vi.fn(), register: vi.fn(), logout: vi.fn(), refresh: vi.fn() }}>
          {children}
        </AuthContext.Provider>
      </QueryClientProvider>
    )
  }
}

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 30_000 }, mutations: { retry: false } } })
}

describe('useNewsDetail', () => {
  beforeEach(() => {
    usePreferencesStore.setState({ lang: 'zh' })
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('loads typed detail and forwards query cancellation to the API request', async () => {
    const fetch = vi.spyOn(api, 'fetchNewsDetail').mockResolvedValueOnce(story(42, 'Hello'))
    const client = makeClient()
    const { result } = renderHook(() => useNewsDetail('42'), { wrapper: makeWrapper(client) })

    await waitFor(() => expect(result.current.news?.title).toBe('Hello'))
    expect(fetch).toHaveBeenCalledWith(42, expect.any(AbortSignal))
    expect(result.current.news).toMatchObject({ id: 42, title: 'Hello', full_content: '' })
  })

  it('uses language in the detail cache identity and loads the changed language', async () => {
    const fetch = vi.spyOn(api, 'fetchNewsDetail')
      .mockResolvedValueOnce(story(42, '中文标题'))
      .mockResolvedValueOnce(story(42, 'English title'))
    const client = makeClient()
    const { result } = renderHook(() => useNewsDetail('42'), { wrapper: makeWrapper(client) })

    await waitFor(() => expect(result.current.news?.title).toBe('中文标题'))
    act(() => usePreferencesStore.getState().setLang('en'))
    await waitFor(() => expect(result.current.news?.title).toBe('English title'))
    expect(fetch).toHaveBeenCalledTimes(2)
  })

  it('allows stream hooks to patch only the current query detail cache', async () => {
    vi.spyOn(api, 'fetchNewsDetail').mockResolvedValueOnce(story(1, 'A'))
    const client = makeClient()
    const { result } = renderHook(() => useNewsDetail('1'), { wrapper: makeWrapper(client) })
    await waitFor(() => expect(result.current.news?.title).toBe('A'))

    act(() => result.current.setNews((previous) => previous && { ...previous, full_content: 'Fetched body' }))
    await waitFor(() => expect(result.current.news).toMatchObject({ title: 'A', full_content: 'Fetched body' }))
  })

  it('does not show a previous viewer detail while the new viewer request is pending', async () => {
    let currentUser = { id: 12, username: 'reader-a' }
    const pending = []
    vi.spyOn(api, 'fetchNewsDetail').mockImplementation(() => new Promise((resolve) => pending.push(resolve)))
    const client = makeClient()
    const { result, rerender } = renderHook(() => useNewsDetail('42'), { wrapper: makeWrapper(client, () => currentUser) })

    await waitFor(() => expect(pending).toHaveLength(1))
    await act(async () => pending.shift()?.(story(42, 'Viewer A article')))
    await waitFor(() => expect(result.current.news?.title).toBe('Viewer A article'))

    currentUser = { id: 13, username: 'reader-b' }
    rerender()
    expect(result.current.news).toBeNull()
    await waitFor(() => expect(pending).toHaveLength(1))
    await act(async () => pending.shift()?.(story(42, 'Viewer B article')))
    await waitFor(() => expect(result.current.news?.title).toBe('Viewer B article'))
  })

  it('aborts a pending detail request when the hook unmounts', async () => {
    let requestSignal
    vi.spyOn(api, 'fetchNewsDetail').mockImplementation((_id, signal) => {
      requestSignal = signal
      return new Promise(() => {})
    })
    const client = makeClient()
    const { unmount } = renderHook(() => useNewsDetail('99'), { wrapper: makeWrapper(client) })
    await waitFor(() => expect(requestSignal).toBeInstanceOf(AbortSignal))

    unmount()
    expect(requestSignal.aborted).toBe(true)
  })
})
