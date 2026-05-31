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
})
