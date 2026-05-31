import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { useSuggestedQuestions } from './useSuggestedQuestions'
import * as api from '../services/api'

vi.mock('../services/api', () => ({
  fetchSuggestedQuestions: vi.fn(),
}))

describe('useSuggestedQuestions', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('does NOT fetch when enabled=false (panel closed)', async () => {
    renderHook(() => useSuggestedQuestions('42', false))
    // Wait a tick to be sure no async call slipped through
    await new Promise(r => setTimeout(r, 10))
    expect(api.fetchSuggestedQuestions).not.toHaveBeenCalled()
  })

  it('fetches once when enabled flips to true', async () => {
    api.fetchSuggestedQuestions.mockResolvedValueOnce({ questions: ['a', 'b', 'c'] })
    const { result, rerender } = renderHook(
      ({ enabled }) => useSuggestedQuestions('42', enabled),
      { initialProps: { enabled: false } }
    )
    expect(result.current.questions).toEqual([])

    rerender({ enabled: true })
    await waitFor(() => expect(result.current.questions).toEqual(['a', 'b', 'c']))
    expect(api.fetchSuggestedQuestions).toHaveBeenCalledOnce()
    expect(api.fetchSuggestedQuestions).toHaveBeenCalledWith('42')

    // Toggling enabled false → true again must NOT re-fetch (already cached for this newsId)
    rerender({ enabled: false })
    rerender({ enabled: true })
    await new Promise(r => setTimeout(r, 10))
    expect(api.fetchSuggestedQuestions).toHaveBeenCalledOnce()
  })

  it('re-fetches when newsId changes', async () => {
    api.fetchSuggestedQuestions
      .mockResolvedValueOnce({ questions: ['a'] })
      .mockResolvedValueOnce({ questions: ['b'] })
    const { result, rerender } = renderHook(
      ({ id }) => useSuggestedQuestions(id, true),
      { initialProps: { id: '1' } }
    )
    await waitFor(() => expect(result.current.questions).toEqual(['a']))

    rerender({ id: '2' })
    await waitFor(() => expect(result.current.questions).toEqual(['b']))
    expect(api.fetchSuggestedQuestions).toHaveBeenCalledTimes(2)
  })

  it('on API failure stays at empty (caller will fall back to defaults)', async () => {
    api.fetchSuggestedQuestions.mockRejectedValueOnce(new Error('boom'))
    const { result } = renderHook(() => useSuggestedQuestions('42', true))
    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.questions).toEqual([])
    expect(result.current.error).toBeTruthy()
  })

  it('refresh() re-invokes the API with force=true and updates questions', async () => {
    api.fetchSuggestedQuestions
      .mockResolvedValueOnce({ questions: ['old1', 'old2', 'old3'] })
      .mockResolvedValueOnce({ questions: ['new1', 'new2', 'new3'] })

    const { result } = renderHook(() => useSuggestedQuestions('42', true))
    await waitFor(() => expect(result.current.questions).toEqual(['old1', 'old2', 'old3']))
    expect(api.fetchSuggestedQuestions).toHaveBeenLastCalledWith('42')

    // User clicks "换一批"
    await result.current.refresh()
    await waitFor(() => expect(result.current.questions).toEqual(['new1', 'new2', 'new3']))
    // Second call must pass the force flag
    expect(api.fetchSuggestedQuestions).toHaveBeenLastCalledWith('42', { force: true })
    expect(api.fetchSuggestedQuestions).toHaveBeenCalledTimes(2)
  })

  it('refresh() keeps old questions on failure (UX never goes blank)', async () => {
    api.fetchSuggestedQuestions
      .mockResolvedValueOnce({ questions: ['kept1', 'kept2', 'kept3'] })
      .mockRejectedValueOnce(new Error('llm down'))

    const { result } = renderHook(() => useSuggestedQuestions('42', true))
    await waitFor(() => expect(result.current.questions).toEqual(['kept1', 'kept2', 'kept3']))

    await result.current.refresh()
    await waitFor(() => expect(result.current.loading).toBe(false))
    // Old questions preserved
    expect(result.current.questions).toEqual(['kept1', 'kept2', 'kept3'])
  })

  it('refresh() is a no-op when newsId is missing', async () => {
    const { result } = renderHook(() => useSuggestedQuestions(null, true))
    await result.current.refresh()
    expect(api.fetchSuggestedQuestions).not.toHaveBeenCalled()
  })
})
