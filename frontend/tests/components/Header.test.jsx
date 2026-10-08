import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import Header from '@/components/Header'

vi.mock('@/context/AuthContext', () => ({
  useAuth: () => ({ user: null, logout: vi.fn() }),
}))

vi.mock('@/context/useLanguage', () => ({
  useLanguage: () => ({
    lang: 'zh',
    setLang: vi.fn(),
    displayMode: 'zh',
    setDisplayMode: vi.fn(),
    t: { admin: '管理后台' },
  }),
}))

describe('Header navigation menu', () => {
  it('keeps the menu button inside while handling its real pointer toggle sequence', () => {
    render(<MemoryRouter><Header /></MemoryRouter>)

    const toggle = screen.getByRole('button', { name: '打开菜单' })
    fireEvent.click(toggle)
    expect(toggle).toHaveAttribute('aria-expanded', 'true')

    fireEvent.pointerDown(toggle, { pointerId: 1, pointerType: 'mouse', button: 0 })
    fireEvent.pointerUp(toggle, { pointerId: 1, pointerType: 'mouse', button: 0 })
    fireEvent.click(toggle)

    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByRole('navigation', { name: '站点导航' })).not.toBeInTheDocument()
  })
})
