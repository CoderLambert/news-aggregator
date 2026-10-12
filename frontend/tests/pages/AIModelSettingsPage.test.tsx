import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import AIModelSettingsPage from '@/pages/AIModelSettingsPage'
import type { AIConnection, AIModelConfig, AIModelPreset, AIProviderProfile, AITaskKind, AITaskPreference, SaveAITaskPreference } from '@/services/api'

const mocks = vi.hoisted(() => ({
  fetchAIProviderProfiles: vi.fn(),
  fetchAIConnections: vi.fn(),
  fetchAIModelCatalog: vi.fn(),
  fetchAIModels: vi.fn(),
  fetchAITaskPreferences: vi.fn(),
  saveAITaskPreferences: vi.fn(),
  createAIConnection: vi.fn(),
  createAIModel: vi.fn(),
  replaceAIConnectionKey: vi.fn(),
  updateAIConnection: vi.fn(),
  deleteAIConnection: vi.fn(),
  deleteAIModel: vi.fn(),
  updateAIModel: vi.fn(),
  testAIModel: vi.fn(),
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

function routedModelConfig(id = 'model-17', displayName = 'DeepSeek V4.1 Flash'): AIModelConfig {
  return {
    ...modelConfig,
    id,
    model_id: 'deepseek-flash',
    display_name: displayName,
    source: 'catalog',
    catalog_model_id: 'deepseek-flash',
    catalog_version: '2026-10-12.1',
    catalog_source_url: modelPreset.source_url,
    provider_claims: modelPreset.provider_claims,
    context_window_tokens: 1_048_576,
    max_output_tokens: 393_216,
    has_trusted_context_limit: true,
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

const taskKinds: AITaskKind[] = ['default', 'article_qa', 'full_translation', 'deep_research', 'question_suggestions']

function preferenceSet(
  selected: Partial<Record<AITaskKind, string | null>> = {},
  unavailable: AITaskKind[] = [],
): AITaskPreference[] {
  return taskKinds.map((task_kind) => {
    const model_config_id = selected[task_kind] ?? null
    const selection_state = unavailable.includes(task_kind)
      ? 'needs_reselection'
      : model_config_id !== null
        ? 'available'
        : task_kind === 'default' ? 'unset' : 'inherit_default'
    return {
      task_kind,
      model_config_id,
      selection_state,
      model: model_config_id === modelConfig.id ? {
        id: modelConfig.id,
        model_id: modelConfig.model_id,
        display_name: modelConfig.display_name,
        connection_id: modelConfig.connection_id,
      } : null,
    }
  })
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
  mocks.fetchAITaskPreferences.mockResolvedValue(preferenceSet())
  mocks.saveAITaskPreferences.mockImplementation(async (preferences: SaveAITaskPreference[]) => preferenceSet(
    Object.fromEntries(preferences.map(({ task_kind, model_config_id }) => [task_kind, model_config_id])) as Partial<Record<AITaskKind, string | null>>,
  ))
  mocks.createAIConnection.mockResolvedValue(connection)
  mocks.createAIModel.mockResolvedValue(modelConfig)
  mocks.replaceAIConnectionKey.mockResolvedValue(connection)
  mocks.updateAIConnection.mockResolvedValue(connection)
  mocks.deleteAIConnection.mockResolvedValue({ deleted: true })
  mocks.deleteAIModel.mockResolvedValue({ deleted: true })
  mocks.updateAIModel.mockResolvedValue(modelConfig)
  mocks.testAIModel.mockResolvedValue({
    attempt_id: 'attempt-17', probe_kind: 'text', status: 'succeeded',
    verification_status: 'verified', capability: 'supported', stale: false,
    safe_error_code: '', latency_ms: 120, input_tokens: 8, output_tokens: 2,
    billing_notice: 'provider_may_bill',
  })
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
    expect(await screen.findByText('模型配置已更新；此前的测试结果已失效。')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /测试模型/ })).not.toBeInTheDocument()
  })

  it('requires a billing confirmation before testing each capability on a routed preset', async () => {
    mocks.fetchAIConnections.mockResolvedValue([connection])
    mocks.fetchAIModels.mockResolvedValue([routedModelConfig()])
    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: '测试文本能力' }))
    expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining('可能产生费用'))
    await waitFor(() => expect(mocks.testAIModel).toHaveBeenCalledWith('model-17', 'text'))
    expect(await screen.findByText('文本能力测试成功。')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '测试工具能力' }))
    await waitFor(() => expect(mocks.testAIModel).toHaveBeenCalledWith('model-17', 'tools'))
    expect(window.confirm).toHaveBeenCalledTimes(2)
  })

  it('keeps confirmation cancellation at zero requests', async () => {
    mocks.fetchAIConnections.mockResolvedValue([connection])
    mocks.fetchAIModels.mockResolvedValue([routedModelConfig()])
    vi.stubGlobal('confirm', vi.fn(() => false))
    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: '测试文本能力' }))

    expect(window.confirm).toHaveBeenCalledOnce()
    expect(mocks.testAIModel).not.toHaveBeenCalled()
    expect(screen.queryByText('正在测试文本能力…')).not.toBeInTheDocument()
  })

  it('shows pending feedback beside the model and restores its button after completion', async () => {
    const request = deferred<Awaited<ReturnType<typeof mocks.testAIModel>>>()
    mocks.fetchAIConnections.mockResolvedValue([connection])
    mocks.fetchAIModels.mockResolvedValue([routedModelConfig()])
    mocks.testAIModel.mockReturnValueOnce(request.promise)
    renderPage()

    const button = await screen.findByRole('button', { name: '测试文本能力' })
    fireEvent.click(button)

    expect(await screen.findByText('正在测试文本能力…')).toBeInTheDocument()
    expect(button).toBeDisabled()
    request.resolve({
      attempt_id: 'attempt-pending', probe_kind: 'text', status: 'succeeded',
      verification_status: 'verified', capability: 'supported', stale: false,
      safe_error_code: '', latency_ms: 120, input_tokens: 8, output_tokens: 2,
      billing_notice: 'provider_may_bill',
    })

    expect(await screen.findByText('文本能力测试成功。')).toBeInTheDocument()
    await waitFor(() => expect(button).toBeEnabled())
    await waitFor(() => expect(mocks.fetchAIModels).toHaveBeenCalledTimes(2))
  })

  it('refreshes saved connection and model state through the visible GET-only refresh button', async () => {
    mocks.fetchAIConnections.mockResolvedValue([connection])
    mocks.fetchAIModels.mockResolvedValue([routedModelConfig()])
    renderPage()

    expect(await screen.findByText('模型 ID：deepseek-flash')).toBeInTheDocument()
    expect(mocks.fetchAIConnections).toHaveBeenCalledOnce()
    expect(mocks.fetchAIModels).toHaveBeenCalledOnce()

    fireEvent.click(screen.getByRole('button', { name: '刷新连接和模型' }))

    await waitFor(() => {
      expect(mocks.fetchAIConnections).toHaveBeenCalledTimes(2)
      expect(mocks.fetchAIModels).toHaveBeenCalledTimes(2)
    })
    expect(mocks.testAIModel).not.toHaveBeenCalled()
  })

  it('ignores an old successful test response after the model configuration changes', async () => {
    const request = deferred<Awaited<ReturnType<typeof mocks.testAIModel>>>()
    mocks.fetchAIConnections.mockResolvedValue([connection])
    mocks.fetchAIModels.mockResolvedValue([routedModelConfig()])
    mocks.testAIModel.mockReturnValueOnce(request.promise)
    mocks.updateAIModel.mockResolvedValue({
      ...routedModelConfig(), model_id: 'deepseek-flash-v2', display_name: 'Updated Flash', config_revision: 2,
    })
    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: '测试文本能力' }))
    expect(await screen.findByText('正在测试文本能力…')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '编辑模型' }))
    fireEvent.change(screen.getByLabelText('模型 ID'), { target: { value: 'deepseek-flash-v2' } })
    fireEvent.change(screen.getByLabelText('显示名称'), { target: { value: 'Updated Flash' } })
    fireEvent.click(screen.getByRole('button', { name: '保存模型修改' }))
    await screen.findByText('模型配置已更新；此前的测试结果已失效。')

    request.resolve({
      attempt_id: 'attempt-old-success', probe_kind: 'text', status: 'succeeded',
      verification_status: 'verified', capability: 'supported', stale: false,
      safe_error_code: '', latency_ms: 120, input_tokens: 8, output_tokens: 2,
      billing_notice: 'provider_may_bill',
    })

    const button = await screen.findByRole('button', { name: '测试文本能力' })
    await waitFor(() => expect(button).toBeEnabled())
    expect(screen.queryByText('文本能力测试成功。')).not.toBeInTheDocument()
    expect(screen.queryByText('正在测试文本能力…')).not.toBeInTheDocument()
  })

  it('ignores an old failed test response after replacing its connection key', async () => {
    const request = deferred<Awaited<ReturnType<typeof mocks.testAIModel>>>()
    mocks.fetchAIConnections.mockResolvedValue([connection])
    mocks.fetchAIModels.mockResolvedValue([routedModelConfig()])
    mocks.testAIModel.mockReturnValueOnce(request.promise)
    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: '测试文本能力' }))
    expect(await screen.findByText('正在测试文本能力…')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '替换 Key' }))
    fireEvent.change(screen.getByLabelText('输入新的 API Key'), { target: { value: 'sk-t01-delayed-test-replacement-synthetic' } })
    fireEvent.click(screen.getByRole('button', { name: '确认替换' }))
    expect(await screen.findByText('Key 已替换，旧凭据版本已失效。本站尚未测试新 Key。')).toBeInTheDocument()

    request.reject(Object.assign(new Error('old test failure'), {
      response: { status: 502, data: { error_code: 'gateway_rejected' } },
    }))

    const button = await screen.findByRole('button', { name: '测试文本能力' })
    await waitFor(() => expect(button).toBeEnabled())
    expect(screen.queryByText(/网关拒绝了本次测试/)).not.toBeInTheDocument()
    expect(screen.queryByText('正在测试文本能力…')).not.toBeInTheDocument()
  })

  it('keeps model A pending feedback when connection B changes', async () => {
    const secondConnection: AIConnection = {
      ...connection, id: 'connection-18', display_name: 'DeepSeek · 第二连接', masked_key: '••••••18',
    }
    const firstModel = routedModelConfig('model-17', 'DeepSeek Flash A')
    const secondModel = { ...routedModelConfig('model-18', 'DeepSeek Flash B'), connection_id: secondConnection.id }
    const request = deferred<Awaited<ReturnType<typeof mocks.testAIModel>>>()
    mocks.fetchAIConnections.mockResolvedValue([connection, secondConnection])
    mocks.fetchAIModels.mockResolvedValue([firstModel, secondModel])
    mocks.testAIModel
      .mockResolvedValueOnce({
        attempt_id: 'attempt-b', probe_kind: 'text', status: 'succeeded',
        verification_status: 'verified', capability: 'supported', stale: false,
        safe_error_code: '', latency_ms: 120, input_tokens: 8, output_tokens: 2,
        billing_notice: 'provider_may_bill',
      })
      .mockReturnValueOnce(request.promise)
    renderPage()

    let modelB = (await screen.findByText('DeepSeek Flash B')).closest('li') as HTMLElement
    fireEvent.click(within(modelB).getByRole('button', { name: '测试文本能力' }))
    expect(await within(modelB).findByText('文本能力测试成功。')).toBeInTheDocument()

    const modelA = screen.getByText('DeepSeek Flash A').closest('li') as HTMLElement
    fireEvent.click(within(modelA).getByRole('button', { name: '测试文本能力' }))
    expect(await within(modelA).findByText('正在测试文本能力…')).toBeInTheDocument()

    fireEvent.click(screen.getAllByRole('button', { name: '停用' })[1])
    await waitFor(() => expect(mocks.updateAIConnection).toHaveBeenCalledWith('connection-18', { is_enabled: false }))

    modelB = screen.getByText('DeepSeek Flash B').closest('li') as HTMLElement
    expect(within(modelA).getByText('正在测试文本能力…')).toBeInTheDocument()
    expect(within(modelB).queryByText('文本能力测试成功。')).not.toBeInTheDocument()

    request.resolve({
      attempt_id: 'attempt-a', probe_kind: 'text', status: 'succeeded',
      verification_status: 'verified', capability: 'supported', stale: false,
      safe_error_code: '', latency_ms: 120, input_tokens: 8, output_tokens: 2,
      billing_notice: 'provider_may_bill',
    })
    expect(await within(modelA).findByText('文本能力测试成功。')).toBeInTheDocument()
  })

  it('keeps a gateway precheck error on its model card and leaves capability untested', async () => {
    const gatewayError = Object.assign(new Error('raw response must stay hidden'), {
      response: { status: 503, data: { error_code: 'model_test_gateway_unavailable', error: 'do not display raw response' } },
    })
    mocks.fetchAIConnections.mockResolvedValue([connection])
    mocks.fetchAIModels.mockResolvedValue([routedModelConfig()])
    mocks.testAIModel.mockRejectedValueOnce(gatewayError)
    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: '测试文本能力' }))
    const feedback = await screen.findByText('本次未发送：个人模型网关暂不可用，能力仍为“未测试”。')
    const modelCard = feedback.closest('li')

    expect(modelCard).not.toBeNull()
    expect(within(modelCard as HTMLElement).getByText(/文本：unknown · 工具：unknown · 未测试/)).toBeInTheDocument()
    expect(screen.queryByText('raw response must stay hidden')).not.toBeInTheDocument()
    expect(screen.queryByText('do not display raw response')).not.toBeInTheDocument()
    expect(mocks.fetchAIModels).toHaveBeenCalledOnce()
  })

  it('marks a timed out model test unconfirmed and never retries it', async () => {
    const timeoutError = Object.assign(new Error('timeout'), { code: 'ECONNABORTED' })
    mocks.fetchAIConnections.mockResolvedValue([connection])
    mocks.fetchAIModels.mockResolvedValue([routedModelConfig()])
    mocks.testAIModel.mockRejectedValueOnce(timeoutError)
    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: '测试文本能力' }))

    expect(await screen.findByText(/无法确认是否到达服务商/)).toBeInTheDocument()
    expect(mocks.testAIModel).toHaveBeenCalledTimes(1)
    expect(mocks.saveAITaskPreferences).not.toHaveBeenCalled()
  })

  it('keeps feedback attached to its model when another model returns a different result', async () => {
    const firstModel = routedModelConfig('model-17', 'DeepSeek Flash A')
    const secondModel = routedModelConfig('model-18', 'DeepSeek Flash B')
    mocks.fetchAIConnections.mockResolvedValue([connection])
    mocks.fetchAIModels.mockResolvedValue([firstModel, secondModel])
    mocks.testAIModel
      .mockResolvedValueOnce({
        attempt_id: 'attempt-a', probe_kind: 'text', status: 'succeeded',
        verification_status: 'verified', capability: 'supported', stale: false,
        safe_error_code: '', latency_ms: 120, input_tokens: 8, output_tokens: 2,
        billing_notice: 'provider_may_bill',
      })
      .mockResolvedValueOnce({
        attempt_id: 'attempt-b', probe_kind: 'text', status: 'failed',
        verification_status: 'failed', capability: 'unknown', stale: false,
        safe_error_code: 'gateway_rejected', latency_ms: 110, input_tokens: null, output_tokens: null,
        billing_notice: 'provider_may_bill',
      })
    renderPage()

    let buttons = await screen.findAllByRole('button', { name: '测试文本能力' })
    fireEvent.click(buttons[0])
    await within(screen.getByText('DeepSeek Flash A').closest('li') as HTMLElement).findByText('文本能力测试成功。')

    buttons = screen.getAllByRole('button', { name: '测试文本能力' })
    fireEvent.click(buttons[1])
    await within(screen.getByText('DeepSeek Flash B').closest('li') as HTMLElement).findByText(/网关拒绝了本次测试/)

    expect(within(screen.getByText('DeepSeek Flash A').closest('li') as HTMLElement).getByText('文本能力测试成功。')).toBeInTheDocument()
    expect(within(screen.getByText('DeepSeek Flash B').closest('li') as HTMLElement).queryByText('文本能力测试成功。')).not.toBeInTheDocument()
  })

  it('does not offer a gateway test for an unknown manual model ID', async () => {
    mocks.fetchAIConnections.mockResolvedValue([connection])
    mocks.fetchAIModels.mockResolvedValue([modelConfig])
    renderPage()

    expect(await screen.findByText('该手动模型尚无预批准网关路由，暂不可测试。')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '测试文本能力' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '测试工具能力' })).not.toBeInTheDocument()
  })

  it('keeps preference drafts local until save and can revert them', async () => {
    mocks.fetchAIConnections.mockResolvedValue([connection])
    mocks.fetchAIModels.mockResolvedValue([modelConfig])
    renderPage()

    const defaultSelect = await screen.findByLabelText('全局默认：默认模型')
    expect(await screen.findByLabelText('新闻问答：使用模型')).toHaveValue('')
    fireEvent.change(defaultSelect, { target: { value: modelConfig.id } })

    expect(screen.getByText('当前选择尚未保存。')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '保存用途偏好' })).toBeEnabled()
    fireEvent.click(screen.getByRole('button', { name: '撤销修改' }))

    expect(defaultSelect).toHaveValue('')
    expect(screen.getByText('已撤销本页尚未保存的选择。')).toBeInTheDocument()
    expect(mocks.saveAITaskPreferences).not.toHaveBeenCalled()
  })

  it('saves all five preferences explicitly and preserves the saved selection', async () => {
    mocks.fetchAIConnections.mockResolvedValue([connection])
    mocks.fetchAIModels.mockResolvedValue([modelConfig])
    mocks.saveAITaskPreferences.mockResolvedValue(preferenceSet({
      default: modelConfig.id,
      article_qa: modelConfig.id,
    }))
    renderPage()

    fireEvent.change(await screen.findByLabelText('全局默认：默认模型'), { target: { value: modelConfig.id } })
    fireEvent.change(screen.getByLabelText('新闻问答：使用模型'), { target: { value: modelConfig.id } })
    fireEvent.click(screen.getByRole('button', { name: '保存用途偏好' }))

    await waitFor(() => expect(mocks.saveAITaskPreferences).toHaveBeenCalledWith([
      { task_kind: 'default', model_config_id: modelConfig.id },
      { task_kind: 'article_qa', model_config_id: modelConfig.id },
      { task_kind: 'full_translation', model_config_id: null },
      { task_kind: 'deep_research', model_config_id: null },
      { task_kind: 'question_suggestions', model_config_id: null },
    ]))
    expect(await screen.findByText('用途偏好已保存，只影响之后开始的任务；已开始的任务和历史结果保持不变。')).toBeInTheDocument()
    expect(screen.getByLabelText('全局默认：默认模型')).toHaveValue(modelConfig.id)
    expect(screen.getByLabelText('新闻问答：使用模型')).toHaveValue(modelConfig.id)
  })

  it('keeps unsaved choices and reports failure when saving preferences fails', async () => {
    mocks.fetchAIConnections.mockResolvedValue([connection])
    mocks.fetchAIModels.mockResolvedValue([modelConfig])
    mocks.saveAITaskPreferences.mockRejectedValue(new Error('synthetic preference outage'))
    renderPage()

    const defaultSelect = await screen.findByLabelText('全局默认：默认模型')
    fireEvent.change(defaultSelect, { target: { value: modelConfig.id } })
    fireEvent.click(screen.getByRole('button', { name: '保存用途偏好' }))

    expect(await screen.findByText('保存失败。未保存的选择仍留在本页，请检查连接状态后重试。')).toBeInTheDocument()
    expect(defaultSelect).toHaveValue(modelConfig.id)
    expect(screen.getByRole('button', { name: '保存用途偏好' })).toBeEnabled()
  })

  it('shows a disabled saved model as requiring reselection and blocks an unchanged stale save', async () => {
    mocks.fetchAIConnections.mockResolvedValue([{ ...connection, is_enabled: false }])
    mocks.fetchAIModels.mockResolvedValue([modelConfig])
    mocks.fetchAITaskPreferences.mockResolvedValue(preferenceSet({ default: modelConfig.id }, ['default']))
    renderPage()

    const defaultSelect = await screen.findByLabelText('全局默认：默认模型')
    expect(defaultSelect).toHaveValue(modelConfig.id)
    expect(screen.getByText('默认模型已停用或删除。请选择有效默认模型。')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '保存用途偏好' })).toBeDisabled()
    expect(screen.getByText('有用途指向不可用模型，请重新选择后保存。')).toBeInTheDocument()
  })
})
