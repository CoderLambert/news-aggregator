import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import SettingsPage from '@/pages/SettingsPage'
import { CapabilitiesTestProvider } from '../helpers/capabilities'

const authState = vi.hoisted(() => ({ user: { id: 7, username: 'reader-a', isSuperuser: false } as { id: number; username: string; isSuperuser: boolean } | null }))
const api = vi.hoisted(() => ({ fetchProviderCredentialStatus: vi.fn(), saveProviderCredential: vi.fn(), deleteProviderCredential: vi.fn() }))
vi.mock('@/context/AuthContext', () => ({ useAuth: () => authState }))
vi.mock('@/context/useLanguage', () => ({ useLanguage: () => ({ lang: 'zh', displayMode: 'zh', setLang: vi.fn(), setDisplayMode: vi.fn(), t: { admin: '后台管理' } }) }))
vi.mock('@/services/api', () => api)

const empty = { configured: false, requiresReplacement: false, provider: null, providerLabel: null, modelId: null, updatedAt: null }
const configured = { configured: true, requiresReplacement: false, provider: 'deepseek', providerLabel: 'DeepSeek', modelId: 'deepseek-chat', updatedAt: '2026-10-17T00:00:00Z' }
const SECRET = 'synthetic-only-private-key-never-real'
function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail })
  return { promise, resolve, reject }
}
function setup() {
  const ui = () => <MemoryRouter><CapabilitiesTestProvider><SettingsPage /></CapabilitiesTestProvider></MemoryRouter>
  const view = render(ui())
  return { ...view, switchViewer: (id: number | null) => {
    authState.user = id === null ? null : { id, username: `reader-${id}`, isSuperuser: false }
    view.rerender(ui())
  } }
}
const keyInput = () => screen.getByPlaceholderText('请输入厂商 API Key')
async function ready() { await waitFor(() => expect(screen.getByLabelText('模型提供方')).toBeEnabled()) }
function enterKey() { fireEvent.change(keyInput(), { target: { value: SECRET } }) }

beforeEach(() => {
  vi.resetAllMocks()
  authState.user = { id: 7, username: 'reader-a', isSuperuser: false }
  api.fetchProviderCredentialStatus.mockResolvedValue(empty)
})
afterEach(() => { cleanup(); vi.restoreAllMocks() })

describe('BYOK T01 credential settings recovery', () => {
  it('does not mistake an unreadable credential for an unconfigured account', async () => {
    api.fetchProviderCredentialStatus.mockRejectedValueOnce(new Error('offline'))
    setup()
    await screen.findByText('凭据状态未知，请重新读取。')
    expect(screen.queryByText('尚未配置')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '保存 Key' })).toBeDisabled()
    expect(keyInput()).toBeDisabled()
    expect(screen.getByLabelText('Model ID')).toBeDisabled()
    expect(api.fetchProviderCredentialStatus).toHaveBeenCalledTimes(1)
    expect(api.saveProviderCredential).not.toHaveBeenCalled()
    expect(api.deleteProviderCredential).not.toHaveBeenCalled()
  })

  it('recovers an initial read with one explicit GET and restores the saved provider/model', async () => {
    api.fetchProviderCredentialStatus.mockRejectedValueOnce(new Error('offline')).mockResolvedValue(configured)
    setup()
    fireEvent.click(await screen.findByRole('button', { name: '重新读取 Key 状态' }))
    await ready()
    expect(screen.getByLabelText('模型提供方')).toHaveValue('deepseek')
    expect(screen.getByLabelText('Model ID')).toHaveValue('deepseek-chat')
    expect(keyInput()).toHaveValue('')
    expect(screen.getByRole('button', { name: '删除 Key' })).toBeEnabled()
    expect(api.fetchProviderCredentialStatus).toHaveBeenCalledTimes(2)
    expect(api.saveProviderCredential).not.toHaveBeenCalled()
    expect(api.deleteProviderCredential).not.toHaveBeenCalled()
  })

  it('remains unknown after a second failed read and keeps recovery available', async () => {
    api.fetchProviderCredentialStatus.mockRejectedValue(new Error('offline'))
    setup()
    fireEvent.click(await screen.findByRole('button', { name: '重新读取 Key 状态' }))
    await screen.findByText('凭据状态未知，请重新读取。')
    expect(api.fetchProviderCredentialStatus).toHaveBeenCalledTimes(2)
    expect(screen.getByRole('button', { name: '重新读取 Key 状态' })).toBeEnabled()
    expect(keyInput()).toBeDisabled()
  })

  it('clears a submitted Key immediately and prevents duplicate form submissions', async () => {
    const delayed = deferred<typeof configured>()
    api.saveProviderCredential.mockReturnValue(delayed.promise)
    setup(); await ready(); enterKey()
    const form = keyInput().closest('form')!
    act(() => { fireEvent.submit(form); fireEvent.submit(form) })
    expect(api.saveProviderCredential).toHaveBeenCalledTimes(1)
    expect(api.saveProviderCredential).toHaveBeenCalledWith('deepseek', 'deepseek-chat', SECRET)
    expect(keyInput()).toHaveValue('')
    expect(keyInput()).toBeDisabled()
    await act(async () => { delayed.resolve(configured); await delayed.promise })
    expect(await screen.findByText('API Key 与模型已加密保存，尚未验证可用性。')).toBeInTheDocument()
  })

  it('reconciles an unknown save result by GET without resending the Key', async () => {
    api.saveProviderCredential.mockRejectedValue(new Error('response lost'))
    api.fetchProviderCredentialStatus.mockResolvedValueOnce(empty).mockResolvedValue(configured)
    setup(); await ready(); enterKey()
    fireEvent.click(screen.getByRole('button', { name: '保存 Key' }))
    await screen.findByText('凭据状态未知，请重新读取。')
    expect(keyInput()).toHaveValue('')
    expect(screen.getByRole('button', { name: '保存 Key' })).toBeDisabled()
    expect(api.fetchProviderCredentialStatus).toHaveBeenCalledTimes(1)
    fireEvent.click(screen.getByRole('button', { name: '重新读取 Key 状态' }))
    await ready()
    expect(screen.getByText('已配置：DeepSeek / deepseek-chat')).toBeInTheDocument()
    expect(api.saveProviderCredential).toHaveBeenCalledTimes(1)
    expect(api.fetchProviderCredentialStatus).toHaveBeenCalledTimes(2)
    expect(screen.getByRole('button', { name: '替换 Key' })).toBeDisabled()
  })

  it('clears a drafted Key when switching provider, before a different provider can receive it', async () => {
    setup(); await ready(); enterKey()
    fireEvent.change(screen.getByLabelText('模型提供方'), { target: { value: 'anthropic' } })
    expect(keyInput()).toHaveValue('')
    expect(screen.getByRole('button', { name: '保存 Key' })).toBeDisabled()
    fireEvent.submit(keyInput().closest('form')!)
    expect(api.saveProviderCredential).not.toHaveBeenCalled()
  })

  it.each([
    { label: 'transport exception', error: new Error(SECRET) },
    { label: 'proxy body', error: { isAxiosError: true, response: { status: 503, data: { error: `<pre>${SECRET}</pre>` } }, message: SECRET } },
    { label: 'validation body', error: { isAxiosError: true, response: { status: 400, data: { error: SECRET } } } },
  ])('never renders secrets from a $label', async ({ error }) => {
    api.saveProviderCredential.mockRejectedValue(error)
    setup(); await ready(); enterKey()
    fireEvent.click(screen.getByRole('button', { name: '保存 Key' }))
    await screen.findByRole('alert')
    expect(document.body.textContent).not.toContain(SECRET)
    expect(document.body.innerHTML).not.toContain(SECRET)
    expect(keyInput()).toHaveValue('')
    expect(api.saveProviderCredential).toHaveBeenCalledTimes(1)
  })

  it('requires GET reconciliation after a lost delete result and never retries DELETE automatically', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    api.fetchProviderCredentialStatus.mockResolvedValueOnce(configured).mockResolvedValue(empty)
    api.deleteProviderCredential.mockRejectedValue(new Error('response lost'))
    setup(); await ready(); enterKey()
    fireEvent.click(screen.getByRole('button', { name: '删除 Key' }))
    await screen.findByText('凭据状态未知，请重新读取。')
    expect(keyInput()).toHaveValue('')
    expect(screen.queryByRole('button', { name: '删除 Key' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '重新读取 Key 状态' }))
    await screen.findByText('尚未配置')
    expect(api.deleteProviderCredential).toHaveBeenCalledTimes(1)
    expect(api.fetchProviderCredentialStatus).toHaveBeenCalledTimes(2)
  })

  it('does not delete when the user cancels the confirmation', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    api.fetchProviderCredentialStatus.mockResolvedValue(configured)
    setup(); await ready()
    fireEvent.click(screen.getByRole('button', { name: '删除 Key' }))
    expect(api.deleteProviderCredential).not.toHaveBeenCalled()
    expect(screen.getByText('已配置：DeepSeek / deepseek-chat')).toBeInTheDocument()
  })

  it('aborts old status reads and excludes late results after switching accounts', async () => {
    const delayed = deferred<typeof configured>()
    api.fetchProviderCredentialStatus.mockReturnValueOnce(delayed.promise).mockResolvedValue(empty)
    const view = setup()
    await waitFor(() => expect(api.fetchProviderCredentialStatus).toHaveBeenCalledTimes(1))
    const signal = api.fetchProviderCredentialStatus.mock.calls[0][0] as AbortSignal
    view.switchViewer(8)
    await ready()
    expect(signal.aborted).toBe(true)
    await act(async () => { delayed.resolve(configured); await delayed.promise })
    expect(screen.getByText('尚未配置')).toBeInTheDocument()
    expect(screen.queryByText('已配置：DeepSeek / deepseek-chat')).not.toBeInTheDocument()
  })

  it('does not display the previous account save result or drafted Key in a new account', async () => {
    const delayed = deferred<typeof configured>()
    api.saveProviderCredential.mockReturnValueOnce(delayed.promise)
    const view = setup(); await ready(); enterKey()
    fireEvent.click(screen.getByRole('button', { name: '保存 Key' }))
    view.switchViewer(8); await ready()
    await act(async () => { delayed.resolve(configured); await delayed.promise })
    expect(screen.getByText('尚未配置')).toBeInTheDocument()
    expect(keyInput()).toHaveValue('')
    expect(screen.queryByText('API Key 与模型已加密保存，尚未验证可用性。')).not.toBeInTheDocument()
    expect(api.saveProviderCredential).toHaveBeenCalledTimes(1)
  })

  it('does not persist a Key in browser storage and discards drafts on logout', async () => {
    const writes = vi.spyOn(Storage.prototype, 'setItem')
    const view = setup(); await ready(); enterKey()
    view.switchViewer(null)
    expect(screen.queryByPlaceholderText('请输入厂商 API Key')).not.toBeInTheDocument()
    expect(writes.mock.calls.some(([, value]) => value.includes(SECRET))).toBe(false)
    expect(api.saveProviderCredential).not.toHaveBeenCalled()
  })
})
