import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider, useMutation } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import GroupWorkspace from '@/pages/GroupWorkspace'
import { createChannelGroup, createChannelGroupRoot, deleteChannelGroup, deleteChannelGroupRoot, updateChannelGroup, updateChannelGroupRoot } from '@/services/api'

vi.mock('@/context/AuthContext', () => ({ useAuth: () => ({ user: { id: 1 }, loading: false }) }))
const hierarchy = vi.hoisted(() => ({ roots: [] as unknown[], groups: [] as unknown[] }))
vi.mock('@/services/api', () => ({ createChannelGroup: vi.fn(), createChannelGroupRoot: vi.fn(), updateChannelGroup: vi.fn(), updateChannelGroupRoot: vi.fn(), deleteChannelGroup: vi.fn(), deleteChannelGroupRoot: vi.fn() }))
vi.mock('@/services/channelQueries', () => ({
  useChannelConfig: () => ({ enabled: true, ready: true, error: false, roots: { data: hierarchy.roots }, groups: { data: hierarchy.groups }, subscriptions: { data: [] } }),
  useChannelMutation: () => useMutation({ mutationFn: (perform: () => Promise<unknown>) => perform() }),
}))
vi.mock('@/services/workspaceApi', () => ({ workspaceCatalogOptions: () => ({ queryKey: ['test-catalog'], queryFn: async () => ({ sources: [], topics: [] }) }) }))
const show = Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, 'showModal')
const close = Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, 'close')
beforeEach(() => {
  vi.clearAllMocks()
  hierarchy.roots = [{ id: 9, name: 'Personal', version: 1, child_count: 1, created_at: '2026-01-01', updated_at: '2026-01-01' }]
  hierarchy.groups = [{ id: 1, root_id: 9, name: 'Existing', source_ids: [], version: 1, created_at: '2026-01-01', updated_at: '2026-01-01' }]
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
function renderWorkspace(path = '/channels/groups') {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}><MemoryRouter initialEntries={[path]}><GroupWorkspace /></MemoryRouter></QueryClientProvider>)
}
function setup() {
  renderWorkspace()
  const trigger = screen.getByRole('button', { name: '新建子分组' })
  trigger.focus(); fireEvent.click(trigger)
  fireEvent.change(screen.getByRole('textbox', { name: '子分组名称' }), { target: { value: 'Guarded group' } })
  return screen.getByRole('dialog', { name: '新建子分组' })
}

it('blocks Escape, close, cancel and repeated submission before pending state renders', async () => {
  const request = deferred()
  vi.mocked(createChannelGroup).mockReturnValue(request.promise as ReturnType<typeof createChannelGroup>)
  const dialog = setup()
  const form = dialog.querySelector('form')!
  const closeButton = screen.getByRole('button', { name: '关闭新建子分组' })
  const cancelButton = screen.getByRole('button', { name: '取消' })
  act(() => {
    fireEvent.submit(form)
    fireEvent(dialog, new Event('cancel', { cancelable: true }))
    fireEvent.click(closeButton)
    fireEvent.click(cancelButton)
    fireEvent.submit(form)
  })
  expect(screen.getByRole('dialog', { name: '新建子分组' })).toBeInTheDocument()
  await waitFor(() => expect(createChannelGroup).toHaveBeenCalledTimes(1))
  expect(screen.getByRole('button', { name: '关闭新建子分组' })).toBeDisabled()
  await act(async () => request.resolve({ id: 2, root_id: 9, name: 'Guarded group', source_ids: [], version: 1, created_at: '2026-01-01', updated_at: '2026-01-01' }))
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
  expect(within(dialog).getByRole('alert')).toHaveTextContent('请先刷新层级确认')
  expect(screen.getByRole('button', { name: '关闭编辑' })).toBeEnabled()
  expect(screen.getByRole('textbox', { name: '子分组名称' })).toHaveValue('Guarded group')
  fireEvent.click(screen.getByRole('button', { name: '保存' }))
  await waitFor(() => expect(createChannelGroup).toHaveBeenCalledTimes(2))
  await act(async () => retry.resolve({ id: 2, root_id: 9, name: 'Guarded group', source_ids: [], version: 1, created_at: '2026-01-01', updated_at: '2026-01-01' }))
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
  fireEvent.click(screen.getByRole('button', { name: '关闭新建子分组' }))
  fireEvent.click(screen.getByRole('button', { name: 'Existing0' }))
  fireEvent.click(screen.getByRole('button', { name: '删除子分组' }))
  const dialog = screen.getByRole('dialog', { name: '删除子分组' })
  const confirm = screen.getByRole('button', { name: '确认删除' })
  act(() => {
    fireEvent.click(confirm)
    fireEvent(dialog, new Event('cancel', { cancelable: true }))
    fireEvent.click(screen.getByRole('button', { name: '关闭删除子分组' }))
    fireEvent.click(confirm)
  })
  expect(dialog).toBeInTheDocument()
  await waitFor(() => expect(deleteChannelGroup).toHaveBeenCalledTimes(1))
  expect(screen.getByRole('button', { name: '关闭删除子分组' })).toBeDisabled()
  await act(async () => request.resolve(undefined))
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
})

it('creates, renames, and deletes an empty root with version fences', async () => {
  hierarchy.roots = [{ id: 9, name: 'Empty', version: 4, child_count: 0, created_at: '2026-01-01', updated_at: '2026-01-01' }]
  hierarchy.groups = []
  vi.mocked(createChannelGroupRoot).mockResolvedValue({ id: 10, name: 'Research' })
  vi.mocked(updateChannelGroupRoot).mockResolvedValue({ id: 9, name: 'Renamed' })
  vi.mocked(deleteChannelGroupRoot).mockResolvedValue(undefined)
  renderWorkspace()
  fireEvent.click(screen.getByRole('button', { name: '新建根分类' }))
  fireEvent.change(screen.getByRole('textbox', { name: '根分类名称' }), { target: { value: 'Research' } })
  fireEvent.click(screen.getByRole('button', { name: '保存' }))
  await waitFor(() => expect(createChannelGroupRoot).toHaveBeenCalledWith('Research'))

  fireEvent.click(screen.getByRole('button', { name: '重命名根分类' }))
  fireEvent.change(screen.getByRole('textbox', { name: '根分类名称' }), { target: { value: 'Renamed' } })
  fireEvent.click(screen.getByRole('button', { name: '保存' }))
  await waitFor(() => expect(updateChannelGroupRoot).toHaveBeenCalledWith(9, { name: 'Renamed', expected_version: 4 }))

  fireEvent.click(screen.getByRole('button', { name: '删除空根分类' }))
  fireEvent.click(screen.getByRole('button', { name: '确认删除' }))
  await waitFor(() => expect(deleteChannelGroupRoot).toHaveBeenCalledWith(9, 4))
})

it('restores a child deep link and reparents with the child structural version', async () => {
  hierarchy.roots = [
    { id: 9, name: 'Personal', version: 1, child_count: 1, created_at: '2026-01-01', updated_at: '2026-01-01' },
    { id: 10, name: 'Research', version: 2, child_count: 0, created_at: '2026-01-01', updated_at: '2026-01-01' },
  ]
  vi.mocked(updateChannelGroup).mockResolvedValue({ id: 1, root_id: 10, name: 'Existing' })
  renderWorkspace('/channels/groups?root=9&group=1')
  expect(await screen.findByRole('heading', { name: 'Personal / Existing' })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: '编辑子分组' }))
  fireEvent.change(screen.getByRole('combobox', { name: '所属根分类' }), { target: { value: '10' } })
  fireEvent.click(screen.getByRole('button', { name: '保存' }))
  await waitFor(() => expect(updateChannelGroup).toHaveBeenCalledWith(1, {
    name: 'Existing', root_id: 10, expected_version: 1,
  }))
})

it('falls back from an invalid child deep link to the owned root without aggregate reading controls', async () => {
  hierarchy.roots = [
    { id: 9, name: 'Personal', version: 1, child_count: 1, created_at: '2026-01-01', updated_at: '2026-01-01' },
    { id: 10, name: 'Research', version: 2, child_count: 0, created_at: '2026-01-01', updated_at: '2026-01-01' },
  ]
  renderWorkspace('/channels/groups?root=10&group=999')
  expect(await screen.findByRole('heading', { name: 'Research' })).toBeInTheDocument()
  expect(screen.queryByRole('link', { name: '阅读此分组' })).toBeNull()
})
