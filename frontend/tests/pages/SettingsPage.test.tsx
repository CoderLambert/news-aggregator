import { fireEvent, render, screen, waitFor } from '@testing-library/react'
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
const api = vi.hoisted(() => ({
  fetchProviderCredentialStatus: vi.fn(),
  saveProviderCredential: vi.fn(),
  deleteProviderCredential: vi.fn(),
}))

vi.mock('@/context/AuthContext', () => ({ useAuth: () => authState }))
vi.mock('@/context/useLanguage', () => ({
  useLanguage: () => ({ ...preferences, t: { admin: '后台管理' } }),
}))
vi.mock('@/services/api', () => api)

beforeEach(() => {
  vi.clearAllMocks()
  authState.user = { id: 7, username: 'reader', isSuperuser: true }
  api.fetchProviderCredentialStatus.mockResolvedValue({
    configured: false,
    requiresReplacement: false,
    provider: null,
    providerLabel: null,
    modelId: null,
    updatedAt: null,
  })
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

  it('saves an allow-listed LiteLLM provider, model ID, and personal key', async () => {
    api.saveProviderCredential.mockResolvedValue({
      configured: true,
      requiresReplacement: false,
      provider: 'openrouter',
      providerLabel: 'OpenRouter',
      modelId: 'anthropic/claude-sonnet-4',
      updatedAt: '2026-10-13T00:00:00Z',
    })
    render(<MemoryRouter><CapabilitiesTestProvider><SettingsPage /></CapabilitiesTestProvider></MemoryRouter>)

    await waitFor(() => expect(api.fetchProviderCredentialStatus).toHaveBeenCalledTimes(1))
    fireEvent.change(screen.getByLabelText('模型提供方'), { target: { value: 'openrouter' } })
    fireEvent.change(screen.getByLabelText('Model ID'), { target: { value: 'anthropic/claude-sonnet-4' } })
    fireEvent.change(screen.getByLabelText('API Key'), { target: { value: 'synthetic-user-key' } })
    fireEvent.click(screen.getByRole('button', { name: '保存 Key' }))

    await waitFor(() => expect(api.saveProviderCredential).toHaveBeenCalledWith(
      'openrouter', 'anthropic/claude-sonnet-4', 'synthetic-user-key',
    ))
    expect(await screen.findByText('OpenRouter / anthropic/claude-sonnet-4', { exact: false })).toBeInTheDocument()
  })

  it('allows a disabled legacy credential to be deleted', async () => {
    api.fetchProviderCredentialStatus.mockResolvedValue({
      configured: false,
      requiresReplacement: true,
      provider: null,
      providerLabel: null,
      modelId: null,
      updatedAt: '2026-10-13T00:00:00Z',
    })
    render(<MemoryRouter><CapabilitiesTestProvider><SettingsPage /></CapabilitiesTestProvider></MemoryRouter>)

    expect(await screen.findByText('旧版直连凭据已停用，请替换')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '删除 Key' })).toBeInTheDocument()
  })
})
