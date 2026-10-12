import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import AIModelSettingsPage from '@/pages/AIModelSettingsPage'
import type { AIConnection, AIProviderProfile } from '@/services/api'

const mocks = vi.hoisted(() => ({
  fetchAIProviderProfiles: vi.fn(),
  fetchAIConnections: vi.fn(),
  createAIConnection: vi.fn(),
  replaceAIConnectionKey: vi.fn(),
  updateAIConnection: vi.fn(),
  deleteAIConnection: vi.fn(),
}))

const authState = vi.hoisted(() => ({
  user: { id: 17, username: 'owner', isSuperuser: false } as { id: number; username: string; isSuperuser: boolean } | null,
  loading: false,
}))

vi.mock('@/context/AuthContext', () => ({ useAuth: () => authState }))
vi.mock('@/services/api', () => mocks)

const providerProfiles: AIProviderProfile[] = [
  {
    provider_id: 'deepseek', provider_name: 'DeepSeek', profile_id: 'deepseek_default',
    region_name: '通用 API', base_url: 'https://api.deepseek.com', version: 1,
  },
]

const connection: AIConnection = {
  id: 'connection-17', provider_id: 'deepseek', provider_name: 'DeepSeek',
  endpoint_profile: 'deepseek_default', region_name: '通用 API', display_name: 'DeepSeek · 个人',
  key_saved: true, masked_key: '••••••••', is_enabled: true,
  verification_status: 'not_tested', updated_at: '2026-10-11T00:00:00Z',
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return { ...render(<MemoryRouter><QueryClientProvider client={client}><AIModelSettingsPage /></QueryClientProvider></MemoryRouter>), client }
}

beforeEach(() => {
  vi.clearAllMocks()
  window.localStorage.clear()
  window.sessionStorage.clear()
  authState.user = { id: 17, username: 'owner', isSuperuser: false }
  authState.loading = false
  mocks.fetchAIProviderProfiles.mockResolvedValue(providerProfiles)
  mocks.fetchAIConnections.mockResolvedValue([])
  mocks.createAIConnection.mockResolvedValue(connection)
  mocks.replaceAIConnectionKey.mockResolvedValue(connection)
  mocks.updateAIConnection.mockResolvedValue(connection)
  mocks.deleteAIConnection.mockResolvedValue({ deleted: true })
  vi.stubGlobal('confirm', vi.fn(() => true))
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('AIModelSettingsPage', () => {
  it('creates a connection without exposing the key in the response UI or browser storage', async () => {
    const secret = 'sk-t01-synthetic-browser-test-never-real'
    renderPage()

    const keyField = await screen.findByLabelText('API Key')
    fireEvent.change(screen.getByLabelText('连接名称（可选）'), { target: { value: '工作用 DeepSeek' } })
    fireEvent.change(keyField, { target: { value: secret } })
    fireEvent.click(screen.getByRole('button', { name: '保存连接' }))

    await waitFor(() => expect(mocks.createAIConnection).toHaveBeenCalledWith({
      provider_id: 'deepseek',
      endpoint_profile: 'deepseek_default',
      display_name: '工作用 DeepSeek',
      api_key: secret,
    }))
    await waitFor(() => expect(keyField).toHaveValue(''))
    expect(await screen.findByRole('status')).toHaveTextContent('连接已安全保存。本站尚未测试此 Key。')
    expect(screen.queryByText(secret)).not.toBeInTheDocument()
    expect(window.localStorage.length).toBe(0)
    expect(window.sessionStorage.length).toBe(0)
    expect(screen.queryByRole('button', { name: /测试|验证 Key/ })).not.toBeInTheDocument()
  })

  it('replaces, disables, and deletes a masked connection without provider test actions', async () => {
    mocks.fetchAIConnections.mockResolvedValue([connection])
    renderPage()

    expect(await screen.findByText('••••••••')).toBeInTheDocument()
    expect(screen.getByText('未测试 · 保存连接不会调用服务商')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '修改名称' }))
    fireEvent.change(screen.getByLabelText('连接名称'), { target: { value: '研究专用 DeepSeek' } })
    fireEvent.click(screen.getByRole('button', { name: '保存名称' }))
    await waitFor(() => expect(mocks.updateAIConnection).toHaveBeenCalledWith('connection-17', { display_name: '研究专用 DeepSeek' }))

    fireEvent.click(screen.getByRole('button', { name: '替换 Key' }))
    const replacementField = screen.getByLabelText('输入新的 API Key')
    fireEvent.change(replacementField, { target: { value: 'sk-t01-replacement-synthetic-never-real' } })
    fireEvent.click(screen.getByRole('button', { name: '确认替换' }))
    await waitFor(() => expect(mocks.replaceAIConnectionKey).toHaveBeenCalledWith('connection-17', 'sk-t01-replacement-synthetic-never-real'))

    fireEvent.click(screen.getByRole('button', { name: '停用' }))
    await waitFor(() => expect(mocks.updateAIConnection).toHaveBeenCalledWith('connection-17', { is_enabled: false }))

    fireEvent.click(screen.getByRole('button', { name: '删除' }))
    await waitFor(() => expect(mocks.deleteAIConnection).toHaveBeenCalledWith('connection-17'))
    expect(window.confirm).toHaveBeenCalledOnce()
    expect(window.localStorage.length).toBe(0)
    expect(window.sessionStorage.length).toBe(0)
  })

  it('shows no API key input before the owner signs in', async () => {
    authState.user = null
    renderPage()

    expect(await screen.findByRole('heading', { name: 'AI 模型与密钥' })).toBeInTheDocument()
    expect(screen.queryByLabelText('API Key')).not.toBeInTheDocument()
    expect(mocks.fetchAIProviderProfiles).not.toHaveBeenCalled()
    expect(mocks.fetchAIConnections).not.toHaveBeenCalled()
  })

  it('clears an unsaved key immediately when the signed-in account changes', async () => {
    const rendered = renderPage()
    const keyField = await screen.findByLabelText('API Key')
    fireEvent.change(keyField, { target: { value: 'sk-t01-unsaved-account-switch-synthetic' } })

    authState.user = { id: 28, username: 'next-owner', isSuperuser: false }
    rendered.rerender(<MemoryRouter><QueryClientProvider client={rendered.client}><AIModelSettingsPage /></QueryClientProvider></MemoryRouter>)

    expect(await screen.findByLabelText('API Key')).toHaveValue('')
    expect(screen.queryByText('sk-t01-unsaved-account-switch-synthetic')).not.toBeInTheDocument()
  })
})
