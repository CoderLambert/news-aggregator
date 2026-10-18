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
  cancelChatTurn: vi.fn(),
  parseWebSources: vi.fn(),
}))
let testViewerId = 9
function wrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  return function Harness({ children }) {
    return createElement(QueryClientProvider, { client }, createElement(AuthContext.Provider, {
      value: { user: { id: testViewerId, username: 'synthetic-reader' }, loading: false,
        login: vi.fn(), register: vi.fn(), logout: vi.fn(), refresh: vi.fn() },
    }, children))
  }
}
function deferred() {
  let resolve
  const promise = new Promise((done) => { resolve = done })
  return { promise, resolve }
}
describe('T04 explicit BYOK turns in useChat', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    testViewerId = 9
    api.fetchChatHistory.mockResolvedValue({ messages: [] })
    api.clearChatHistory.mockResolvedValue(undefined)
    api.cancelChatTurn.mockResolvedValue('cancelled')
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
    expect(args[2]).toMatchObject({ modelConfigId: model, billingConsent: true, turnId: expect.any(String), webSearch: false, signal: expect.any(AbortSignal) })
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

  it('waits for cancellation receipt before clearing and lets an already-completed turn clear safely', async () => {
    const model = '22222222-2222-4222-8222-222222222222'
    const cancellation = deferred()
    api.cancelChatTurn.mockReturnValue(cancellation.promise)
    api.chatStream.mockImplementation(async function* (_id, _question, options) {
      yield ''
      await new Promise((resolve) => {
        if (options.signal.aborted) resolve()
        else options.signal.addEventListener('abort', resolve, { once: true })
      })
    })
    const hook = renderHook(() => useChat(81, true, model, true), { wrapper: wrapper() })
    await waitFor(() => expect(hook.result.current.isLoading).toBe(false))
    act(() => hook.result.current.setInput('Potentially billable question'))
    act(() => { void hook.result.current.handleSend() })
    await waitFor(() => expect(api.chatStream).toHaveBeenCalledOnce())
    const turnId = api.chatStream.mock.calls[0][2].turnId

    act(() => hook.result.current.requestClearChat())
    let clearResult
    act(() => { clearResult = hook.result.current.confirmClear() })
    await waitFor(() => expect(api.cancelChatTurn).toHaveBeenCalledWith(81, turnId))
    expect(api.clearChatHistory).not.toHaveBeenCalled()

    await act(async () => {
      cancellation.resolve('already_completed')
      expect(await clearResult).toBe(true)
    })
    expect(api.clearChatHistory).toHaveBeenCalledOnce()
    expect(hook.result.current.messages).toEqual([])
  })

  it('keeps clear and uncertain-turn state when cancellation outcome is unknown', async () => {
    const model = '22222222-2222-4222-8222-222222222222'
    api.cancelChatTurn.mockRejectedValueOnce(new Error('network lost'))
    api.chatStream.mockImplementation(async function* (_id, _question, options) {
      yield ''
      await new Promise((resolve) => {
        if (options.signal.aborted) resolve()
        else options.signal.addEventListener('abort', resolve, { once: true })
      })
    })
    const hook = renderHook(() => useChat(81, true, model, true), { wrapper: wrapper() })
    await waitFor(() => expect(hook.result.current.isLoading).toBe(false))
    act(() => hook.result.current.setInput('Uncertain billable question'))
    act(() => { void hook.result.current.handleSend() })
    await waitFor(() => expect(api.chatStream).toHaveBeenCalledOnce())

    act(() => hook.result.current.requestClearChat())
    let clearResult
    act(() => { clearResult = hook.result.current.confirmClear() })
    await act(async () => expect(await clearResult).toBe(false))

    expect(api.clearChatHistory).not.toHaveBeenCalled()
    expect(hook.result.current.clearError).toMatch(/无法确认服务端/)
    expect(api.chatStream).toHaveBeenCalledOnce()
    expect(hook.result.current.messages.some((message) => message.role === 'user')).toBe(true)
  })

  it('best-effort cancels an in-flight personal turn when the hook unmounts', async () => {
    const model = '22222222-2222-4222-8222-222222222222'
    api.chatStream.mockImplementation(async function* (_id, _question, options) {
      yield ''
      await new Promise((resolve) => {
        if (options.signal.aborted) resolve()
        else options.signal.addEventListener('abort', resolve, { once: true })
      })
    })
    const hook = renderHook(() => useChat(81, true, model, true), { wrapper: wrapper() })
    await waitFor(() => expect(hook.result.current.isLoading).toBe(false))
    act(() => hook.result.current.setInput('Unmounted paid turn'))
    act(() => { void hook.result.current.handleSend() })
    await waitFor(() => expect(api.chatStream).toHaveBeenCalledOnce())
    const turnId = api.chatStream.mock.calls[0][2].turnId

    hook.unmount()
    expect(api.cancelChatTurn).toHaveBeenCalledWith(81, turnId)
  })

  it('does not send an old viewer turn cancellation after a viewer switch', async () => {
    const model = '22222222-2222-4222-8222-222222222222'
    api.chatStream.mockImplementation(async function* (_id, _question, options) {
      yield ''
      await new Promise((resolve) => {
        if (options.signal.aborted) resolve()
        else options.signal.addEventListener('abort', resolve, { once: true })
      })
    })
    const hook = renderHook(() => useChat(81, true, model, true), { wrapper: wrapper() })
    await waitFor(() => expect(hook.result.current.isLoading).toBe(false))
    act(() => hook.result.current.setInput('Old viewer turn'))
    act(() => { void hook.result.current.handleSend() })
    await waitFor(() => expect(api.chatStream).toHaveBeenCalledOnce())
    const signal = api.chatStream.mock.calls[0][2].signal

    testViewerId = 10
    hook.rerender()
    await waitFor(() => expect(signal.aborted).toBe(true))
    expect(api.cancelChatTurn).not.toHaveBeenCalled()
    hook.unmount()
    expect(api.cancelChatTurn).not.toHaveBeenCalled()
  })
})
