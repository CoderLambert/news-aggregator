import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import AITaskPreferencesSection from '@/components/workspace/AITaskPreferencesSection'
import * as api from '@/services/aiConnectionsApi'

vi.mock('@/services/aiConnectionsApi', async original => ({
  ...await original<typeof import('@/services/aiConnectionsApi')>(),
  listAITaskPreferences: vi.fn(), saveAITaskPreferences: vi.fn(),
  listAIModels: vi.fn(), probeAIModel: vi.fn(),
}))
const KINDS: api.AITaskKind[] = [
  'default','article_qa','full_translation','deep_research','question_suggestions',
]
const connection: api.AIConnection = {
  id: '11111111-1111-4111-8111-111111111111',
  provider_id: 'deepseek', provider_name: 'DeepSeek', endpoint_profile: 'deepseek_default',
  endpoint_profile_version: 1, display_name: '私人的连接', region_name: '默认路由',
  key_saved: true, masked_key: '••••', is_enabled: true,
  credential_epoch: 1, revision: 1, verification_status: 'not_tested',
  updated_at: '2026-10-18T00:00:00Z',
}
const textModel: api.AIModel = {
  id: '22222222-2222-4222-8222-222222222222', connection_id: connection.id,
  model_id: 'deepseek-chat', display_name: 'Text only', catalog_model_id: 'deepseek-chat',
  config_revision: 1, has_trusted_route: true, context_window_tokens: null,
  capabilities: { text: 'supported', tools: 'unknown' },
  updated_at: '2026-10-18T00:00:00Z',
}
const toolsModel: api.AIModel = {
  ...textModel, id: '33333333-3333-4333-8333-333333333333',
  display_name: 'Text + tools',
  capabilities: { text: 'supported', tools: 'supported' },
}
const initial: api.AITaskPreferences = {
  revision: 0, preferences: KINDS.map(kind => ({
    task_kind: kind, model_config_id: null,
    selection_state: kind === 'default' ? 'unset' : 'inherit_default', model: null,
  })),
}
let current: api.AITaskPreferences
let available: api.AIModel[]
beforeEach(() => {
  vi.clearAllMocks()
  current = initial
  available = [textModel, toolsModel]
  vi.mocked(api.listAITaskPreferences).mockReset().mockImplementation(async () => current)
  vi.mocked(api.listAIModels).mockReset().mockImplementation(async () => available)
  vi.mocked(api.saveAITaskPreferences).mockReset().mockImplementation(async (revision, selections) => {
    current = { revision: revision + 1, preferences: selections.map(item => ({
      ...item, selection_state: item.model_config_id ? 'available' :
        item.task_kind === 'default' ? 'unset' : 'inherit_default',
      model: null,
    })) as api.AITaskPreference[] }
    return current
  })
})
afterEach(cleanup)
function setup(viewer = 7) {
  return render(<AITaskPreferencesSection key={viewer} viewer={viewer} connections={[connection]} />)
}
async function ready() {
  await screen.findByRole('combobox', { name: '全局默认模型' })
}
describe('T03 model purpose settings', () => {
  it('loads metadata read-only and only submits after an explicit save of all five kinds', async () => {
    setup()
    await ready()
    expect(api.listAITaskPreferences).toHaveBeenCalledOnce()
    expect(api.listAIModels).toHaveBeenCalledOnce()
    expect(api.saveAITaskPreferences).not.toHaveBeenCalled()
    expect(api.probeAIModel).not.toHaveBeenCalled()
    fireEvent.change(screen.getByRole('combobox', { name: '全局默认模型' }), {
      target: { value: textModel.id },
    })
    expect(screen.getByText('存在未保存的用途变更。')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '保存用途偏好' }))
    await waitFor(() => expect(api.saveAITaskPreferences).toHaveBeenCalledOnce())
    const [revision, rows, viewer, signal] = vi.mocked(api.saveAITaskPreferences).mock.calls[0]
    expect(revision).toBe(0)
    expect(rows).toHaveLength(5)
    expect(rows[0]).toEqual({ task_kind: 'default', model_config_id: textModel.id })
    expect(rows.slice(1).every(row => row.model_config_id === null)).toBe(true)
    expect(viewer).toBe(7)
    expect(signal).toBeInstanceOf(AbortSignal)
    expect(api.probeAIModel).not.toHaveBeenCalled()
    await screen.findByText(/用途偏好已保存/)
  })
  it('can undo a draft without a write and disables unverified deep research choices', async () => {
    setup(); await ready()
    const research = screen.getByRole('combobox', { name: '深度研究模型' })
    expect(within(research).queryByText(/Text only/)).not.toBeInTheDocument()
    expect(within(research).getByText(/Text \+ tools/)).toBeInTheDocument()
    fireEvent.change(screen.getByRole('combobox', { name: '新闻问答模型' }), {
      target: { value: textModel.id },
    })
    fireEvent.click(screen.getByRole('button', { name: '撤销修改' }))
    expect(screen.getByRole('combobox', { name: '新闻问答模型' })).toHaveValue('')
    expect(api.saveAITaskPreferences).not.toHaveBeenCalled()
  })
  it('keeps unsaved draft but freezes resubmission after an uncertain PATCH, until GET reconciliation', async () => {
    vi.mocked(api.saveAITaskPreferences).mockRejectedValue(new api.ConnectionRequestError(0))
    setup(); await ready()
    fireEvent.change(screen.getByRole('combobox', { name: '全局默认模型' }), {
      target: { value: textModel.id },
    })
    fireEvent.click(screen.getByRole('button', { name: '保存用途偏好' }))
    await screen.findByText(/请先重新读取，不自动重发保存/)
    expect(screen.getByRole('button', { name: '保存用途偏好' })).toBeDisabled()
    expect(screen.getByRole('combobox', { name: '全局默认模型' })).toHaveValue(textModel.id)
    fireEvent.click(screen.getByRole('button', { name: '重新读取用途偏好' }))
    await waitFor(() => expect(api.listAITaskPreferences).toHaveBeenCalledTimes(2))
    await waitFor(() => expect(screen.getByRole('button', { name: '保存用途偏好' })).toBeEnabled())
    expect(api.saveAITaskPreferences).toHaveBeenCalledOnce()
  })
  it('marks a stale saved preference as unselectable and never silently chooses another model', async () => {
    current = { revision: 3, preferences: KINDS.map(kind => ({
      task_kind: kind,
      model_config_id: kind === 'default' ? '99999999-9999-4999-8999-999999999999' : null,
      selection_state: kind === 'default' ? 'needs_reselection' : 'inherit_default',
      model: kind === 'default' ? {
        id: '99999999-9999-4999-8999-999999999999',
        connection_id: connection.id, display_name: 'Revoked',
        model_id: 'removed',
      } : null,
    })) as api.AITaskPreference[] }
    setup(); await ready()
    expect(screen.getByRole('combobox', { name: '全局默认模型' })).toHaveValue('99999999-9999-4999-8999-999999999999')
    expect(screen.getByText(/必须重新选择/)).toBeInTheDocument()
    expect(api.saveAITaskPreferences).not.toHaveBeenCalled()
  })
  it('stops late account reads after unmount and rejects old viewer data', async () => {
    let finish!: (value: api.AITaskPreferences) => void
    vi.mocked(api.listAITaskPreferences).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const view = setup()
    await waitFor(() => expect(api.listAITaskPreferences).toHaveBeenCalledOnce())
    const signal = vi.mocked(api.listAITaskPreferences).mock.calls[0][0]
    view.unmount()
    await act(async () => finish(initial))
    expect(signal?.aborted).toBe(true)
    setup(8); await ready()
    expect(api.saveAITaskPreferences).not.toHaveBeenCalled()
  })
})
