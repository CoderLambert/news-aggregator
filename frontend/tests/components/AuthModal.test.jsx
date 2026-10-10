import { afterEach, describe, expect, it, vi } from 'vitest'
import { useState } from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import AuthModal from '@/components/AuthModal'
import { CapabilitiesTestProvider } from '../helpers/capabilities'

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
    render(<CapabilitiesTestProvider><Harness /></CapabilitiesTestProvider>)

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

  it('submits the invite token only with registration and requires a valid email field', async () => {
    const user = userEvent.setup()
    auth.register.mockResolvedValue({ id: 9, username: 'invited-reader' })
    render(<CapabilitiesTestProvider><Harness /></CapabilitiesTestProvider>)

    await user.click(screen.getByRole('button', { name: '打开登录' }))
    await user.click(screen.getByRole('button', { name: '立即注册' }))
    expect(screen.getByLabelText('邮箱')).toHaveAttribute('type', 'email')
    expect(screen.getByLabelText('邮箱')).toBeRequired()
    expect(screen.getByText('公网注册需要有效邀请；密码需符合安全要求。')).toBeInTheDocument()

    await user.type(screen.getByLabelText('用户名'), 'invited-reader')
    await user.type(screen.getByLabelText('邮箱'), 'invitee@example.test')
    await user.type(screen.getByLabelText('邀请码'), 'one-time-token')
    await user.type(screen.getByLabelText('密码'), 'Sufficiently-Strong-Password-93!')
    await user.click(screen.getByRole('button', { name: '注册' }))

    await waitFor(() => expect(auth.register).toHaveBeenCalledWith(
      'invited-reader', 'Sufficiently-Strong-Password-93!', 'invitee@example.test', 'one-time-token',
    ))
    const persistedValues = [localStorage, sessionStorage].flatMap((storage) =>
      Array.from({ length: storage.length }, (_, index) => storage.getItem(storage.key(index) ?? '') ?? ''),
    )
    expect(persistedValues.some((value) => value.includes('one-time-token'))).toBe(false)
  })
})

afterEach(() => {
  auth.login.mockReset()
  auth.register.mockReset()
})
