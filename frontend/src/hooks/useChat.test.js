import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'
import { useChat } from './useChat'
import * as api from '../services/api'

describe('useChat', () => {
  beforeEach(() => {
    vi.spyOn(api, 'fetchChatHistory').mockResolvedValue({ messages: [] })
    vi.spyOn(api, 'clearChatHistory').mockResolvedValue({})
  })
  afterEach(() => { vi.restoreAllMocks() })

  it('loads chat history on mount', async () => {
    api.fetchChatHistory.mockResolvedValueOnce({
      messages: [{ role: 'user', content: 'hi' }, { role: 'assistant', content: 'hello' }],
    })

    const { result } = renderHook(() => useChat('42'))

    await waitFor(() => expect(result.current.isLoading).toBe(false))
    expect(result.current.messages).toHaveLength(2)
    expect(api.fetchChatHistory).toHaveBeenCalledWith('42')
  })

  it('handleSend appends user + assistant messages and streams content', async () => {
    async function* fakeStream() {
      yield 'Hel'
      yield 'lo!'
    }
    vi.spyOn(api, 'chatStream').mockReturnValue(fakeStream())

    const { result } = renderHook(() => useChat('42'))
    await waitFor(() => expect(result.current.isLoading).toBe(false))

    act(() => { result.current.setInput('请问') })
    await act(async () => { await result.current.handleSend() })

    expect(result.current.messages).toHaveLength(2)
    expect(result.current.messages[0]).toMatchObject({ role: 'user', content: '请问' })
    expect(result.current.messages[1]).toMatchObject({ role: 'assistant', content: 'Hello!' })
    expect(result.current.input).toBe('')
    expect(result.current.isLoading).toBe(false)
  })

  it('handleSend writes error message on stream failure', async () => {
    async function* failing() { throw new Error('network down') }
    vi.spyOn(api, 'chatStream').mockReturnValue(failing())

    const { result } = renderHook(() => useChat('42'))
    await waitFor(() => expect(result.current.isLoading).toBe(false))

    act(() => { result.current.setInput('hi') })
    await act(async () => { await result.current.handleSend() })

    expect(result.current.messages[1].content).toContain('遇到了一些问题')
  })

  it('ignores empty input', async () => {
    vi.spyOn(api, 'chatStream')
    const { result } = renderHook(() => useChat('42'))
    await waitFor(() => expect(result.current.isLoading).toBe(false))

    act(() => { result.current.setInput('   ') })
    await act(async () => { await result.current.handleSend() })

    expect(result.current.messages).toHaveLength(0)
    expect(api.chatStream).not.toHaveBeenCalled()
  })

  it('handleClearChat removes messages when confirmed', async () => {
    api.fetchChatHistory.mockResolvedValueOnce({ messages: [{ role: 'user', content: 'x' }] })
    vi.spyOn(window, 'confirm').mockReturnValue(true)

    const { result } = renderHook(() => useChat('42'))
    await waitFor(() => expect(result.current.messages).toHaveLength(1))

    await act(async () => { await result.current.handleClearChat() })
    expect(result.current.messages).toHaveLength(0)
    expect(api.clearChatHistory).toHaveBeenCalledWith('42')
  })
})
