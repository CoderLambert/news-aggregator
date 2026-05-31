import { describe, it, expect, vi } from 'vitest'
import { renderHook } from '@testing-library/react'
import { useScrollPast } from './useScrollPast'

describe('useScrollPast', () => {
  it('returns false when scroll position is below threshold', () => {
    window.scrollY = 100
    const { result } = renderHook(() => useScrollPast(400))
    expect(result.current).toBe(false)
  })

  it('returns true when scroll position is above threshold', () => {
    window.scrollY = 500
    const { result } = renderHook(() => useScrollPast(400))
    expect(result.current).toBe(true)
  })

  it('listens to scroll events with passive flag', () => {
    const addSpy = vi.spyOn(window, 'addEventListener')
    renderHook(() => useScrollPast(400))
    expect(addSpy).toHaveBeenCalledWith('scroll', expect.any(Function), { passive: true })
    addSpy.mockRestore()
  })
})
