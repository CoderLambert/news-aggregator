import '@tests/helpers/commandDom'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider, useMutation } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import GroupWorkspace from '@/pages/GroupWorkspace'
import { workspaceRequest } from '@/services/workspaceApi'
import { clearBulkUncertain } from '@/services/bulkWriteBarrier'

vi.mock('@/context/AuthContext', () => ({ useAuth: () => ({ user: { id: 1 }, loading: false }) }))
const reload = vi.hoisted(() => vi.fn())
vi.mock('@/services/channelQueries', () => ({
  useChannelConfig: () => ({ enabled: true, ready: true, error: false, retry: reload, groups: { data: [{ id: 1, name: '前端', source_ids: [2] }, { id: 3, name: '后端', source_ids: [] }] }, subscriptions: { data: [{ source_id: 2, group_ids: [1] }, { source_id: 4, group_ids: [] }] } }),
  useChannelMutation: () => useMutation({ mutationFn: (perform: () => Promise<unknown>) => perform() }),
}))
vi.mock('@/services/workspaceApi', async original => ({
  ...await original<typeof import('@/services/workspaceApi')>(), workspaceRequest: vi.fn(),
  workspaceCatalogOptions: () => ({ queryKey: ['bulk-catalog'], queryFn: async () => ({ sources: [{ id: 2, name: 'React', topics: [] }, { id: 4, name: 'Vue', topics: [] }], topics: [] }) }),
}))
beforeEach(() => { clearBulkUncertain(1); vi.mocked(workspaceRequest).mockReset().mockResolvedValue([]); reload.mockReset().mockResolvedValue([{ isSuccess: true }, { isSuccess: true }]) })
afterEach(cleanup)
function view() {
  return <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter><GroupWorkspace /></MemoryRouter></QueryClientProvider>
}
function setup() { return render(view()) }
it('moves a selected channel to a searchable target with one atomic bulk request', async () => {
  setup()
  fireEvent.click(await screen.findByRole('checkbox', { name: '选择 React' }))
  fireEvent.click(screen.getByRole('combobox', { name: '目标分组' }))
  fireEvent.click(screen.getByRole('option', { name: '后端' }))
  fireEvent.click(screen.getByRole('button', { name: '移动到目标分组' }))
  await waitFor(() => expect(workspaceRequest).toHaveBeenCalledWith('/me/channel-subscriptions/', expect.objectContaining({ method: 'POST', viewer: 1, signal: expect.any(AbortSignal), body: { action: 'move_to_group', group_id: 3, source_ids: [2] } })))
  expect(await screen.findByRole('status')).toHaveTextContent('移动')
})
it('filters ungrouped channels and removes hidden selections from bulk changes', async () => {
  setup()
  fireEvent.click(await screen.findByRole('checkbox', { name: '选择 React' }))
  fireEvent.change(screen.getByRole('combobox', { name: '频道范围' }), { target: { value: 'ungrouped' } })
  expect(screen.queryByRole('checkbox', { name: '选择 React' })).toBeNull()
  expect(screen.getByRole('checkbox', { name: '选择 Vue' })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: '移动到目标分组' })).toBeNull()
  expect(workspaceRequest).not.toHaveBeenCalled()
})

it('blocks every write after an unknown bulk outcome until both private reads reconcile', async () => {
  vi.mocked(workspaceRequest).mockRejectedValueOnce(Error('response lost'))
  reload.mockRejectedValueOnce(Error('reload offline'))
  setup()
  fireEvent.click(await screen.findByRole('checkbox', { name: '选择 React' }))
  fireEvent.click(screen.getByRole('button', { name: '移动到目标分组' }))
  await waitFor(() => expect(screen.getByRole('button', { name: '移动到目标分组' })).toBeDisabled())
  expect(screen.getByRole('checkbox', { name: '选择 React' })).toBeChecked()
  expect(screen.getByRole('button', { name: '新建分组' })).toBeDisabled()
  expect(screen.getByRole('button', { name: '重命名分组' })).toBeDisabled()
  expect(screen.getByRole('button', { name: '删除分组' })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: '移动到目标分组' }))
  expect(workspaceRequest).toHaveBeenCalledTimes(1)
  fireEvent.click(screen.getByRole('button', { name: '重新读取分组与订阅' }))
  await screen.findByText('重新读取失败，仍暂停所有修改。')
  expect(screen.getByRole('button', { name: '移动到目标分组' })).toBeDisabled()
  reload.mockResolvedValueOnce([{ isSuccess: true }, { isSuccess: false }])
  fireEvent.click(screen.getByRole('button', { name: '重新读取分组与订阅' }))
  await waitFor(() => expect(reload).toHaveBeenCalledTimes(2))
  expect(screen.getByRole('button', { name: '移动到目标分组' })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: '重新读取分组与订阅' }))
  await waitFor(() => expect(screen.getByRole('button', { name: '移动到目标分组' })).toBeEnabled())
  expect(screen.getByRole('checkbox', { name: '选择 React' })).toBeChecked()
  expect(workspaceRequest).toHaveBeenCalledTimes(1)
})

it('keeps the unknown-bulk barrier across a remount so nothing is retried blindly', async () => {
  vi.mocked(workspaceRequest).mockRejectedValueOnce(Error('response lost'))
  const first = setup()
  fireEvent.click(await screen.findByRole('checkbox', { name: '选择 React' }))
  fireEvent.click(screen.getByRole('button', { name: '移动到目标分组' }))
  await waitFor(() => expect(screen.getByRole('button', { name: '移动到目标分组' })).toBeDisabled())
  first.unmount()
  // Re-entering the page must not drop the barrier: the request may still have
  // been applied server-side and the cached reads are pre-write data.
  setup()
  expect(await screen.findByText(/批量操作结果尚未确认/)).toBeInTheDocument()
  expect(screen.getByRole('button', { name: '新建分组' })).toBeDisabled()
  expect(screen.getByRole('button', { name: '重命名分组' })).toBeDisabled()
  expect(workspaceRequest).toHaveBeenCalledTimes(1)
  fireEvent.click(screen.getByRole('button', { name: '重新读取分组与订阅' }))
  await waitFor(() => expect(screen.getByRole('button', { name: '新建分组' })).toBeEnabled())
  expect(workspaceRequest).toHaveBeenCalledTimes(1)
})

it('merges group-card wrapping over the button defaults so names do not stay h-9 nowrap', async () => {
  setup()
  const card = await screen.findByRole('button', { name: /前端/ })
  expect(card.className).toContain('whitespace-normal')
  expect(card.className).toContain('h-auto')
  expect(card.className).not.toContain('whitespace-nowrap')
  expect(card.className).not.toMatch(/(^|\s)h-9(\s|$)/)
})
