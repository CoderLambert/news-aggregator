import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import AIModelSettingsPage from '@/pages/AIModelSettingsPage'
import type { AIConnection, AIModelConfig, AIModelPreset, AIProviderProfile } from '@/services/api'

const mocks = vi.hoisted(() => ({
  fetchAIProviderProfiles: vi.fn(),
  fetchAIConnections: vi.fn(),
  fetchAIModelCatalog: vi.fn(),
  fetchAIModels: vi.fn(),
  createAIConnection: vi.fn(),
  createAIModel: vi.fn(),
  replaceAIConnectionKey: vi.fn(),
  updateAIConnection: vi.fn(),
  deleteAIConnection: vi.fn(),
  deleteAIModel: vi.fn(),
  updateAIModel: vi.fn(),
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

const modelPreset: AIModelPreset = {
  catalog_model_id: 'deepseek-flash', provider_id: 'deepseek', model_id: 'deepseek-flash',
  display_name: 'DeepSeek V4.1 Flash', context_window_tokens: 1_048_576, max_output_tokens: 393_216,
  catalog_version: '2026-10-12.1', source_url: 'https://api-docs.deepseek.com/api/list-models/',
  provider_claims: { tools: true, stream: true },
}

const modelConfig: AIModelConfig = {
  id: 'model-17', connection_id: 'connection-17', model_id: 'vendor/custom-model',
  display_name: 'vendor/custom-model', source: 'manual', catalog_model_id: '', catalog_version: '',
  catalog_source_url: '', provider_claims: {}, context_window_tokens: null, max_output_tokens: null,
  has_trusted_context_limit: false, config_revision: 1, verification_status: 'not_tested',
  capabilities: { text: 'unknown', tools: 'unknown', structured_output: 'unknown', thinking: 'unknown', stream: 'unknown' },
  last_tested_at: null, updated_at: '2026-10-12T00:00:00Z',
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
  mocks.fetchAIModelCatalog.mockResolvedValue({ catalog_version: '2026-10-12.1', models: [modelPreset], catalog_available: true })
  mocks.fetchAIModels.mockResolvedValue([])
  mocks.createAIConnection.mockResolvedValue(connection)
  mocks.createAIModel.mockResolvedValue(modelConfig)
  mocks.replaceAIConnectionKey.mockResolvedValue(connection)
  mocks.updateAIConnection.mockResolvedValue(connection)
  mocks.deleteAIConnection.mockResolvedValue({ deleted: true })
  mocks.deleteAIModel.mockResolvedValue({ deleted: true })
  mocks.updateAIModel.mockResolvedValue(modelConfig)
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

  it('allows manual model entry when the official model catalog is unavailable', async () => {
    mocks.fetchAIConnections.mockResolvedValue([connection])
    mocks.fetchAIModelCatalog.mockRejectedValue(new Error('synthetic catalog outage'))
    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: '添加模型' }))
    expect(await screen.findByText('官方目录暂不可用。你仍可手动输入模型 ID。')).toBeInTheDocument()
    const modelIdField = screen.getByLabelText('模型 ID')
    fireEvent.change(modelIdField, { target: { value: 'vendor/manual-model-2026' } })
    fireEvent.click(screen.getByRole('button', { name: '保存模型' }))

    await waitFor(() => expect(mocks.createAIModel).toHaveBeenCalledWith({
      connection_id: 'connection-17', model_id: 'vendor/manual-model-2026', display_name: '',
    }))
    expect(await screen.findByRole('status')).toHaveTextContent('模型已保存，当前未测试；保存模型不会调用服务商。')
  })

  it('saves an official preset without treating provider-declared capabilities as verified', async () => {
    mocks.fetchAIConnections.mockResolvedValue([connection])
    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: '添加模型' }))
    fireEvent.change(screen.getByLabelText('官方模型预设'), { target: { value: 'deepseek-flash' } })
    expect(screen.getByText('已选：deepseek-flash')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '保存模型' }))

    await waitFor(() => expect(mocks.createAIModel).toHaveBeenCalledWith({
      connection_id: 'connection-17', catalog_model_id: 'deepseek-flash', display_name: '',
    }))
  })

  it('updates a model configuration without making a provider request', async () => {
    mocks.fetchAIConnections.mockResolvedValue([connection])
    mocks.fetchAIModels.mockResolvedValue([modelConfig])
    mocks.updateAIModel.mockResolvedValue({
      ...modelConfig, model_id: 'vendor/custom-model-v2', display_name: 'My model', config_revision: 2,
    })
    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: '编辑模型' }))
    fireEvent.change(screen.getByLabelText('模型 ID'), { target: { value: 'vendor/custom-model-v2' } })
    fireEvent.change(screen.getByLabelText('显示名称'), { target: { value: 'My model' } })
    fireEvent.click(screen.getByRole('button', { name: '保存模型修改' }))

    await waitFor(() => expect(mocks.updateAIModel).toHaveBeenCalledWith('model-17', {
      model_id: 'vendor/custom-model-v2', display_name: 'My model',
    }))
    expect(await screen.findByRole('status')).toHaveTextContent('模型配置已更新；此前的测试结果已失效。')
    expect(screen.queryByRole('button', { name: /测试模型/ })).not.toBeInTheDocument()
  })
})
