import { act, render, renderHook, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useNearViewport } from '@/hooks/useNearViewport'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('useNearViewport', () => {
  it('falls back to immediate work when IntersectionObserver is unavailable', () => {
    vi.stubGlobal('IntersectionObserver', undefined)
    const { result } = renderHook(() => useNearViewport())
    expect(result.current.isNearViewport).toBe(true)
  })

  it('waits until the target enters the preload margin', () => {
    let notify: IntersectionObserverCallback | undefined
    const observe = vi.fn()
    const disconnect = vi.fn()
    class MockObserver {
      constructor(callback: IntersectionObserverCallback) { notify = callback }
      observe = observe
      disconnect = disconnect
    }
    vi.stubGlobal('IntersectionObserver', MockObserver)
    function Target() {
      const { targetRef, isNearViewport } = useNearViewport<HTMLDivElement>()
      return <div ref={targetRef} data-testid="target" data-near={String(isNearViewport)} />
    }
    render(<Target />)
    expect(screen.getByTestId('target').getAttribute('data-near')).toBe('false')
    expect(observe).toHaveBeenCalledOnce()

    act(() => {
      notify?.([{ isIntersecting: true } as IntersectionObserverEntry], {} as IntersectionObserver)
    })
    expect(screen.getByTestId('target').getAttribute('data-near')).toBe('true')
    expect(disconnect).toHaveBeenCalled()
  })
})
