import { describe, it, beforeEach, expect, vi } from 'vitest'
import { act, renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createElement } from 'react'
import { AuthContext } from '@/context/AuthContext'
import { useChat } from '@/hooks/useChat'
import * as api from '@/services/newsWorkflowApi'

vi.mock('@/services/newsWorkflowApi', () => ({
  fetchChatHistory: vi.fn(),
  clearChatHistory: vi.fn(),
  chatStream: vi.fn(),
  parseWebSources: vi.fn(),
}))
function wrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  return function Harness({ children }) {
    return createElement(QueryClientProvider, { client }, createElement(AuthContext.Provider, {
      value: { user: { id: 9, username: 'synthetic-reader' }, loading: false,
        login: vi.fn(), register: vi.fn(), logout: vi.fn(), refresh: vi.fn() },
    }, children))
  }
}
describe('T04 explicit BYOK turns in useChat', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.fetchChatHistory.mockResolvedValue({ messages: [] })
    api.clearChatHistory.mockResolvedValue(undefined)
  })
  it('does not send or bill a selected model before per-turn consent and uses only one selected ID', async () => {
    const model = '22222222-2222-4222-8222-222222222222'
    api.chatStream.mockImplementation(async function* () {
      yield '\u200b__META__{"type":"chat_model","model_source":{"provider":"deepseek","model":"Verified"}}__META__\n\n'
      yield 'A verified complete answer'
      yield '\u200b__META__{"type":"chat_turn","status":"complete"}__META__\n\n'
    })
    const result = renderHook(
      ({ consent }) => useChat(81, true, model, consent),
      { wrapper: wrapper(), initialProps: { consent: false } },
    )
    await waitFor(() => expect(result.result.current.isLoading).toBe(false))
    act(() => result.result.current.setInput('Explicit personal model question'))
    await act(async () => { expect(await result.result.current.handleSend()).toBe(false) })
    expect(api.chatStream).not.toHaveBeenCalled()
    result.rerender({ consent: true })
    await act(async () => { expect(await result.result.current.handleSend()).toBe(true) })
    expect(api.chatStream).toHaveBeenCalledOnce()
    const args = api.chatStream.mock.calls[0]
    expect(args[0]).toBe(81)
    expect(args[1]).toBe('Explicit personal model question')
    expect(args[2]).toMatchObject({ modelConfigId: model, billingConsent: true, webSearch: false, signal: expect.any(AbortSignal) })
    expect(result.result.current.messages[1]).toMatchObject({
      status: 'complete', content: 'A verified complete answer',
      model_source: { provider: 'deepseek', model: 'Verified' },
    })
  })
  it('never silently binds the stored personal preference for the original non-BYOK path', async () => {
    api.chatStream.mockImplementation(async function* () {
      yield 'Original answer'
      yield '\u200b__META__{"type":"chat_turn","status":"complete"}__META__\n\n'
    })
    const hook = renderHook(() => useChat(81, true), { wrapper: wrapper() })
    await waitFor(() => expect(hook.result.current.isLoading).toBe(false))
    act(() => hook.result.current.setInput('No personal model selected'))
    await act(async () => { expect(await hook.result.current.handleSend()).toBe(true) })
    expect(api.chatStream).toHaveBeenCalledOnce()
    expect(api.chatStream.mock.calls[0][2]).not.toHaveProperty('modelConfigId')
  })
})
