import { describe, expect, it, vi } from 'vitest'
import { useState } from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import AuthModal from '@/components/AuthModal'

const auth = vi.hoisted(() => ({ login: vi.fn(), register: vi.fn() }))
vi.mock('@/context/AuthContext', () => ({ useAuth: () => auth }))
vi.mock('@gsap/react', () => ({ useGSAP: () => {} }))

function Harness() {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>打开登录</button>
      {open && <AuthModal onClose={() => setOpen(false)} />}
    </>
  )
}

describe('AuthModal keyboard behavior', () => {
  it('focuses the form, traps Tab, and closes on Escape with focus restored', async () => {
    const user = userEvent.setup()
    render(<Harness />)

    const opener = screen.getByRole('button', { name: '打开登录' })
    await user.click(opener)
    expect(screen.getByRole('dialog', { name: '登录小闻' })).toBeInTheDocument()
    await waitFor(() => expect(screen.getByLabelText('用户名')).toHaveFocus())

    await user.keyboard('{Shift>}{Tab}{/Shift}')
    expect(screen.getByRole('button', { name: '关闭登录窗口' })).toHaveFocus()
    await user.keyboard('{Shift>}{Tab}{/Shift}')
    expect(screen.getByRole('button', { name: '立即注册' })).toHaveFocus()
    await user.keyboard('{Tab}')
    expect(screen.getByRole('button', { name: '关闭登录窗口' })).toHaveFocus()

    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(opener).toHaveFocus()
  })
})
