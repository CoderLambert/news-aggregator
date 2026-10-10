import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import SettingsPage from '@/pages/SettingsPage'
import { CapabilitiesTestProvider } from '../helpers/capabilities'

const preferences = vi.hoisted(() => ({
  lang: 'zh' as const,
  displayMode: 'zh' as const,
  setLang: vi.fn(),
  setDisplayMode: vi.fn(),
}))
const authState = vi.hoisted(() => ({ user: { id: 7, username: 'reader', isSuperuser: true as boolean } }))

vi.mock('@/context/AuthContext', () => ({ useAuth: () => authState }))
vi.mock('@/context/useLanguage', () => ({
  useLanguage: () => ({ ...preferences, t: { admin: '后台管理' } }),
}))

beforeEach(() => {
  vi.clearAllMocks()
  authState.user = { id: 7, username: 'reader', isSuperuser: true }
})

describe('SettingsPage', () => {
  it('keeps reading preferences, account connection, and tools in clear sections', () => {
    render(<MemoryRouter><CapabilitiesTestProvider><SettingsPage /></CapabilitiesTestProvider></MemoryRouter>)
    expect(screen.getByRole('heading', { name: '阅读偏好' })).toBeTruthy()
    expect(screen.getByRole('heading', { name: '账号与连接' })).toBeTruthy()
    expect(screen.getByRole('heading', { name: '站点工具' })).toBeTruthy()
    expect(screen.getByRole('group', { name: '界面语言' })).toBeTruthy()
    expect(screen.getByRole('link', { name: '管理连接' }).getAttribute('href')).toBe('/settings/chatgpt')

    fireEvent.click(screen.getByRole('button', { name: /双文/ }))
    expect(preferences.setDisplayMode).toHaveBeenCalledWith('bilingual')
    fireEvent.click(screen.getByRole('button', { name: 'English' }))
    expect(preferences.setLang).toHaveBeenCalledWith('en')
  })

  it('hides the Provider comparisons entry from a regular account', () => {
    authState.user = { id: 8, username: 'reader', isSuperuser: false }
    render(<MemoryRouter><CapabilitiesTestProvider><SettingsPage /></CapabilitiesTestProvider></MemoryRouter>)

    expect(screen.queryByRole('link', { name: 'Provider 对比' })).not.toBeInTheDocument()
  })
})
