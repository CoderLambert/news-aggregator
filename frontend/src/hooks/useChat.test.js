import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createElement } from 'react'
import { AuthContext } from '@/context/AuthContext'
import { useChat } from './useChat'
import * as api from '@/services/newsWorkflowApi'

vi.mock('@/services/newsWorkflowApi', () => ({
  fetchChatHistory: vi.fn(),
  clearChatHistory: vi.fn(),
  chatStream: vi.fn(),
  parseWebSources: vi.fn(),
}))

function makeWrapper(getUser = () => ({ id: 5, username: 'reader' })) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  return function Wrapper({ children }) {
    return createElement(QueryClientProvider, { client }, createElement(AuthContext.Provider, {
      value: { user: getUser(), loading: false, login: vi.fn(), register: vi.fn(), logout: vi.fn(), refresh: vi.fn() },
    }, children))
  }
}

describe('useChat', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.fetchChatHistory.mockResolvedValue({ messages: [] })
    api.clearChatHistory.mockResolvedValue(undefined)
  })
  afterEach(() => vi.restoreAllMocks())

  it('loads the saved history through a cancellable viewer-scoped query', async () => {
    api.fetchChatHistory.mockResolvedValueOnce({ messages: [{ role: 'user', content: 'hi' }, { role: 'assistant', content: 'hello' }] })
    const { result } = renderHook(() => useChat('42', true), { wrapper: makeWrapper() })
    await waitFor(() => expect(result.current.isLoading).toBe(false))
    expect(result.current.messages).toHaveLength(2)
    expect(api.fetchChatHistory).toHaveBeenCalledWith(42, expect.any(AbortSignal))
  })

  it('streams one user/assistant pair and clears the submitted draft only on success', async () => {
    async function* fakeStream() { yield 'Hel'; yield 'lo!' }
    api.chatStream.mockReturnValue(fakeStream())
    const { result } = renderHook(() => useChat('42', true), { wrapper: makeWrapper() })
    await waitFor(() => expect(result.current.isLoading).toBe(false))
    act(() => result.current.setInput('请问'))

    await act(async () => { await result.current.handleSend() })

    expect(result.current.messages).toHaveLength(2)
    expect(result.current.messages[0]).toMatchObject({ role: 'user', content: '请问' })
    expect(result.current.messages[1]).toMatchObject({ role: 'assistant', content: 'Hello!' })
    expect(result.current.input).toBe('')
    expect(result.current.isLoading).toBe(false)
  })

  it('reassembles split web-search metadata and preserves streamed Markdown exactly', async () => {
    const markdown = 'Summary\n\n```ts\nconst answer: string = "OK"\n```'
    const metaFrame = '\u200b__META__{"type":"web_search","sources":[{"title":"Example","url":"https://example.com"}]}__META__\n\n'
    api.parseWebSources.mockImplementation((sources) => sources)
    api.chatStream.mockReturnValue((async function* () {
      yield metaFrame.slice(0, 5)
      yield metaFrame.slice(5, 23)
      yield metaFrame.slice(23)
      yield markdown.slice(0, 16)
      yield markdown.slice(16)
    })())
    const { result } = renderHook(() => useChat('42', true), { wrapper: makeWrapper() })
    await waitFor(() => expect(result.current.isLoading).toBe(false))

    await act(async () => { await result.current.doSend('summarize') })

    expect(result.current.messages[1].content).toBe(markdown)
    expect(result.current.messages[1].content).not.toContain('__META__')
    expect(result.current.messages[1].web_sources).toEqual([{ title: 'Example', url: 'https://example.com' }])
  })

  it('keeps the question in the input after a stream error for explicit retry', async () => {
    // eslint-disable-next-line require-yield -- intentional: simulates a request that fails before its first token
    api.chatStream.mockImplementationOnce(async function* () { throw new Error('network down') })
    const { result } = renderHook(() => useChat('42', true), { wrapper: makeWrapper() })
    await waitFor(() => expect(result.current.isLoading).toBe(false))
    act(() => result.current.setInput('hi'))

    await act(async () => { await result.current.handleSend() })

    expect(result.current.input).toBe('hi')
    expect(result.current.messages).toHaveLength(2)
    expect(result.current.messages[1].content).toContain('遇到了一些问题')
    expect(result.current.phase).toBe('error')
  })

  it('reuses the failed local turn on explicit retry instead of appending duplicate UI messages', async () => {
    api.chatStream
      // eslint-disable-next-line require-yield -- intentional: simulates a request that fails before its first token
      .mockImplementationOnce(async function* () { throw new Error('network down') })
      .mockImplementationOnce(async function* () { yield 'recovered' })
    const { result } = renderHook(() => useChat('42', true), { wrapper: makeWrapper() })
    await waitFor(() => expect(result.current.isLoading).toBe(false))
    act(() => result.current.setInput('repeat once'))
    await act(async () => { await result.current.handleSend() })
    const failedUserId = result.current.messages[0].id

    await act(async () => { await result.current.handleSend() })

    expect(api.chatStream).toHaveBeenCalledTimes(2)
    expect(result.current.messages).toHaveLength(2)
    expect(result.current.messages[0].id).toBe(failedUserId)
    expect(result.current.messages[1].content).toBe('recovered')
  })

  it('ignores empty input and prevents concurrent duplicate submissions', async () => {
    let release
    api.chatStream.mockImplementation(async function* () {
      await new Promise((resolve) => { release = resolve })
      yield 'once'
    })
    const { result } = renderHook(() => useChat('42', true), { wrapper: makeWrapper() })
    await waitFor(() => expect(result.current.isLoading).toBe(false))
    await act(async () => { await result.current.doSend('   ') })
    expect(api.chatStream).not.toHaveBeenCalled()

    let send
    act(() => { send = result.current.doSend('one question') })
    await waitFor(() => expect(api.chatStream).toHaveBeenCalledOnce())
    await expect(result.current.doSend('one question')).resolves.toBe(false)
    await act(async () => { release(); await send })
    expect(result.current.messages).toHaveLength(2)
    expect(api.chatStream).toHaveBeenCalledOnce()
  })

  it('aborts the active stream on article switch and does not carry the prior turn into the new article', async () => {
    let signal
    api.chatStream.mockImplementation(async function* (_id, _question, options) {
      signal = options.signal
      await new Promise((resolve) => options.signal.addEventListener('abort', () => resolve('late token'), { once: true }))
      yield 'late token'
    })
    const wrapper = makeWrapper()
    const { result, rerender } = renderHook(({ id }) => useChat(id, true), { initialProps: { id: '42' }, wrapper })
    await waitFor(() => expect(result.current.isLoading).toBe(false))
    let send
    act(() => { send = result.current.doSend('old story') })
    await waitFor(() => expect(signal).toBeInstanceOf(AbortSignal))
    rerender({ id: '43' })
    await waitFor(() => expect(signal.aborted).toBe(true))
    await act(async () => { await send })
    expect(result.current.messages).toEqual([])
  })

  it('aborts the active stream and uses a fresh history query when the account changes', async () => {
    let currentUser = { id: 5, username: 'reader-a' }
    let signal
    api.chatStream.mockImplementation(async function* (_id, _question, options) {
      signal = options.signal
      await new Promise((resolve) => options.signal.addEventListener('abort', resolve, { once: true }))
      yield 'late answer'
    })
    const { result, rerender } = renderHook(() => useChat('42', true), { wrapper: makeWrapper(() => currentUser) })
    await waitFor(() => expect(result.current.isLoading).toBe(false))
    let send
    act(() => { send = result.current.doSend('private draft') })
    await waitFor(() => expect(signal).toBeInstanceOf(AbortSignal))

    currentUser = { id: 6, username: 'reader-b' }
    rerender()
    await waitFor(() => expect(signal.aborted).toBe(true))
    await act(async () => { await send })
    await waitFor(() => expect(api.fetchChatHistory).toHaveBeenCalledTimes(2))
    expect(result.current.messages).toEqual([])
  })

  it('clears the saved history only after the user confirms', async () => {
    api.fetchChatHistory.mockResolvedValueOnce({ messages: [{ role: 'user', content: 'x' }] })
    const { result } = renderHook(() => useChat('42', true), { wrapper: makeWrapper() })
    await waitFor(() => expect(result.current.messages).toHaveLength(1))
    act(() => result.current.requestClearChat())
    expect(result.current.confirmingClear).toBe(true)
    await act(async () => { await result.current.confirmClear() })
    expect(result.current.messages).toHaveLength(0)
    expect(result.current.confirmingClear).toBe(false)
    expect(api.clearChatHistory).toHaveBeenCalledWith(42, expect.any(AbortSignal))
  })

  it('cancelClear closes the dialog without calling the API', async () => {
    api.fetchChatHistory.mockResolvedValueOnce({ messages: [{ role: 'user', content: 'x' }] })
    const { result } = renderHook(() => useChat('42', true), { wrapper: makeWrapper() })
    await waitFor(() => expect(result.current.messages).toHaveLength(1))
    act(() => result.current.requestClearChat())
    act(() => result.current.cancelClear())
    expect(result.current.confirmingClear).toBe(false)
    expect(result.current.messages).toHaveLength(1)
    expect(api.clearChatHistory).not.toHaveBeenCalled()
  })
})
