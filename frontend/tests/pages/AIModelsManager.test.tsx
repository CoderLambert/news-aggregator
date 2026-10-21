import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import '@tests/helpers/commandDom'
import AIModelsManager from '@/components/workspace/AIModelsManager'
import * as api from '@/services/aiConnectionsApi'

vi.mock('@/services/aiConnectionsApi', async original => ({
  ...await original<typeof import('@/services/aiConnectionsApi')>(),
  listAIModels: vi.fn(), listAIModelCatalog: vi.fn(), createAIModel: vi.fn(),
  patchAIModel: vi.fn(), deleteAIModel: vi.fn(), probeAIModel: vi.fn(),
  discoverAIModels: vi.fn(), getAIConnectionDiagnostics: vi.fn(),
}))
const connection = {
  id: 'connection-synthetic-id', provider_id: 'deepseek', provider_name: 'DeepSeek',
  endpoint_profile: 'deepseek_default', endpoint_profile_version: 1, display_name: 'Test Connection',
  region_name: 'test', key_saved: true, masked_key: '••••', is_enabled: true,
  revision: 1, credential_epoch: 1, verification_status: 'not_tested' as const,
  updated_at: '2026-10-18T00:00:00Z',
}
const model: api.AIModel = {
  id: 'model-synthetic-id', connection_id: connection.id, model_id: 'deepseek-chat',
  display_name: 'DeepSeek Chat', catalog_model_id: 'deepseek-chat',
  config_revision: 1, capabilities: { text: 'unknown', tools: 'unknown' },
  has_trusted_route: true, article_chat_supported: true, context_window_tokens: null, updated_at: '2026-10-18T00:00:00Z',
}
beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(api.discoverAIModels).mockReset().mockResolvedValue({ models: ['org/model:cloud'], truncated: false })
  vi.mocked(api.listAIModels).mockReset().mockResolvedValue([model])
  vi.mocked(api.listAIModelCatalog).mockReset().mockResolvedValue({
    catalog_version: 'synthetic', models: [{
      model_id: 'deepseek-chat', display_name: 'DeepSeek Chat',
      catalog_version: 'synthetic', context_window_tokens: null, text: 'unknown', tools: 'unknown',
    }],
  })
  vi.mocked(api.createAIModel).mockReset().mockResolvedValue(model)
  vi.mocked(api.patchAIModel).mockReset().mockResolvedValue(model)
  vi.mocked(api.deleteAIModel).mockReset().mockResolvedValue({ deleted: true })
  vi.mocked(api.probeAIModel).mockReset().mockResolvedValue({
    attempt_id: 'synthetic-attempt', request_id: 'synthetic-request', model_id: model.model_id,
    probe_kind: 'text', status: 'succeeded', capability: 'supported', stale: false,
    safe_error_code: '', input_tokens: 4, output_tokens: 1, latency_ms: 20,
    billing_notice: 'provider_may_bill',
  })
})
afterEach(cleanup)
async function ready() {
  await screen.findByRole('region', { name: '模型 DeepSeek Chat' })
  const summary = screen.getByText('添加模型', { exact: true }).closest('summary')!
  if (!summary.parentElement?.hasAttribute('open')) fireEvent.click(summary)
}
describe('T02 per-connection models and explicit billing consent', () => {
  it('keeps discovered IDs unselected until the user makes an explicit choice', async () => {
    vi.mocked(api.listAIModelCatalog).mockResolvedValue({ catalog_version: 'empty', models: [] })
    render(<AIModelsManager connection={{ ...connection, model_discovery_supported: true }} viewer={3} />)
    await ready()
    fireEvent.click(screen.getByRole('button', { name: '发现服务端模型' }))
    await screen.findByText(/发现 1 个模型/)
    expect(screen.getByRole('combobox', { name: '预置模型（可选）' })).toHaveTextContent('搜索并选择模型')
    fireEvent.click(screen.getByRole('combobox', { name: '预置模型（可选）' }))
    await screen.findByRole('option', { name: /org\/model:cloud/ })
    fireEvent.keyDown(screen.getByLabelText('搜索模型'), { key: 'Escape' })
    expect(screen.getByRole('button', { name: '添加模型（不调用服务商）' })).toBeDisabled()
    expect(api.createAIModel).not.toHaveBeenCalled()
  })
  it('aborts a late discovery result after the viewer leaves', async () => {
    let finish!: (result: { models: string[]; truncated: boolean }) => void
    vi.mocked(api.discoverAIModels).mockImplementation(() => new Promise(resolve => { finish = resolve }))
    const first = render(<AIModelsManager connection={{ ...connection, model_discovery_supported: true }} viewer={3} />)
    await ready()
    fireEvent.click(screen.getByRole('button', { name: '发现服务端模型' }))
    const signal = vi.mocked(api.discoverAIModels).mock.calls[0][2]
    first.unmount()
    render(<AIModelsManager connection={connection} viewer={4} />)
    await ready()
    await act(async () => finish({ models: ['prior-viewer-private-model'], truncated: false }))
    expect(signal?.aborted).toBe(true)
    expect(screen.queryByRole('option', { name: /prior-viewer-private-model/ })).toBeNull()
  })
  it('keeps manual entry usable when the optional preset catalog fails', async () => {
    vi.mocked(api.listAIModelCatalog).mockRejectedValue(new api.ConnectionRequestError(0))
    render(<AIModelsManager connection={connection} viewer={3} />)
    await ready()
    fireEvent.change(screen.getByLabelText('或手动填写模型 ID'), { target: { value: 'org/manual:cloud' } })
    fireEvent.click(screen.getByRole('button', { name: '添加模型（不调用服务商）' }))
    await waitFor(() => expect(api.createAIModel).toHaveBeenCalledWith(connection, 'org/manual:cloud', 3, expect.any(AbortSignal)))
    expect(api.probeAIModel).not.toHaveBeenCalled()
  })
  it('discovers only after a click and preserves manual entry after discovery failure', async () => {
    vi.mocked(api.discoverAIModels).mockRejectedValue(new api.ConnectionRequestError(0))
    render(<AIModelsManager connection={{ ...connection, model_discovery_supported: true }} viewer={3} />)
    await ready()
    expect(api.discoverAIModels).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: '发现服务端模型' }))
    await waitFor(() => expect(api.discoverAIModels).toHaveBeenCalledOnce())
    expect(screen.getByLabelText('或手动填写模型 ID')).toBeEnabled()
    expect(api.probeAIModel).not.toHaveBeenCalled()
  })
  it('GET loads metadata only; never auto tests text or tools', async () => {
    render(<AIModelsManager connection={connection} viewer={3} />)
    await ready()
    expect(api.listAIModels).toHaveBeenCalledOnce()
    expect(api.listAIModelCatalog).toHaveBeenCalledOnce()
    expect(api.probeAIModel).not.toHaveBeenCalled()
    expect(screen.getAllByText(/未知/, { selector: '[data-slot=badge]' })).toHaveLength(2)
    expect(screen.getByRole('button', { name: '测试文本能力' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '测试工具能力' })).toBeDisabled()
  })
  it('requires active checkbox; tests one capability with viewer and stable request ID', async () => {
    render(<AIModelsManager connection={connection} viewer={3} />)
    await ready()
    fireEvent.click(screen.getByRole('checkbox', { name: /我确认主动测试可能产生服务商费用/ }))
    const textButton = screen.getByRole('button', { name: '测试文本能力' })
    expect(textButton).toBeEnabled()
    fireEvent.click(textButton)
    await waitFor(() => expect(api.probeAIModel).toHaveBeenCalledOnce())
    const [originalConnection, selectedModel, kind, requestId, viewer, signal] = vi.mocked(api.probeAIModel).mock.calls[0]
    expect(originalConnection.id).toBe(connection.id)
    expect(selectedModel.id).toBe(model.id)
    expect(kind).toBe('text')
    expect(requestId).toMatch(/^[a-f0-9-]{36}$/)
    expect(viewer).toBe(3)
    expect(signal).toBeInstanceOf(AbortSignal)
    expect(api.createAIModel).not.toHaveBeenCalled()
  })
  it('saving a new model does not invoke a paid probe', async () => {
    render(<AIModelsManager connection={connection} viewer={3} />)
    await ready()
    fireEvent.change(screen.getByLabelText('或手动填写模型 ID'), { target: { value: 'some-private-manual-model' } })
    fireEvent.click(screen.getByRole('button', { name: '添加模型（不调用服务商）' }))
    await waitFor(() => expect(api.createAIModel).toHaveBeenCalledWith(connection, 'some-private-manual-model', 3, expect.any(AbortSignal)))
    expect(api.probeAIModel).not.toHaveBeenCalled()
  })
  it('unknown response freezes writes and does not repeat a paid request on reload', async () => {
    vi.mocked(api.probeAIModel).mockRejectedValue(new api.ConnectionRequestError(0))
    render(<AIModelsManager connection={connection} viewer={3} />)
    await ready()
    fireEvent.click(screen.getByRole('checkbox', { name: /我确认主动测试可能产生服务商费用/ }))
    fireEvent.click(screen.getByRole('button', { name: '测试工具能力' }))
    await screen.findByText(/模型状态未知/)
    expect(api.probeAIModel).toHaveBeenCalledOnce()
    fireEvent.click(screen.getByRole('button', { name: '重新读取模型' }))
    await ready()
    expect(api.probeAIModel).toHaveBeenCalledOnce()
  })
  it('unmount cancels in-flight mutation and ignores the late response', async () => {
    let finish!: (value: api.AIModel) => void
    vi.mocked(api.createAIModel).mockImplementation(() => new Promise(resolve => { finish = resolve }))
    const view = render(<AIModelsManager connection={connection} viewer={3} />)
    await ready()
    fireEvent.click(screen.getByRole('button', { name: '添加模型（不调用服务商）' }))
    const signal = vi.mocked(api.createAIModel).mock.calls[0][3]
    view.unmount()
    const count = vi.mocked(api.listAIModels).mock.calls.length
    await act(async () => finish(model))
    expect(signal?.aborted).toBe(true)
    expect(api.listAIModels).toHaveBeenCalledTimes(count)
  })
})
