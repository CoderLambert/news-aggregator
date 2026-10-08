import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createElement } from 'react'
import { AuthContext } from '@/context/AuthContext'
import { useChat } from '@/hooks/useChat'

vi.mock('@/services/newsWorkflowApi', () => ({
  fetchChatHistory: vi.fn(),
  clearChatHistory: vi.fn(),
  chatStream: vi.fn(),
  parseWebSources: vi.fn(),
}))

import { fetchChatHistory, chatStream } from '@/services/newsWorkflowApi'

function makeWrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  return function Wrapper({ children }) {
    return createElement(QueryClientProvider, { client }, createElement(AuthContext.Provider, {
      value: { user: { id: 5, username: 'reader' }, loading: false, login: vi.fn(), register: vi.fn(), logout: vi.fn(), refresh: vi.fn() },
    }, children))
  }
}

describe('useChat phase machine', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    fetchChatHistory.mockResolvedValue({ messages: [] })
  })

  it('starts in loading-history then becomes idle', async () => {
    const { result } = renderHook(() => useChat(1, true), { wrapper: makeWrapper() })
    expect(result.current.phase).toBe('loading-history')
    await waitFor(() => expect(result.current.phase).toBe('idle'))
  })

  it('transitions idle → thinking → streaming → success → idle', async () => {
    let releaseFirst
    let releaseSecond
    chatStream.mockImplementation(async function* () {
      await new Promise((resolve) => { releaseFirst = resolve })
      yield 'Hello '
      await new Promise((resolve) => { releaseSecond = resolve })
      yield 'world'
    })
    const { result } = renderHook(() => useChat(1, true), { wrapper: makeWrapper() })
    await waitFor(() => expect(result.current.phase).toBe('idle'))
    act(() => result.current.setInput('hi'))
    let sendPromise
    act(() => { sendPromise = result.current.handleSend() })
    await waitFor(() => expect(result.current.phase).toBe('thinking'))
    act(() => releaseFirst())
    await waitFor(() => expect(result.current.phase).toBe('streaming'))
    act(() => releaseSecond())
    await act(async () => { await sendPromise })
    await waitFor(() => expect(result.current.phase).toBe('idle'), { timeout: 3000 })
  })

  it('keeps a failed request uncertain until the user explicitly resends it', async () => {
    chatStream
      // eslint-disable-next-line require-yield -- intentional: simulates a request that fails before its first token
      .mockImplementationOnce(async function* () { throw new Error('boom') })
      .mockImplementationOnce(async function* () { yield 'ok' })
    const { result } = renderHook(() => useChat(1, true), { wrapper: makeWrapper() })
    await waitFor(() => expect(result.current.phase).toBe('idle'))
    act(() => result.current.setInput('first'))
    await act(async () => { await result.current.handleSend() })
    expect(result.current.phase).toBe('error')
    expect(result.current.uncertainTurn?.reconciliation).toBe('unconfirmed')
    await expect(result.current.handleSend()).resolves.toBe(false)
    let resendPromise
    act(() => { resendPromise = result.current.resendUncertainTurn() })
    await waitFor(() => expect(result.current.phase).not.toBe('error'))
    await act(async () => { await resendPromise })
  })
})
