import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, act } from '@testing-library/react'
import Confetti from './Confetti'

describe('Confetti', () => {
  beforeEach(() => { vi.useFakeTimers() })
  afterEach(() => { vi.useRealTimers() })

  // Flush both microtasks (Promise.resolve().then in the effect) and timers
  async function flush() {
    await act(async () => {
      await Promise.resolve()
      await Promise.resolve()
    })
  }

  it('does not render when fire=false', async () => {
    render(<Confetti fire={false} />)
    await flush()
    expect(screen.queryByTestId('confetti-root')).toBeNull()
  })

  it('renders pieces when fire=true', async () => {
    render(<Confetti fire pieceCount={20} />)
    await flush()
    const root = screen.getByTestId('confetti-root')
    expect(root).toBeInTheDocument()
    expect(root.querySelectorAll('span').length).toBe(20)
  })

  it('cleans up itself after durationMs', async () => {
    render(<Confetti fire pieceCount={10} durationMs={1000} />)
    await flush()
    expect(screen.getByTestId('confetti-root')).toBeInTheDocument()
    await act(async () => { vi.advanceTimersByTime(1100) })
    expect(screen.queryByTestId('confetti-root')).toBeNull()
  })
})
