import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import OpmlDialog from '@/features/rss/OpmlDialog'
import { workspaceRequest } from '@/services/workspaceApi'

vi.mock('@/services/workspaceApi', async importOriginal => ({ ...await importOriginal<typeof import('@/services/workspaceApi')>(), workspaceRequest: vi.fn(), workspaceError: () => '操作未完成，请重试。' }))
const request = vi.mocked(workspaceRequest)
const batch = { id: 'batch', status: 'preview', preview_token: 'signed-token', groups: ['Tech'], items: [
  { id: 'one', title: 'One', feed_url: 'https://example.com/rss', groups: ['Tech'], status: 'preview', error_code: '', operation_id: null },
  { id: 'bad', title: 'Invalid', feed_url: '', groups: [], status: 'invalid', error_code: 'credential_feed_not_supported', operation_id: null },
] }
beforeEach(() => {
  vi.clearAllMocks()
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', '') }
  HTMLDialogElement.prototype.close = function () { this.removeAttribute('open') }
})
afterEach(cleanup)
function setup() { return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}>
  <OpmlDialog viewer={12} roots={[{ id: 1, name: 'Personal', version: 1, child_count: 1, created_at: '2026-01-01', updated_at: '2026-01-01' }]} groups={[{ id: 7, root_id: 1, name: 'Mine', source_ids: [], version: 1, created_at: '2026-01-01', updated_at: '2026-01-01' }]} onClose={vi.fn()} />
</QueryClientProvider>) }

describe('personal OPML workflow', () => {
  it('uploads bytes, requires confirmation and sends only selected valid entries with explicit group mapping', async () => {
    request.mockResolvedValueOnce(batch).mockResolvedValueOnce({ ...batch, status: 'confirmed' }).mockResolvedValue({ ...batch, status: 'complete', items: [] })
    setup()
    expect(request).not.toHaveBeenCalled()
    const file = new File(['<opml/>'], 'feeds.opml', { type: 'text/xml' })
    fireEvent.change(screen.getByLabelText('OPML 文件'), { target: { files: [file] } })
    fireEvent.click(screen.getByRole('button', { name: '预览文件' }))
    expect(await screen.findByRole('checkbox', { name: '导入 One' })).toBeChecked()
    expect(screen.getByRole('checkbox', { name: '导入 Invalid' })).toBeDisabled()
    expect(request.mock.calls[0][1]?.body).toBeInstanceOf(FormData)
    expect(request).toHaveBeenCalledTimes(1)
    fireEvent.change(screen.getByRole('combobox', { name: 'Tech映射分组' }), { target: { value: '7' } })
    fireEvent.click(screen.getByRole('button', { name: '确认导入 1 项' }))
    await waitFor(() => expect(request).toHaveBeenCalledWith('/me/rss-imports/confirm/', expect.objectContaining({ viewer: 12,
      body: { preview_token: 'signed-token', selected_ids: ['one'], group_map: { Tech: 7 } } })))
  })
  it('preselects an exact nested path and keeps existing-child mappings numeric', async () => {
    const nested = { ...batch, groups: ['Personal / Mine'], group_matches: { 'Personal / Mine': 7 } }
    request.mockResolvedValueOnce(nested).mockResolvedValueOnce({ ...nested, status: 'confirmed' })
    setup()
    fireEvent.change(screen.getByLabelText('OPML 文件'), { target: { files: [new File(['<opml/>'], 'nested.opml')] } })
    fireEvent.click(screen.getByRole('button', { name: '预览文件' }))
    expect(await screen.findByRole('combobox', { name: 'Personal / Mine映射分组' })).toHaveValue('7')
    fireEvent.click(screen.getByRole('button', { name: '确认导入 1 项' }))
    await waitFor(() => expect(request).toHaveBeenCalledWith('/me/rss-imports/confirm/', expect.objectContaining({
      body: { preview_token: 'signed-token', selected_ids: ['one'], group_map: { 'Personal / Mine': 7 } },
    })))
  })

  it('requires an explicit owned root when confirming a new child', async () => {
    request.mockResolvedValueOnce(batch).mockResolvedValueOnce({ ...batch, status: 'confirmed' })
    setup()
    fireEvent.change(screen.getByLabelText('OPML 文件'), { target: { files: [new File(['<opml/>'], 'new-child.opml')] } })
    fireEvent.click(screen.getByRole('button', { name: '预览文件' }))
    fireEvent.change(await screen.findByRole('combobox', { name: 'Tech映射分组' }), { target: { value: 'new:1' } })
    fireEvent.click(screen.getByRole('button', { name: '确认导入 1 项' }))
    await waitFor(() => expect(request).toHaveBeenCalledWith('/me/rss-imports/confirm/', expect.objectContaining({
      body: { preview_token: 'signed-token', selected_ids: ['one'], group_map: { Tech: { create: 'Tech', root_id: 1 } } },
    })))
  })
  it('keeps oversized upload local and offers personal export', () => {
    setup()
    fireEvent.change(screen.getByLabelText('OPML 文件'), { target: { files: [new File(['x'.repeat(1024 * 1024 + 1)], 'big.opml')] } })
    expect(screen.getByRole('button', { name: '预览文件' })).toBeDisabled()
    expect(screen.getByRole('alert')).toHaveTextContent('超过1MiB')
    expect(screen.getByRole('link', { name: '导出我的订阅' })).toHaveAttribute('href', '/api/me/rss-subscriptions/export/')
    expect(request).not.toHaveBeenCalled()
  })
  it('selects only valid entries in bulk and reports preview counts', async () => {
    request.mockResolvedValue(batch)
    setup()
    fireEvent.change(screen.getByLabelText('OPML 文件'), { target: { files: [new File(['<opml/>'], 'feeds.opml')] } })
    fireEvent.click(screen.getByRole('button', { name: '预览文件' }))
    expect(await screen.findByText('共 2 项 · 可导入 1 项 · 无效 1 项 · 重复合并 0 项 · 已订阅 0 项 · 已选 1 项')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '取消全选' }))
    expect(screen.getByRole('checkbox', { name: '导入 One' })).not.toBeChecked()
    expect(screen.getByRole('button', { name: '确认导入 0 项' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: '全选有效频道' }))
    expect(screen.getByRole('checkbox', { name: '导入 One' })).toBeChecked()
    expect(screen.getByRole('checkbox', { name: '导入 Invalid' })).not.toBeChecked()
  })

  it('skips existing subscriptions without counting them as invalid entries', async () => {
    const duplicate = { ...batch, duplicate_count: 3, items: [
      { ...batch.items[0], outcome: 'already_subscribed' },
      { ...batch.items[0], id: 'two', title: 'Two', outcome: 'reused' },
    ] }
    request.mockResolvedValue(duplicate)
    setup()
    fireEvent.change(screen.getByLabelText('OPML 文件'), { target: { files: [new File(['<opml/>'], 'feeds.opml')] } })
    fireEvent.click(screen.getByRole('button', { name: '预览文件' }))
    expect(await screen.findByText('共 2 项 · 可导入 1 项 · 无效 0 项 · 重复合并 3 项 · 已订阅 1 项 · 已选 1 项')).toBeInTheDocument()
    expect(screen.getByRole('checkbox', { name: '导入 One' })).toBeDisabled()
    expect(screen.getByRole('checkbox', { name: '导入 One' })).not.toBeChecked()
    expect(screen.getByRole('checkbox', { name: '导入 Two' })).toBeChecked()
  })

  it('pauses, resumes and confirms cancellation of remaining work while retaining completed subscriptions', async () => {
    const id = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
    let current = { ...batch, id, status: 'confirmed', paused: false, cancelled_at: null as string | null, items: [
      { ...batch.items[0], status: 'succeeded', outcome: 'connected' },
      { ...batch.items[0], id: 'two', title: 'Two', status: 'pending', outcome: 'waiting' },
    ] }
    request.mockImplementation(async (_path, options) => {
      if (options?.method === 'PATCH') {
        const { action } = options.body as { action: string }
        current = { ...current, paused: action === 'pause', cancelled_at: action === 'cancel' ? '2026-10-22T00:00:00Z' : null,
          items: action === 'cancel' ? current.items.map(item => item.status === 'pending' ? { ...item, status: 'removed', outcome: 'cancelled' } : item) : current.items }
      }
      return current
    })
    setup()
    fireEvent.change(screen.getByLabelText('恢复导入记录'), { target: { value: id } })
    fireEvent.click(screen.getByRole('button', { name: '查看进度' }))
    fireEvent.click(await screen.findByRole('button', { name: '暂停接入' }))
    fireEvent.click(await screen.findByRole('button', { name: '继续自动接入' }))
    await screen.findByRole('button', { name: '暂停接入' })
    fireEvent.click(screen.getByRole('button', { name: '取消剩余任务' }))
    expect(request.mock.calls.filter(([, options]) => options?.method === 'PATCH')).toHaveLength(2)
    fireEvent.click(screen.getByRole('button', { name: '确认取消剩余' }))
    await waitFor(() => expect(request.mock.calls.filter(([, options]) => options?.method === 'PATCH')).toHaveLength(3))
    expect(await screen.findByText(/剩余任务已取消，已建立的订阅保留/)).toBeInTheDocument()
    expect(screen.getByText('One')).toBeInTheDocument()
    expect(screen.getByText('已接入')).toBeInTheDocument()
    expect(screen.getByText('已取消')).toBeInTheDocument()
    expect(request).toHaveBeenLastCalledWith(`/me/rss-imports/${id}/`, expect.objectContaining({ viewer: 12, body: { action: 'cancel' } }))
  })

})
