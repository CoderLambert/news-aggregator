import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AIConnectionsManager } from '@/pages/AIModelSettingsPage'
import * as api from '@/services/aiConnectionsApi'

vi.mock('@/services/aiConnectionsApi', async importOriginal => ({
  ...await importOriginal<typeof import('@/services/aiConnectionsApi')>(),
  listAIProviders: vi.fn(), listAIConnections: vi.fn(), createAIConnection: vi.fn(),
  patchAIConnection: vi.fn(), replaceAIConnectionKey: vi.fn(), deleteAIConnection: vi.fn(),
  listAIModels: vi.fn(), listAIModelCatalog: vi.fn(),
}))
const profile = { provider_id: 'deepseek', provider_name: 'DeepSeek', profile_id: 'deepseek_default', region_name: '默认路由', version: 1 }
const profiles = [profile, { ...profile, provider_id: 'qwen', provider_name: 'Qwen', profile_id: 'qwen_default' }]
const row: api.AIConnection = {
  id: 'b92da999-b652-4c37-953d-969b3a8eac91', provider_id: 'deepseek', provider_name: 'DeepSeek', endpoint_profile: 'deepseek_default',
  endpoint_profile_version: 1, display_name: '我的连接', region_name: '默认路由', key_saved: true, masked_key: '••••••••',
  is_enabled: true, revision: 1, credential_epoch: 1, verification_status: 'not_tested', updated_at: '2026-10-17T00:00:00Z',
}
const KEY = 'synthetic-key-never-use-real-12345'
const showModal = Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, 'showModal')
const close = Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, 'close')
let rows: api.AIConnection[]
beforeEach(() => {
  vi.clearAllMocks()
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', { configurable: true, value: function (this: HTMLDialogElement) { this.setAttribute('open', '') } })
  Object.defineProperty(HTMLDialogElement.prototype, 'close', { configurable: true, value: function (this: HTMLDialogElement) { this.removeAttribute('open') } })
  rows = []
  vi.mocked(api.listAIModels).mockReset().mockResolvedValue([])
  vi.mocked(api.listAIModelCatalog).mockReset().mockResolvedValue({ catalog_version: 'synthetic', models: [] })
  vi.mocked(api.listAIProviders).mockReset().mockResolvedValue(profiles)
  vi.mocked(api.listAIConnections).mockReset().mockImplementation(async () => rows)
  vi.mocked(api.createAIConnection).mockReset().mockImplementation(async body => {
    const created = { ...row, display_name: body.display_name }
    rows = [...rows, created]; return created
  })
  vi.mocked(api.patchAIConnection).mockReset().mockImplementation(async (old, values) => {
    const updated = { ...old, ...values, revision: old.revision + 1 }
    rows = rows.map(value => value.id === old.id ? updated : value); return updated
  })
  vi.mocked(api.replaceAIConnectionKey).mockReset().mockImplementation(async old => ({ ...old, revision: old.revision + 1 }))
  vi.mocked(api.deleteAIConnection).mockReset().mockImplementation(async old => { rows = rows.filter(value => value.id !== old.id); return { deleted: true } })
})
afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  if (showModal) Object.defineProperty(HTMLDialogElement.prototype, 'showModal', showModal)
  else Reflect.deleteProperty(HTMLDialogElement.prototype, 'showModal')
  if (close) Object.defineProperty(HTMLDialogElement.prototype, 'close', close)
  else Reflect.deleteProperty(HTMLDialogElement.prototype, 'close')
})
function setup(viewer = 1) { return render(<MemoryRouter><AIConnectionsManager key={viewer} viewer={viewer} /></MemoryRouter>) }
async function ready() { await waitFor(() => expect(screen.getByRole('button', { name: '新增连接' })).toBeEnabled()) }
async function openCreate() {
  await ready()
  fireEvent.click(screen.getByRole('button', { name: '新增连接' }))
  fireEvent.change(screen.getByLabelText('连接名称'), { target: { value: '测试连接' } })
  fireEvent.change(screen.getByLabelText('API Key'), { target: { value: KEY } })
}
async function submitCreate() { await openCreate(); fireEvent.click(screen.getByRole('button', { name: '保存连接' })) }

describe('BYOK T01 connection settings', () => {
  it('lists multiple masked connections without any mutation', async () => {
    rows = [row, { ...row, id: 'other', display_name: '备用连接' }]
    setup(); await ready()
    expect(screen.getByRole('region', { name: '我的连接' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: '备用连接' })).toBeInTheDocument()
    expect(api.createAIConnection).not.toHaveBeenCalled()
    expect(api.patchAIConnection).not.toHaveBeenCalled()
    expect(screen.queryByText(KEY)).toBeNull()
  })
  it('shows the single personal Key manager and no retired settings entry', async () => {
    setup(); await ready()
    expect(screen.getByRole('heading', { name: '个人 AI 连接' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: '查看现有单 Key 设置' })).not.toBeInTheDocument()
    expect(screen.getByText(/尚无个人 AI 连接/)).toBeInTheDocument()
  })
  it('creates only after explicit submit with viewer and a stable request id', async () => {
    setup(); await openCreate()
    expect(api.createAIConnection).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: '保存连接' }))
    await screen.findByRole('region', { name: '测试连接' })
    expect(api.createAIConnection).toHaveBeenCalledWith(expect.objectContaining({ api_key: KEY, display_name: '测试连接',
      provider_id: 'deepseek', endpoint_profile: 'deepseek_default', request_id: expect.stringMatching(/^[a-f0-9-]{36}$/) }), 1, expect.any(AbortSignal))
    expect(screen.queryByLabelText('API Key')).toBeNull()
  })
  it('clears submitted Key immediately and refuses a duplicate submission', async () => {
    let finish!: (value: api.AIConnection) => void
    vi.mocked(api.createAIConnection).mockImplementation(() => new Promise(resolve => { finish = resolve }))
    setup(); await openCreate()
    const button = screen.getByRole('button', { name: '保存连接' })
    act(() => { fireEvent.click(button); fireEvent.click(button) })
    expect(screen.getByLabelText('API Key')).toHaveValue('')
    expect(api.createAIConnection).toHaveBeenCalledOnce()
    await act(async () => finish(row))
  })
  it('clears a draft when switching providers', async () => {
    setup(); await openCreate()
    fireEvent.change(screen.getByLabelText('服务商与受信端点'), { target: { value: 'qwen_default' } })
    expect(screen.getByLabelText('API Key')).toHaveValue('')
    expect(api.createAIConnection).not.toHaveBeenCalled()
  })
  it('changes an alias without submitting a Key', async () => {
    rows = [row]; setup(); await ready()
    fireEvent.click(screen.getByRole('button', { name: '修改名称' }))
    expect(screen.queryByLabelText('API Key')).toBeNull()
    fireEvent.change(screen.getByLabelText('连接名称'), { target: { value: '重命名连接' } })
    fireEvent.click(screen.getByRole('button', { name: '保存连接' }))
    await screen.findByRole('region', { name: '重命名连接' })
    expect(api.patchAIConnection).toHaveBeenCalledWith(row, { display_name: '重命名连接' }, 1, expect.any(AbortSignal))
  })
  it('disables and enables the selected connection only', async () => {
    rows = [row]; setup(); await ready()
    fireEvent.click(screen.getByRole('button', { name: '停用' }))
    await waitFor(() => expect(screen.getByRole('button', { name: '启用' })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: '启用' }))
    await screen.findByRole('button', { name: '停用' })
    expect(api.patchAIConnection).toHaveBeenCalledTimes(2)
    expect(vi.mocked(api.patchAIConnection).mock.calls.map(([, values]) => values)).toEqual([{ is_enabled: false }, { is_enabled: true }])
  })
  it('replaces a Key without creating a new connection', async () => {
    rows = [row]; setup(); await ready()
    fireEvent.click(screen.getByRole('button', { name: '替换 Key' }))
    fireEvent.change(screen.getByLabelText('API Key'), { target: { value: KEY } })
    fireEvent.click(screen.getByRole('button', { name: '保存连接' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(api.replaceAIConnectionKey).toHaveBeenCalledWith(row, KEY, 1, expect.any(AbortSignal))
    expect(api.createAIConnection).not.toHaveBeenCalled()
  })
  it('requires confirmation before deletion and supports cancelling it', async () => {
    rows = [row]; setup(); await ready()
    const trigger = screen.getByRole('button', { name: '删除连接' }); trigger.focus(); fireEvent.click(trigger)
    expect(api.deleteAIConnection).not.toHaveBeenCalled()
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: '取消' }))
    expect(trigger).toHaveFocus()
    expect(api.deleteAIConnection).not.toHaveBeenCalled()
    fireEvent.click(trigger)
    fireEvent.click(screen.getByRole('button', { name: '确认删除' }))
    await waitFor(() => expect(screen.queryByRole('region', { name: '我的连接' })).toBeNull())
    expect(api.deleteAIConnection).toHaveBeenCalledOnce()
  })
  it('uses GET reconciliation after a lost save response, never resending the Key', async () => {
    vi.mocked(api.createAIConnection).mockImplementation(async () => { rows = [row]; throw new api.ConnectionRequestError(0) })
    setup(); await submitCreate()
    await screen.findByText(/连接状态未知/)
    expect(screen.getByRole('button', { name: '新增连接' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: '重新读取连接' }))
    await screen.findByRole('region', { name: '我的连接' })
    expect(api.createAIConnection).toHaveBeenCalledOnce()
  })
  it('keeps unreadable initial state unknown rather than reporting an empty account', async () => {
    vi.mocked(api.listAIConnections).mockRejectedValueOnce(new api.ConnectionRequestError(0))
    setup()
    await screen.findByText(/连接状态未知/)
    expect(screen.queryByText(/尚无新式连接/)).toBeNull()
    expect(screen.getByRole('button', { name: '新增连接' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: '重新读取连接' }))
    await ready()
  })
  it('does not display potentially sensitive exception text or persist a Key', async () => {
    vi.mocked(api.createAIConnection).mockRejectedValue(new Error(KEY))
    const storage = vi.spyOn(Storage.prototype, 'setItem')
    setup(); await submitCreate()
    await screen.findByText(/连接状态未知/)
    expect(document.body.textContent).not.toContain(KEY)
    expect(storage.mock.calls.flat().some(value => String(value).includes(KEY))).toBe(false)
    storage.mockRestore()
  })
  it('ignores a late old-account write and aborts its client request', async () => {
    let finish!: (value: api.AIConnection) => void
    vi.mocked(api.createAIConnection).mockImplementation(() => new Promise(resolve => { finish = resolve }))
    const view = setup(); await submitCreate()
    const signal = vi.mocked(api.createAIConnection).mock.calls[0][2]
    view.unmount()
    const reads = vi.mocked(api.listAIConnections).mock.calls.length
    await act(async () => finish(row))
    expect(signal?.aborted).toBe(true)
    expect(api.listAIConnections).toHaveBeenCalledTimes(reads)
    setup(2); await ready()
    expect(screen.queryByText('测试连接')).toBeNull()
  })
  it('shows a disabled-management error without exposing edit controls', async () => {
    vi.mocked(api.listAIProviders).mockRejectedValue(new api.ConnectionRequestError(403))
    setup()
    await screen.findByText(/连接管理未启用/)
    expect(screen.getByRole('button', { name: '新增连接' })).toBeDisabled()
    expect(api.createAIConnection).not.toHaveBeenCalled()
  })
})
