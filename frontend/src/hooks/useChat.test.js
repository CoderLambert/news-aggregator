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

function waitForAbort(signal) {
  return new Promise((resolve) => {
    if (signal.aborted) resolve()
    else signal.addEventListener('abort', resolve, { once: true })
  })
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
    api.chatStream.mockReturnValue((async function* () { yield 'Hel'; yield 'lo!' })())
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

  it('reconciles a stopped request by exact history boundary and avoids a duplicate saved pair', async () => {
    const base = [{ role: 'user', content: 'earlier' }, { role: 'assistant', content: 'answer' }]
    api.fetchChatHistory
      .mockResolvedValueOnce({ messages: base })
      .mockResolvedValueOnce({ messages: [...base, { role: 'user', content: 'current' }, { role: 'assistant', content: 'saved reply' }] })
    let signal
    api.chatStream.mockImplementation(async function* (_id, _question, options) {
      signal = options.signal
      yield 'partial'
      await waitForAbort(signal)
    })
    const { result } = renderHook(() => useChat('42', true), { wrapper: makeWrapper() })
    await waitFor(() => expect(result.current.isLoading).toBe(false))
    act(() => result.current.setInput('current'))
    let sendPromise
    act(() => { sendPromise = result.current.handleSend() })
    await waitFor(() => expect(result.current.phase).toBe('streaming'))

    act(() => result.current.stopWaiting())
    await act(async () => { await sendPromise })
    await waitFor(() => expect(result.current.uncertainTurn).toBeNull())

    expect(result.current.messages).toEqual([...base, { role: 'user', content: 'current' }, { role: 'assistant', content: 'saved reply' }])
    expect(result.current.input).toBe('')
    expect(api.chatStream).toHaveBeenCalledOnce()
    expect(api.fetchChatHistory).toHaveBeenCalledTimes(2)
  })

  it('keeps an uncertain draft when the server history is unchanged and never resends automatically', async () => {
    api.chatStream.mockImplementation(async function* (_id, _question, { signal }) {
      yield 'partial'
      await waitForAbort(signal)
    })
    const { result } = renderHook(() => useChat('42', true), { wrapper: makeWrapper() })
    await waitFor(() => expect(result.current.isLoading).toBe(false))
    act(() => result.current.setInput('maybe saved'))
    let sendPromise
    act(() => { sendPromise = result.current.handleSend() })
    await waitFor(() => expect(result.current.phase).toBe('streaming'))
    act(() => result.current.stopWaiting())
    await act(async () => { await sendPromise })
    await waitFor(() => expect(result.current.uncertainTurn?.reconciliation).toBe('unconfirmed'))

    expect(result.current.input).toBe('maybe saved')
    expect(result.current.messages).toHaveLength(2)
    await expect(result.current.doSend('different question')).resolves.toBe(false)
    expect(api.chatStream).toHaveBeenCalledOnce()
  })

  it('does not mistake an identical question in the existing history for the interrupted turn', async () => {
    const previous = [{ role: 'user', content: 'repeat' }, { role: 'assistant', content: 'old reply' }]
    api.fetchChatHistory.mockResolvedValueOnce({ messages: previous }).mockResolvedValueOnce({ messages: previous })
    api.chatStream.mockImplementation(async function* (_id, _question, { signal }) {
      yield 'partial'
      await waitForAbort(signal)
    })
    const { result } = renderHook(() => useChat('42', true), { wrapper: makeWrapper() })
    await waitFor(() => expect(result.current.isLoading).toBe(false))
    act(() => result.current.setInput('repeat'))
    let sendPromise
    act(() => { sendPromise = result.current.handleSend() })
    await waitFor(() => expect(result.current.phase).toBe('streaming'))
    act(() => result.current.stopWaiting())
    await act(async () => { await sendPromise })
    await waitFor(() => expect(result.current.uncertainTurn?.reconciliation).toBe('unconfirmed'))

    expect(result.current.messages.filter((message) => message.role === 'user' && message.content === 'repeat')).toHaveLength(2)
    expect(result.current.input).toBe('repeat')
  })

  it('keeps a draft and exposes read-only recheck after a network error and history GET failure', async () => {
    // eslint-disable-next-line require-yield -- simulates failure before the first token
    api.chatStream.mockImplementationOnce(async function* () { throw new Error('network down') })
    api.fetchChatHistory.mockResolvedValueOnce({ messages: [] }).mockRejectedValueOnce(new Error('history unavailable'))
    const { result } = renderHook(() => useChat('42', true), { wrapper: makeWrapper() })
    await waitFor(() => expect(result.current.isLoading).toBe(false))
    act(() => result.current.setInput('recover me'))

    await act(async () => { await result.current.handleSend() })

    expect(result.current.input).toBe('recover me')
    expect(result.current.uncertainTurn?.reconciliation).toBe('failed')
    expect(api.chatStream).toHaveBeenCalledOnce()
    expect(api.fetchChatHistory).toHaveBeenCalledTimes(2)
    await act(async () => { await result.current.checkPendingTurn() })
    expect(result.current.uncertainTurn?.reconciliation).toBe('unconfirmed')
    expect(api.chatStream).toHaveBeenCalledOnce()
  })

  it('reconciles a later normal history refetch after the first interrupted check found no records', async () => {
    const saved = [{ role: 'user', content: 'recover after check' }, { role: 'assistant', content: 'saved answer' }]
    api.fetchChatHistory
      .mockResolvedValueOnce({ messages: [] })
      .mockResolvedValueOnce({ messages: [] })
      .mockResolvedValueOnce({ messages: saved })
    api.chatStream.mockImplementation(async function* (_id, _question, { signal }) {
      yield 'partial'
      await waitForAbort(signal)
    })
    const { result } = renderHook(() => useChat('42', true), { wrapper: makeWrapper() })
    await waitFor(() => expect(result.current.isLoading).toBe(false))
    act(() => result.current.setInput('recover after check'))
    let sendPromise
    act(() => { sendPromise = result.current.handleSend() })
    await waitFor(() => expect(result.current.phase).toBe('streaming'))
    act(() => result.current.stopWaiting())
    await act(async () => { await sendPromise })
    await waitFor(() => expect(result.current.uncertainTurn?.reconciliation).toBe('unconfirmed'))
    act(() => result.current.setInput('keep this new draft'))

    await act(async () => { await result.current.retryHistory() })
    await waitFor(() => expect(result.current.uncertainTurn).toBeNull())

    expect(result.current.messages).toEqual(saved)
    expect(result.current.input).toBe('keep this new draft')
    expect(api.chatStream).toHaveBeenCalledOnce()
    expect(api.fetchChatHistory).toHaveBeenCalledTimes(3)
  })

  it('reconciles a later normal history refetch after the first check found only the question', async () => {
    const question = { role: 'user', content: 'answer arrives later' }
    const saved = [question, { role: 'assistant', content: 'late saved answer' }]
    api.fetchChatHistory
      .mockResolvedValueOnce({ messages: [] })
      .mockResolvedValueOnce({ messages: [question] })
      .mockResolvedValueOnce({ messages: saved })
    api.chatStream.mockImplementation(async function* (_id, _question, { signal }) {
      yield 'partial'
      await waitForAbort(signal)
    })
    const { result } = renderHook(() => useChat('42', true), { wrapper: makeWrapper() })
    await waitFor(() => expect(result.current.isLoading).toBe(false))
    act(() => result.current.setInput('answer arrives later'))
    let sendPromise
    act(() => { sendPromise = result.current.handleSend() })
    await waitFor(() => expect(result.current.phase).toBe('streaming'))
    act(() => result.current.stopWaiting())
    await act(async () => { await sendPromise })
    await waitFor(() => expect(result.current.uncertainTurn?.reconciliation).toBe('partial'))
    act(() => result.current.setInput('keep this different draft'))

    await act(async () => { await result.current.retryHistory() })
    await waitFor(() => expect(result.current.uncertainTurn).toBeNull())

    expect(result.current.messages).toEqual(saved)
    expect(result.current.input).toBe('keep this different draft')
    expect(api.chatStream).toHaveBeenCalledOnce()
    expect(api.fetchChatHistory).toHaveBeenCalledTimes(3)
  })

  it('hides a confirmed saved question and prevents resending while its answer is missing', async () => {
    api.fetchChatHistory.mockResolvedValueOnce({ messages: [] }).mockResolvedValueOnce({ messages: [{ role: 'user', content: 'question only' }] })
    api.chatStream.mockImplementation(async function* (_id, _question, { signal }) {
      yield 'partial'
      await waitForAbort(signal)
    })
    const { result } = renderHook(() => useChat('42', true), { wrapper: makeWrapper() })
    await waitFor(() => expect(result.current.isLoading).toBe(false))
    act(() => result.current.setInput('question only'))
    let sendPromise
    act(() => { sendPromise = result.current.handleSend() })
    await waitFor(() => expect(result.current.phase).toBe('streaming'))
    act(() => result.current.stopWaiting())
    await act(async () => { await sendPromise })
    await waitFor(() => expect(result.current.uncertainTurn?.reconciliation).toBe('partial'))

    expect(result.current.messages.filter((message) => message.role === 'user' && message.content === 'question only')).toHaveLength(1)
    expect(result.current.input).toBe('')
    await expect(result.current.resendUncertainTurn()).resolves.toBe(false)
    expect(api.chatStream).toHaveBeenCalledOnce()
  })

  it('allows only an explicit risk-acknowledging resend after an unconfirmed result', async () => {
    api.chatStream
      // eslint-disable-next-line require-yield -- simulates failure before the first token
      .mockImplementationOnce(async function* () { throw new Error('network down') })
      .mockImplementationOnce(async function* () { yield 'recovered' })
    const { result } = renderHook(() => useChat('42', true), { wrapper: makeWrapper() })
    await waitFor(() => expect(result.current.isLoading).toBe(false))
    act(() => result.current.setInput('repeat once'))
    await act(async () => { await result.current.handleSend() })
    expect(result.current.uncertainTurn?.reconciliation).toBe('unconfirmed')
    expect(api.chatStream).toHaveBeenCalledOnce()

    await act(async () => { await result.current.resendUncertainTurn() })

    expect(api.chatStream).toHaveBeenCalledTimes(2)
    expect(result.current.messages).toHaveLength(2)
    expect(result.current.messages[0]).toMatchObject({ role: 'user', content: 'repeat once' })
    expect(result.current.messages[1].content).toBe('recovered')
    expect(result.current.input).toBe('')
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
      await waitForAbort(signal)
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
      await waitForAbort(signal)
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

  it('retains messages and exposes a recoverable error when an idle clear fails', async () => {
    api.fetchChatHistory.mockResolvedValueOnce({ messages: [{ role: 'user', content: 'existing' }] })
    api.clearChatHistory.mockRejectedValueOnce(new Error('delete failed'))
    api.chatStream.mockReturnValue((async function* () { yield 'recovered' })())
    const { result } = renderHook(() => useChat('42', true), { wrapper: makeWrapper() })
    await waitFor(() => expect(result.current.messages).toHaveLength(1))
    act(() => result.current.requestClearChat())

    await act(async () => { await expect(result.current.confirmClear()).resolves.toBe(false) })

    expect(result.current.messages).toEqual([{ role: 'user', content: 'existing' }])
    expect(result.current.clearError).toContain('清空失败')
    expect(result.current.confirmingClear).toBe(true)
    expect(result.current.isClearing).toBe(false)
    act(() => result.current.cancelClear())
    await act(async () => { await result.current.doSend('new question') })
    expect(api.chatStream).toHaveBeenCalledOnce()
  })

  it('reconciles the aborted stream after clear failure without dropping prior history', async () => {
    const saved = [{ role: 'user', content: 'before clear' }]
    api.fetchChatHistory.mockResolvedValueOnce({ messages: saved }).mockResolvedValueOnce({ messages: saved })
    api.clearChatHistory.mockRejectedValueOnce(new Error('delete failed'))
    api.chatStream.mockImplementation(async function* (_id, _question, { signal }) {
      yield 'partial answer'
      await waitForAbort(signal)
    })
    const { result } = renderHook(() => useChat('42', true), { wrapper: makeWrapper() })
    await waitFor(() => expect(result.current.isLoading).toBe(false))
    let sendPromise
    act(() => { sendPromise = result.current.doSend('pending question') })
    await waitFor(() => expect(result.current.phase).toBe('streaming'))
    act(() => result.current.requestClearChat())
    await act(async () => { await result.current.confirmClear() })
    await waitFor(() => expect(result.current.uncertainTurn?.reconciliation).toBe('unconfirmed'))
    await act(async () => { await sendPromise })

    expect(result.current.messages[0]).toEqual(saved[0])
    expect(result.current.messages).toHaveLength(3)
    expect(result.current.clearError).toContain('清空失败')
    expect(api.fetchChatHistory).toHaveBeenCalledTimes(2)
    expect(api.chatStream).toHaveBeenCalledOnce()
  })

  it('blocks sends and duplicate clears while a confirmed clear is pending', async () => {
    let resolveDelete
    api.clearChatHistory.mockImplementation(() => new Promise((resolve) => { resolveDelete = resolve }))
    const { result } = renderHook(() => useChat('42', true), { wrapper: makeWrapper() })
    await waitFor(() => expect(result.current.isLoading).toBe(false))
    act(() => result.current.requestClearChat())
    await expect(result.current.doSend('before confirmation')).resolves.toBe(false)
    let clearing
    act(() => { clearing = result.current.confirmClear() })
    await waitFor(() => expect(result.current.isClearing).toBe(true))

    await expect(result.current.doSend('too soon')).resolves.toBe(false)
    await expect(result.current.confirmClear()).resolves.toBe(false)
    expect(api.clearChatHistory).toHaveBeenCalledOnce()
    expect(api.chatStream).not.toHaveBeenCalled()

    await act(async () => { resolveDelete(); await clearing })
    expect(result.current.messages).toEqual([])
    expect(result.current.isClearing).toBe(false)
  })

  it('aborts a pending clear on identity switch and ignores its late success', async () => {
    let currentUser = { id: 5, username: 'reader-a' }
    api.fetchChatHistory.mockResolvedValueOnce({ messages: [{ role: 'user', content: 'account a' }] })
    api.fetchChatHistory.mockResolvedValue({ messages: [{ role: 'user', content: 'account b' }] })
    let resolveDelete
    let deleteSignal
    api.clearChatHistory.mockImplementation((_id, signal) => {
      deleteSignal = signal
      return new Promise((resolve) => { resolveDelete = resolve })
    })
    const { result, rerender } = renderHook(() => useChat('42', true), { wrapper: makeWrapper(() => currentUser) })
    await waitFor(() => expect(result.current.messages[0]?.content).toBe('account a'))
    act(() => result.current.requestClearChat())
    let clearing
    act(() => { clearing = result.current.confirmClear() })
    await waitFor(() => expect(deleteSignal).toBeInstanceOf(AbortSignal))

    currentUser = { id: 6, username: 'reader-b' }
    rerender()
    await waitFor(() => expect(deleteSignal.aborted).toBe(true))
    await waitFor(() => expect(result.current.messages[0]?.content).toBe('account b'))
    await act(async () => { resolveDelete(); await clearing })

    expect(result.current.messages).toEqual([{ role: 'user', content: 'account b' }])
    expect(api.clearChatHistory).toHaveBeenCalledOnce()
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
