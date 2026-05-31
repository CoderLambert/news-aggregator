import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import ScrollToTop from './ScrollToTop'

// Mock the scroll position hook
vi.mock('@/hooks/useScrollPast', () => ({
  useScrollPast: vi.fn(),
}))

import { useScrollPast } from '@/hooks/useScrollPast'

describe('ScrollToTop', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // Mock window.scrollTo
    window.scrollTo = vi.fn()
  })

  it('does not render when not scrolled past threshold', () => {
    useScrollPast.mockReturnValue(false)
    render(<ScrollToTop />)
    expect(screen.queryByLabelText('返回顶部')).not.toBeInTheDocument()
  })

  it('renders when scrolled past threshold', () => {
    useScrollPast.mockReturnValue(true)
    render(<ScrollToTop />)
    expect(screen.getByLabelText('返回顶部')).toBeInTheDocument()
  })

  it('calls window.scrollTo with smooth behavior on click', async () => {
    const user = userEvent.setup()
    useScrollPast.mockReturnValue(true)
    render(<ScrollToTop />)

    await user.click(screen.getByLabelText('返回顶部'))
    expect(window.scrollTo).toHaveBeenCalledWith({ top: 0, behavior: 'smooth' })
  })
})
