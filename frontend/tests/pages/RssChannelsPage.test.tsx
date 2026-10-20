import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, useLocation } from 'react-router-dom'
import RssChannelsPage from '@/pages/admin/RssChannelsPage'
import { workspaceRequest } from '@/services/workspaceApi'

const auth = vi.hoisted(() => ({ user: { id: 17, isSuperuser: true } }))
vi.mock('@/context/AuthContext', () => ({ useAuth: () => auth }))
vi.mock('@/services/workspaceApi', () => ({ workspaceRequest: vi.fn(), workspaceError: () => '加载失败，请重试。' }))
const request = vi.mocked(workspaceRequest)
const feed = { id: 'binding', feed_url: 'https://example.com/feed', status: 'unknown', policy_version: 1,
  connection_state: 'paused', error_code: 'create_unknown', operation_state: 'manual_blocked', execution_phase: 'missing',
  checked_at: null, cooldown_until: null, can_verify: true, action_reason: '', recovery_requires_boundary: true, history: [] }
const source = { source_id: 3, name: '待恢复频道', status: 'unknown', can_subscribe: false, can_verify: true,
  pending: false, expected_versions: { binding: 1 }, feeds: [feed] }
const list = { results: [source], count: 1, counts: { pending: 3, verifying: 0, passed: 7, all: 10 }, page: 1, page_size: 25, server_time: new Date().toISOString() }
const batch = { id: 'batch', items: [{ source_id: 3, binding_id: 'binding', status: 'accepted', reason: '', operation_id: 'op' }], counts: { accepted: 1 }, done: false }
let client: QueryClient
beforeEach(() => {
  vi.clearAllMocks()
  auth.user = { id: 17, isSuperuser: true }
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', '') }
  HTMLDialogElement.prototype.close = function () { this.removeAttribute('open') }
  request.mockImplementation(async path => path.includes('/verification-batches/') ? batch : path.includes('/verification/') ? source : list)
  client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
})
afterEach(() => { cleanup(); client.clear() })
function Location() { return <output data-testid="location">{useLocation().search}</output> }
function setup(url = '/admin/rss/channels') {
  return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[url]}><RssChannelsPage /><Location /></MemoryRouter></QueryClientProvider>)
}
it('opens the pending list immediately and persists search, filters and page size in the URL', async () => {
  setup()
  expect(await screen.findByRole('button', { name: '查看待恢复频道详情' })).toBeInTheDocument()
  expect(request.mock.calls[0][0]).toContain('status=pending')
  fireEvent.change(screen.getByLabelText('搜索频道名称或 RSS 地址'), { target: { value: '中文 News' } })
  fireEvent.submit(screen.getByRole('search'))
  await waitFor(() => expect(screen.getByTestId('location').textContent).toContain('q=%E4%B8%AD%E6%96%87+News'))
  fireEvent.change(screen.getByLabelText('每页条数'), { target: { value: '50' } })
  await waitFor(() => expect(request.mock.calls.some(([path]) => path.includes('page_size=50'))).toBe(true))
  fireEvent.click(screen.getByRole('button', { name: /已通过/ }))
  expect(screen.getByTestId('location').textContent).toContain('status=passed')
})
it('submits explicit versioned recovery targets and displays batch progress', async () => {
  setup()
  fireEvent.click(await screen.findByRole('checkbox', { name: '选择待恢复频道' }))
  fireEvent.click(screen.getByRole('button', { name: /核验所选/ }))
  await waitFor(() => expect(request).toHaveBeenCalledWith('/admin/rss/verification-batches/', expect.objectContaining({
    method: 'POST', viewer: 17, idempotencyKey: expect.any(String),
    body: { action: 'verify_and_recover', targets: [{ source_id: 3, expected_versions: { binding: 1 } }] },
  })))
  expect(await screen.findByLabelText('批量核验进度')).toBeInTheDocument()
  expect(screen.getByTestId('location').textContent).toContain('batch=batch')
})
it('shows cooldown before clicking and disables repeated submission', async () => {
  const until = new Date(Date.now()+59000).toISOString()
  request.mockResolvedValue({ ...list, results: [{ ...source, can_verify: false, feeds: [{ ...feed, can_verify: false, action_reason: 'cooldown', cooldown_until: until }] }] })
  setup()
  const button = await screen.findByRole('button', { name: /秒后可核验/ })
  expect(button).toBeDisabled()
  expect(screen.getByRole('checkbox', { name: '选择待恢复频道' })).toBeDisabled()
})
it('opens shared details and restores focus on close', async () => {
  setup()
  const opener = await screen.findByRole('button', { name: '查看待恢复频道详情' })
  opener.focus(); fireEvent.click(opener)
  expect(await screen.findByRole('dialog', { name: '频道核验详情' })).toBeInTheDocument()
  expect(await screen.findByText('缺少执行记录')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: '关闭频道核验详情' }))
  await waitFor(() => expect(opener).toHaveFocus())
})
it('preserves a bookmarked filter, and presents empty and error recovery states', async () => {
  request.mockResolvedValue({ ...list, results: [], count: 0 })
  setup('/admin/rss/channels?q=react&status=failed&page=2&page_size=50')
  expect(await screen.findByText('没有符合条件的频道。')).toBeInTheDocument()
  expect(screen.getByLabelText('搜索频道名称或 RSS 地址')).toHaveValue('react')
  expect(request.mock.calls[0][0]).toContain('page=2')
  request.mockRejectedValue(new Error('offline'))
  fireEvent.click(screen.getByRole('button', { name: '刷新列表' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('加载失败')
})

it('drops a late submission result when the account changes', async () => {
  let resolve!: (value: typeof batch) => void
  const pending = new Promise<typeof batch>(done => { resolve = done })
  request.mockImplementation(async path => path === '/admin/rss/verification-batches/' ? pending : list)
  const view = setup()
  fireEvent.click(await screen.findByRole('checkbox', { name: '选择待恢复频道' }))
  fireEvent.click(screen.getByRole('button', { name: /核验所选/ }))
  await waitFor(() => expect(request.mock.calls.some(([path]) => path === '/admin/rss/verification-batches/')).toBe(true))
  auth.user = { id: 18, isSuperuser: true }
  view.rerender(<QueryClientProvider client={client}><MemoryRouter><RssChannelsPage /><Location /></MemoryRouter></QueryClientProvider>)
  resolve(batch)
  await waitFor(() => expect(screen.getByRole('checkbox', { name: '选择待恢复频道' })).not.toBeChecked())
  expect(screen.queryByLabelText('批量核验进度')).not.toBeInTheDocument()
})
it('provides a public channel registration action for the superuser', async () => {
  setup()
  expect(await screen.findByRole('button', { name: '新增公共频道' })).toBeInTheDocument()
})
it('renders verification for a delegated reviewer without root intake controls', async () => {
  auth.user = { id: 17, isSuperuser: false, rssCapabilities: { reviewPublicRss: true, reviewerVersion: 3 } } as typeof auth.user
  setup()
  expect(await screen.findByRole('button', { name: '查看待恢复频道详情' })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: '新增公共频道' })).not.toBeInTheDocument()
})
