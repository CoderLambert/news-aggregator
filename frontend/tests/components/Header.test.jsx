import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import Header from '@/components/Header'
import { CapabilitiesTestProvider } from '../helpers/capabilities'

const authState = vi.hoisted(() => ({ user: null, logout: vi.fn() }))

function renderHeader(initialEntries = ['/']) {
  return render(
    <MemoryRouter initialEntries={initialEntries}>
      <CapabilitiesTestProvider><Header /></CapabilitiesTestProvider>
    </MemoryRouter>,
  )
}

vi.mock('@/context/AuthContext', () => ({
  useAuth: () => authState,
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

beforeEach(() => {
  authState.user = null
  authState.logout.mockReset()
})

describe('Header navigation menu', () => {
  it('shows the current workspace context in the desktop header', () => {
    const subscribed = renderHeader(['/?scope=subscribed'])
    expect(screen.getByLabelText('资讯流：我的订阅')).toBeInTheDocument()
    subscribed.unmount()

    renderHeader(['/admin/crawlers'])
    expect(screen.getByLabelText('系统管理：RSS 与搜索管理')).toBeInTheDocument()
  })

  it('keeps the menu button inside while handling its real pointer toggle sequence', () => {
    renderHeader()

    const toggle = screen.getByRole('button', { name: '打开菜单' })
    fireEvent.click(toggle)
    expect(toggle).toHaveAttribute('aria-expanded', 'true')

    fireEvent.pointerDown(toggle, { pointerId: 1, pointerType: 'mouse', button: 0 })
    fireEvent.pointerUp(toggle, { pointerId: 1, pointerType: 'mouse', button: 0 })
    fireEvent.click(toggle)

    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByRole('navigation', { name: '站点导航' })).not.toBeInTheDocument()
  })

  it('exposes the four primary destinations and marks the current section', () => {
    renderHeader(['/settings'])
    fireEvent.click(screen.getByRole('button', { name: '打开菜单' }))
    const navigation = screen.getByRole('navigation', { name: '站点导航' })
    expect(navigation).toHaveTextContent('首页')
    expect(navigation).toHaveTextContent('搜索')
    expect(navigation).toHaveTextContent('内容偏好')
    expect(navigation).toHaveTextContent('设置')
    expect(screen.getByRole('link', { name: '设置' })).toHaveAttribute('aria-current', 'page')
  })

  it('marks settings as current on the nested ChatGPT connection route', () => {
    renderHeader(['/settings/chatgpt'])
    fireEvent.click(screen.getByRole('button', { name: '打开菜单' }))
    expect(screen.getByRole('link', { name: '设置' })).toHaveAttribute('aria-current', 'page')
  })

  it('offers RSS management only to a superuser and removes retired comparisons', () => {
    authState.user = { id: 4, username: 'reader', isSuperuser: false }
    const reader = renderHeader()
    fireEvent.click(screen.getByRole('button', { name: '打开菜单' }))
    expect(screen.queryByRole('link', { name: 'Provider 对比' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: '管理控制台' })).not.toBeInTheDocument()
    reader.unmount()

    authState.user = { id: 5, username: 'admin', isSuperuser: true }
    renderHeader()
    fireEvent.click(screen.getByRole('button', { name: '打开菜单' }))
    expect(screen.queryByRole('link', { name: 'Provider 对比' })).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: '管理控制台' })).toHaveAttribute('href', '/admin/rss')
  })

  it('shows a visible warning when server logout fails without an unhandled rejection', async () => {
    authState.user = { id: 7, username: 'reader', isSuperuser: false }
    authState.logout.mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce(undefined)
    renderHeader()

    fireEvent.click(screen.getByRole('button', { name: '打开菜单' }))
    fireEvent.click(screen.getByRole('button', { name: '退出登录' }))
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('退出请求未完成，服务端会话可能仍有效。请刷新后确认。')
    expect(alert.closest('header')).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: '打开菜单' }))
    fireEvent.click(screen.getByRole('button', { name: '退出登录' }))
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})
