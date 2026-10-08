import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { act, renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createElement } from 'react'
import { AuthContext } from '@/context/AuthContext'
import { useSuggestedQuestions } from './useSuggestedQuestions'
import * as api from '@/services/newsWorkflowApi'

vi.mock('@/services/newsWorkflowApi', () => ({ fetchSuggestedQuestions: vi.fn() }))

function makeWrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  return function Wrapper({ children }) {
    return createElement(QueryClientProvider, { client }, createElement(AuthContext.Provider, {
      value: { user: { id: 5, username: 'reader' }, loading: false, login: vi.fn(), register: vi.fn(), logout: vi.fn(), refresh: vi.fn() },
    }, children))
  }
}

describe('useSuggestedQuestions', () => {
  beforeEach(() => vi.clearAllMocks())
  afterEach(() => vi.restoreAllMocks())

  it('does not request generated questions while the panel is closed', async () => {
    renderHook(() => useSuggestedQuestions('42', false), { wrapper: makeWrapper() })
    await new Promise((resolve) => setTimeout(resolve, 10))
    expect(api.fetchSuggestedQuestions).not.toHaveBeenCalled()
  })

  it('loads lazily once for a viewer/article and reuses the cached result when reopened', async () => {
    api.fetchSuggestedQuestions.mockResolvedValueOnce(['a', 'b', 'c'])
    const { result, rerender } = renderHook(({ enabled }) => useSuggestedQuestions('42', enabled), {
      initialProps: { enabled: false }, wrapper: makeWrapper(),
    })
    expect(result.current.questions).toEqual([])
    rerender({ enabled: true })
    await waitFor(() => expect(result.current.questions).toEqual(['a', 'b', 'c']))
    expect(api.fetchSuggestedQuestions).toHaveBeenCalledOnce()
    expect(api.fetchSuggestedQuestions).toHaveBeenCalledWith(42, { signal: expect.any(AbortSignal) })
    await act(async () => {
      rerender({ enabled: false })
      rerender({ enabled: true })
    })
    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(api.fetchSuggestedQuestions).toHaveBeenCalledOnce()
  })

  it('uses a separate query when the article changes', async () => {
    api.fetchSuggestedQuestions.mockResolvedValueOnce(['a']).mockResolvedValueOnce(['b'])
    const { result, rerender } = renderHook(({ id }) => useSuggestedQuestions(id, true), {
      initialProps: { id: '1' }, wrapper: makeWrapper(),
    })
    await waitFor(() => expect(result.current.questions).toEqual(['a']))
    rerender({ id: '2' })
    await waitFor(() => expect(result.current.questions).toEqual(['b']))
    expect(api.fetchSuggestedQuestions).toHaveBeenCalledTimes(2)
  })

  it('keeps empty fallbacks after failure and avoids automatic retries', async () => {
    api.fetchSuggestedQuestions.mockRejectedValueOnce(new Error('boom'))
    const { result, rerender } = renderHook(({ enabled }) => useSuggestedQuestions('42', enabled), {
      initialProps: { enabled: true }, wrapper: makeWrapper(),
    })
    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.questions).toEqual([])
    expect(result.current.error).toBeTruthy()
    rerender({ enabled: false })
    rerender({ enabled: true })
    await new Promise((resolve) => setTimeout(resolve, 10))
    expect(api.fetchSuggestedQuestions).toHaveBeenCalledOnce()
  })

  it('forces a new question request only after an explicit refresh', async () => {
    api.fetchSuggestedQuestions.mockResolvedValueOnce(['old1', 'old2', 'old3']).mockResolvedValueOnce(['new1', 'new2', 'new3'])
    const { result } = renderHook(() => useSuggestedQuestions('42', true), { wrapper: makeWrapper() })
    await waitFor(() => expect(result.current.questions).toEqual(['old1', 'old2', 'old3']))
    await result.current.refresh()
    await waitFor(() => expect(result.current.questions).toEqual(['new1', 'new2', 'new3']))
    expect(api.fetchSuggestedQuestions).toHaveBeenLastCalledWith(42, { force: true, signal: expect.any(AbortSignal) })
    expect(api.fetchSuggestedQuestions).toHaveBeenCalledTimes(2)
  })

  it('preserves old questions when explicit refresh fails and does nothing without an article', async () => {
    api.fetchSuggestedQuestions.mockResolvedValueOnce(['kept1', 'kept2']).mockRejectedValueOnce(new Error('llm down'))
    const { result } = renderHook(() => useSuggestedQuestions('42', true), { wrapper: makeWrapper() })
    await waitFor(() => expect(result.current.questions).toEqual(['kept1', 'kept2']))
    await result.current.refresh()
    expect(result.current.questions).toEqual(['kept1', 'kept2'])
    const missing = renderHook(() => useSuggestedQuestions(null, true), { wrapper: makeWrapper() })
    await missing.result.current.refresh()
    expect(api.fetchSuggestedQuestions).toHaveBeenCalledTimes(2)
  })
})
