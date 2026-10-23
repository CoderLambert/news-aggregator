import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import '@tests/helpers/commandDom'
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
  config_revision: 1, has_trusted_route: true, article_chat_supported: true, context_window_tokens: null,
  capabilities: { text: 'supported', tools: 'unknown' },
  updated_at: '2026-10-18T00:00:00Z',
}
const toolsModel: api.AIModel = {
  ...textModel, id: '33333333-3333-4333-8333-333333333333',
  display_name: 'Text + tools',
  capabilities: { text: 'supported', tools: 'supported' },
}
const disconnected: api.ChatGPTTaskOption = {
  state: 'not_connected', model_id: null, display_name: null, research_eligible: false,
}
const initial: api.AITaskPreferences = {
  revision: 0, preferences: KINDS.map(kind => ({
    task_kind: kind,
    selection_source: kind === 'default' ? 'unset' : 'inherit',
    model_config_id: null,
    selection_state: kind === 'default' ? 'unset' : 'inherit_default', model: null,
  })),
  subscription: disconnected,
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
    current = {
      revision: revision + 1,
      preferences: selections.map(item => ({
        ...item,
        selection_state: item.selection_source === 'byok' || item.selection_source === 'chatgpt_subscription'
          ? 'available' : item.task_kind === 'default' ? 'unset' : 'inherit_default',
        model: null,
      })) as api.AITaskPreference[],
      subscription: current.subscription,
    }
    return current
  })
})
afterEach(cleanup)
function setup(viewer = 7) {
  return render(<MemoryRouter><AITaskPreferencesSection key={viewer} viewer={viewer} connections={[connection]} /></MemoryRouter>)
}
async function ready() {
  await screen.findByRole('combobox', { name: '全局默认模型' })
  fireEvent.click(screen.getByText('按用途单独配置'))
}
function choices(label: string) {
  fireEvent.click(screen.getByRole('combobox', { name: label }))
  const names = screen.queryAllByRole('option').map(option => option.textContent)
  fireEvent.keyDown(screen.getByLabelText('搜索模型'), { key: 'Escape' })
  return names.join(' ')
}
function choose(label: string, name: string) {
  fireEvent.click(screen.getByRole('combobox', { name: label }))
  fireEvent.click(screen.getByRole('option', { name: new RegExp(name.replace(/[+]/g, '\\+')) }))
}
describe('T03 model purpose settings', () => {
  it('filters model choices by name and provider model ID without fetching or saving', async () => {
    setup(); await ready()
    fireEvent.click(screen.getByRole('combobox', { name: '全局默认模型' }))
    const input = screen.getByLabelText('搜索模型')
    fireEvent.change(input, { target: { value: 'Text only' } })
    expect(screen.getAllByRole('option')).toHaveLength(1)
    fireEvent.change(input, { target: { value: 'deepseek-chat' } })
    expect(screen.getAllByRole('option')).toHaveLength(2)
    fireEvent.change(input, { target: { value: 'no-such-model' } })
    expect(screen.queryAllByRole('option')).toHaveLength(0)
    expect(screen.getByText('没有匹配的可选模型。')).toBeInTheDocument()
    fireEvent.change(input, { target: { value: '' } })
    expect(screen.getAllByRole('option')).toHaveLength(3)
    expect(api.listAIModels).toHaveBeenCalledOnce()
    expect(api.saveAITaskPreferences).not.toHaveBeenCalled()
    expect(api.probeAIModel).not.toHaveBeenCalled()
  })
  it('allows an approved no-Key model while keeping unverified tools out of research', async () => {
    render(<MemoryRouter><AITaskPreferencesSection viewer={7} connections={[{ ...connection, auth_mode: 'none', key_saved: false }]} /></MemoryRouter>)
    await ready()
    expect(choices('新闻问答模型')).toContain('Text only')
    expect(choices('深度研究模型')).not.toContain('Text only')
    expect(api.saveAITaskPreferences).not.toHaveBeenCalled()
  })
  it('offers an authorized subscription only for explicit supported purposes', async () => {
    current = {
      ...initial,
      subscription: {
        state: 'available', model_id: 'gpt-subscription',
        display_name: 'GPT Subscription', research_eligible: false,
      },
    }
    setup(); await ready()
    expect(choices('全局默认模型')).not.toContain('ChatGPT 订阅')
    expect(choices('新闻问答模型')).toContain('ChatGPT 订阅 · GPT Subscription')
    choose('新闻问答模型', 'ChatGPT 订阅')
    fireEvent.click(screen.getByRole('button', { name: '保存用途偏好' }))
    await waitFor(() => expect(api.saveAITaskPreferences).toHaveBeenCalledOnce())
    const rows = vi.mocked(api.saveAITaskPreferences).mock.calls[0][1]
    expect(rows.find(row => row.task_kind === 'article_qa')).toEqual({
      task_kind: 'article_qa',
      selection_source: 'chatgpt_subscription',
      model_config_id: null,
    })
  })
  it('keeps nonstream models available for research but excludes them from chat and translation', async () => {
    available = [textModel, { ...toolsModel, article_chat_supported: false }]
    setup(); await ready()
    for (const label of ['新闻问答模型', '全文翻译模型']) {
      const names = choices(label)
      expect(names).not.toContain('Text + tools')
      expect(names).toContain('Text only')
    }
    expect(choices('深度研究模型')).toContain('Text + tools')
    expect(choices('问题推荐模型')).toContain('Text + tools')
    expect(api.saveAITaskPreferences).not.toHaveBeenCalled()
    expect(api.probeAIModel).not.toHaveBeenCalled()
  })
  it('loads metadata read-only and only submits after an explicit save of all five kinds', async () => {
    setup()
    await ready()
    expect(api.listAITaskPreferences).toHaveBeenCalledOnce()
    expect(api.listAIModels).toHaveBeenCalledOnce()
    expect(api.saveAITaskPreferences).not.toHaveBeenCalled()
    expect(api.probeAIModel).not.toHaveBeenCalled()
    choose('全局默认模型', 'Text only')
    expect(screen.getByText('存在未保存的用途变更。')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '保存用途偏好' }))
    await waitFor(() => expect(api.saveAITaskPreferences).toHaveBeenCalledOnce())
    const [revision, rows, viewer, signal] = vi.mocked(api.saveAITaskPreferences).mock.calls[0]
    expect(revision).toBe(0)
    expect(rows).toHaveLength(5)
    expect(rows[0]).toEqual({ task_kind: 'default', selection_source: 'byok', model_config_id: textModel.id })
    expect(rows.slice(1).every(row =>
      row.selection_source === 'inherit' && row.model_config_id === null)).toBe(true)
    expect(viewer).toBe(7)
    expect(signal).toBeInstanceOf(AbortSignal)
    expect(api.probeAIModel).not.toHaveBeenCalled()
    await screen.findByText(/用途偏好已保存/)
  })
  it('can undo a draft without a write and disables unverified deep research choices', async () => {
    setup(); await ready()
    expect(choices('深度研究模型')).not.toContain('Text only')
    expect(choices('深度研究模型')).toContain('Text + tools')
    choose('新闻问答模型', 'Text only')
    fireEvent.click(screen.getByRole('button', { name: '撤销修改' }))
    expect(screen.getByRole('combobox', { name: '新闻问答模型' })).toHaveTextContent('跟随个人默认模型')
    expect(api.saveAITaskPreferences).not.toHaveBeenCalled()
  })
  it('keeps unsaved draft but freezes resubmission after an uncertain PATCH, until GET reconciliation', async () => {
    vi.mocked(api.saveAITaskPreferences).mockRejectedValue(new api.ConnectionRequestError(0))
    setup(); await ready()
    choose('全局默认模型', 'Text only')
    fireEvent.click(screen.getByRole('button', { name: '保存用途偏好' }))
    await screen.findByText(/请先重新读取，不自动重发保存/)
    expect(screen.getByRole('button', { name: '保存用途偏好' })).toBeDisabled()
    expect(screen.getByRole('combobox', { name: '全局默认模型' })).toHaveTextContent('Text only')
    fireEvent.click(screen.getByRole('button', { name: '重新读取用途偏好' }))
    await waitFor(() => expect(api.listAITaskPreferences).toHaveBeenCalledTimes(2))
    await waitFor(() => expect(screen.getByRole('button', { name: '保存用途偏好' })).toBeEnabled())
    expect(api.saveAITaskPreferences).toHaveBeenCalledOnce()
  })
  it('marks a stale saved preference as unselectable and never silently chooses another model', async () => {
    current = { revision: 3, preferences: KINDS.map(kind => ({
      task_kind: kind,
      selection_source: kind === 'default' ? 'byok' : 'inherit',
      model_config_id: kind === 'default' ? '99999999-9999-4999-8999-999999999999' : null,
      selection_state: kind === 'default' ? 'needs_reselection' : 'inherit_default',
      model: kind === 'default' ? {
        id: '99999999-9999-4999-8999-999999999999',
        connection_id: connection.id, display_name: 'Revoked',
        model_id: 'removed',
      } : null,
    })) as api.AITaskPreference[], subscription: disconnected }
    setup(); await ready()
    expect(screen.getByRole('combobox', { name: '全局默认模型' })).toHaveTextContent('原模型已失效')
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
