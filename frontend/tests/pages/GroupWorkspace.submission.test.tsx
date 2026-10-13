import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider, useMutation } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import GroupWorkspace from '@/pages/GroupWorkspace'
import { createChannelGroup, deleteChannelGroup } from '@/services/api'

vi.mock('@/context/AuthContext', () => ({ useAuth: () => ({ user: { id: 1 }, loading: false }) }))
vi.mock('@/services/api', () => ({ createChannelGroup: vi.fn(), updateChannelGroup: vi.fn(), deleteChannelGroup: vi.fn() }))
vi.mock('@/services/channelQueries', () => ({
  useChannelConfig: () => ({ enabled: true, ready: true, error: false, groups: { data: [{ id: 1, name: 'Existing', source_ids: [] }] }, subscriptions: { data: [] } }),
  useChannelMutation: () => useMutation({ mutationFn: (perform: () => Promise<unknown>) => perform() }),
}))
vi.mock('@/services/workspaceApi', () => ({ workspaceCatalogOptions: () => ({ queryKey: ['test-catalog'], queryFn: async () => ({ sources: [], topics: [] }) }) }))
const show = Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, 'showModal')
const close = Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, 'close')
beforeEach(() => {
  vi.clearAllMocks()
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', { configurable: true, value: function (this: HTMLDialogElement) { this.setAttribute('open', '') } })
  Object.defineProperty(HTMLDialogElement.prototype, 'close', { configurable: true, value: function (this: HTMLDialogElement) { this.removeAttribute('open') } })
})
afterEach(() => {
  cleanup()
  if (show) Object.defineProperty(HTMLDialogElement.prototype, 'showModal', show)
  else Reflect.deleteProperty(HTMLDialogElement.prototype, 'showModal')
  if (close) Object.defineProperty(HTMLDialogElement.prototype, 'close', close)
  else Reflect.deleteProperty(HTMLDialogElement.prototype, 'close')
})
function deferred() {
  let resolve!: (value: unknown) => void
  let reject!: (error: Error) => void
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
function setup() {
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}><MemoryRouter><GroupWorkspace /></MemoryRouter></QueryClientProvider>)
  const trigger = screen.getByRole('button', { name: '新建分组' })
  trigger.focus(); fireEvent.click(trigger)
  fireEvent.change(screen.getByRole('textbox', { name: '分组名称' }), { target: { value: 'Guarded group' } })
  return screen.getByRole('dialog', { name: '新建分组' })
}

it('blocks Escape, close, cancel and repeated submission before pending state renders', async () => {
  const request = deferred()
  vi.mocked(createChannelGroup).mockReturnValue(request.promise as ReturnType<typeof createChannelGroup>)
  const dialog = setup()
  const form = dialog.querySelector('form')!
  const closeButton = screen.getByRole('button', { name: '关闭新建分组' })
  const cancelButton = screen.getByRole('button', { name: '取消' })
  act(() => {
    fireEvent.submit(form)
    fireEvent(dialog, new Event('cancel', { cancelable: true }))
    fireEvent.click(closeButton)
    fireEvent.click(cancelButton)
    fireEvent.submit(form)
  })
  expect(screen.getByRole('dialog', { name: '新建分组' })).toBeInTheDocument()
  await waitFor(() => expect(createChannelGroup).toHaveBeenCalledTimes(1))
  expect(screen.getByRole('button', { name: '关闭新建分组' })).toBeDisabled()
  await act(async () => request.resolve({ id: 2, name: 'Guarded group', source_ids: [] }))
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
})

it('keeps a failed form and its input, releases the guard, and permits retry', async () => {
  const first = deferred(); const retry = deferred()
  vi.mocked(createChannelGroup).mockReturnValueOnce(first.promise as ReturnType<typeof createChannelGroup>).mockReturnValueOnce(retry.promise as ReturnType<typeof createChannelGroup>)
  const dialog = setup()
  fireEvent.submit(dialog.querySelector('form')!)
  await waitFor(() => expect(createChannelGroup).toHaveBeenCalledTimes(1))
  await act(async () => first.reject(new Error('local controlled failure')))
  expect(await within(dialog).findByRole('alert')).toHaveTextContent('未确认成功')
  expect(within(dialog).getByRole('alert')).toHaveTextContent('请先刷新分组确认')
  expect(screen.getByRole('button', { name: '关闭编辑' })).toBeEnabled()
  expect(screen.getByRole('textbox', { name: '分组名称' })).toHaveValue('Guarded group')
  fireEvent.click(screen.getByRole('button', { name: '保存' }))
  await waitFor(() => expect(createChannelGroup).toHaveBeenCalledTimes(2))
  await act(async () => retry.resolve({ id: 2, name: 'Guarded group', source_ids: [] }))
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
})

it('allows normal Escape dismissal before submission without making a request', () => {
  const dialog = setup()
  fireEvent(dialog, new Event('cancel', { cancelable: true }))
  expect(screen.queryByRole('dialog')).toBeNull()
  // The native dialog's focus restoration is checked in the real browser;
  // this jsdom fixture deliberately models only its open/close state.
  expect(createChannelGroup).not.toHaveBeenCalled()
})

it('also fences a deletion confirmation and sends only one request', async () => {
  const request = deferred()
  vi.mocked(deleteChannelGroup).mockReturnValue(request.promise as ReturnType<typeof deleteChannelGroup>)
  setup()
  fireEvent.click(screen.getByRole('button', { name: '关闭新建分组' }))
  fireEvent.click(screen.getByRole('button', { name: '删除分组' }))
  const dialog = screen.getByRole('dialog', { name: '删除分组' })
  const confirm = screen.getByRole('button', { name: '确认删除' })
  act(() => {
    fireEvent.click(confirm)
    fireEvent(dialog, new Event('cancel', { cancelable: true }))
    fireEvent.click(screen.getByRole('button', { name: '关闭删除分组' }))
    fireEvent.click(confirm)
  })
  expect(dialog).toBeInTheDocument()
  await waitFor(() => expect(deleteChannelGroup).toHaveBeenCalledTimes(1))
  expect(screen.getByRole('button', { name: '关闭删除分组' })).toBeDisabled()
  await act(async () => request.resolve(undefined))
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
})
