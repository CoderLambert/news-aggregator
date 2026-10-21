import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { newsKeys } from '@/services/newsQueries'
import OpmlDialog from '@/features/rss/OpmlDialog'
import { workspaceRequest } from '@/services/workspaceApi'

vi.mock('@/services/workspaceApi', async importOriginal => ({ ...await importOriginal<typeof import('@/services/workspaceApi')>(), workspaceRequest: vi.fn(), workspaceError: () => '网络连接失败' }))
const request = vi.mocked(workspaceRequest)
const id = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
const row = { id, filename: '我的订阅.opml', file_size: 250, file_available: true, created_at: '2026-10-21T10:00:00Z',
  status: 'complete', removed_at: null, removed_count: 0, total: 3, counts: { succeeded: 2, failed: 1 } }
const clients: QueryClient[] = []
function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  clients.push(client)
  client.setQueryData(['channels', 'personal', 12, 'subscriptions'], [])
  client.setQueryData(newsKeys.sources('zh', 12), [])
  client.setQueryData(['news', 'list', { viewerId: 12, scope: 'all', lang: 'zh' }], { results: [] })
  client.setQueryData(newsKeys.sources('zh', 13), [])
  const ui = (viewer: number) => <QueryClientProvider client={client}><OpmlDialog viewer={viewer} groups={[]} onClose={vi.fn()} /></QueryClientProvider>
  const view = render(ui(12))
  return { client, switchViewer: (viewer: number) => view.rerender(ui(viewer)) }
}
beforeEach(() => {
  vi.resetAllMocks()
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', '') }
  HTMLDialogElement.prototype.close = function () { this.removeAttribute('open') }
})
afterEach(() => { cleanup(); clients.splice(0).forEach(client => client.clear()) })

it('opens retained history and requires explicit confirmation to remove only batch additions', async () => {
  request.mockImplementation(async (path, options) => options?.method === 'DELETE'
    ? { ...row, status: 'removed', removed_at: '2026-10-21T11:00:00Z', removed_count: 1, groups: [], items: [] }
    : { count: 1, page: 1, has_next: false, results: [row] })
  const { client } = setup()
  fireEvent.click(screen.getByRole('button', { name: '导入历史' }))
  expect(await screen.findByText('我的订阅.opml')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: '下载原文件' })).toHaveAttribute('href', `/api/me/rss-imports/${id}/file/`)
  fireEvent.click(screen.getByRole('button', { name: '移除此批新增订阅' }))
  expect(request.mock.calls.filter(([, opts]) => opts?.method === 'DELETE')).toHaveLength(0)
  expect(screen.getByText(/保留共享频道、文章和导入前已有的订阅/)).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: '确认移除新增订阅' }))
  await waitFor(() => expect(request).toHaveBeenCalledWith(`/me/rss-imports/${id}/`, expect.objectContaining({ method: 'DELETE', viewer: 12 })))
  expect(await screen.findByText('已移除 1 个新增订阅')).toBeInTheDocument()
  await waitFor(() => expect(client.getQueryState(newsKeys.sources('zh', 12))?.isInvalidated).toBe(true))
  expect(client.getQueryState(['news', 'list', { viewerId: 12, scope: 'all', lang: 'zh' }])?.isInvalidated).toBe(true)
  expect(client.getQueryState(newsKeys.sources('zh', 13))?.isInvalidated).toBe(false)
})

it('loads previous pages and resumes a batch without a manual record number', async () => {
  request.mockImplementation(async path => path === `/me/rss-imports/${id}/`
    ? { ...row, groups: [], items: [{ id: 'one', title: 'News', feed_url: 'https://example.com/rss', groups: [], status: 'succeeded', error_code: '', operation_id: null }] }
    : { count: 21, page: path.endsWith('page=2') ? 2 : 1, has_next: !path.endsWith('page=2'), results: [row] })
  const { client } = setup()
  fireEvent.click(screen.getByRole('button', { name: '导入历史' }))
  fireEvent.click(await screen.findByRole('button', { name: '下一页' }))
  await waitFor(() => expect(request).toHaveBeenCalledWith('/me/rss-imports/?page=2', expect.anything()))
  fireEvent.click(await screen.findByRole('button', { name: '查看详情与进度' }))
  expect(await screen.findByText('News')).toBeInTheDocument()
  await waitFor(() => expect(client.getQueryState(['channels', 'personal', 12, 'subscriptions'])?.isInvalidated).toBe(true))
})

it('preserves a failed removal confirmation for an idempotent explicit retry', async () => {
  request.mockImplementation(async (_path, options) => {
    if (options?.method === 'DELETE') throw new Error('offline')
    return { count: 1, page: 1, has_next: false, results: [row] }
  })
  setup()
  fireEvent.click(screen.getByRole('button', { name: '导入历史' }))
  fireEvent.click(await screen.findByRole('button', { name: '移除此批新增订阅' }))
  fireEvent.click(screen.getByRole('button', { name: '确认移除新增订阅' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('网络连接失败')
  expect(screen.getByRole('button', { name: '确认移除新增订阅' })).toBeEnabled()
  expect(request.mock.calls.filter(([, options]) => options?.method === 'DELETE')).toHaveLength(1)
})

it('ignores a removal response after switching accounts', async () => {
  let finish!: (value: unknown) => void
  request.mockImplementation(async (_path, options) => options?.method === 'DELETE'
    ? new Promise(resolve => { finish = resolve })
    : { count: 1, page: 1, has_next: false, results: [row] })
  const view = setup()
  fireEvent.click(screen.getByRole('button', { name: '导入历史' }))
  fireEvent.click(await screen.findByRole('button', { name: '移除此批新增订阅' }))
  fireEvent.click(screen.getByRole('button', { name: '确认移除新增订阅' }))
  await waitFor(() => expect(finish).toBeDefined())
  view.switchViewer(13)
  await act(async () => { finish({ ...row, status: 'removed', removed_count: 2 }); await Promise.resolve() })
  expect(screen.queryByText('已移除 2 个新增订阅')).not.toBeInTheDocument()
  expect(view.client.getQueryData(['private', 'rss-import', 12, id])).toBeUndefined()
})
