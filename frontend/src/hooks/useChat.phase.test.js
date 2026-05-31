import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'
import { useChat } from './useChat'

/**
 * useChat phase machine — mascot relies on this to pick its mood.
 *
 * Phases:
 *   - 'loading-history' : initial fetch of past messages
 *   - 'idle'            : ready, no active request
 *   - 'thinking'        : user sent, waiting for first token
 *   - 'streaming'       : tokens arriving
 *   - 'success'         : stream finished (transient, then back to idle after 1.5s)
 *   - 'error'           : stream failed (sticky until next send)
 */

vi.mock('../services/api', () => ({
  fetchChatHistory: vi.fn(),
  clearChatHistory: vi.fn(),
  chatStream: vi.fn(),
}))

import { fetchChatHistory, chatStream } from '../services/api'

describe('useChat phase machine', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    fetchChatHistory.mockResolvedValue({ messages: [] })
  })

  it('starts in loading-history then becomes idle', async () => {
    const { result } = renderHook(() => useChat(1))
    expect(result.current.phase).toBe('loading-history')
    await waitFor(() => expect(result.current.phase).toBe('idle'))
  })

  it('transitions idle → thinking → streaming → success → idle on successful send', async () => {
    fetchChatHistory.mockResolvedValue({ messages: [] })
    let resolveFirstChunk, resolveSecondChunk
    chatStream.mockImplementation(async function* () {
      // Wait until test signals us — lets us assert "thinking" before first token
      await new Promise(r => { resolveFirstChunk = r })
      yield 'Hello '
      // Pause between chunks so the test can observe "streaming"
      await new Promise(r => { resolveSecondChunk = r })
      yield 'world'
    })

    const { result } = renderHook(() => useChat(1))
    await waitFor(() => expect(result.current.phase).toBe('idle'))

    act(() => { result.current.setInput('hi') })

    let sendPromise
    act(() => { sendPromise = result.current.handleSend() })

    // Before any token: thinking
    await waitFor(() => expect(result.current.phase).toBe('thinking'))

    // Release first chunk → phase becomes 'streaming'
    act(() => { resolveFirstChunk() })
    await waitFor(() => expect(result.current.phase).toBe('streaming'))

    // Release final chunk + finish
    act(() => { resolveSecondChunk() })
    await act(async () => { await sendPromise })

    // success is transient — should auto-revert to idle
    await waitFor(() => expect(result.current.phase).toBe('idle'), { timeout: 3000 })
  })

  it('transitions to error phase on stream failure', async () => {
    fetchChatHistory.mockResolvedValue({ messages: [] })
    chatStream.mockImplementation(async function* () {
      throw new Error('Network down')
      // eslint-disable-next-line no-unreachable
      yield ''
    })

    const { result } = renderHook(() => useChat(1))
    await waitFor(() => expect(result.current.phase).toBe('idle'))

    act(() => { result.current.setInput('hi') })
    await act(async () => { await result.current.handleSend() })

    expect(result.current.phase).toBe('error')
  })

  it('error phase clears when user sends a new message', async () => {
    fetchChatHistory.mockResolvedValue({ messages: [] })
    chatStream
      .mockImplementationOnce(async function* () {
        throw new Error('boom')
        // eslint-disable-next-line no-unreachable
        yield ''
      })
      .mockImplementationOnce(async function* () {
        yield 'ok'
      })

    const { result } = renderHook(() => useChat(1))
    await waitFor(() => expect(result.current.phase).toBe('idle'))

    act(() => { result.current.setInput('first') })
    await act(async () => { await result.current.handleSend() })
    expect(result.current.phase).toBe('error')

    act(() => { result.current.setInput('second') })
    let sendPromise
    act(() => { sendPromise = result.current.handleSend() })
    // Once second send starts, error should clear
    await waitFor(() => expect(result.current.phase).not.toBe('error'))
    await act(async () => { await sendPromise })
  })
})
