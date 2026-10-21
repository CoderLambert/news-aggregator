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
  <OpmlDialog viewer={12} groups={[{ id: 7, name: 'Mine', source_ids: [] }]} onClose={vi.fn()} />
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
    expect(await screen.findByText('共 2 项 · 可导入 1 项 · 无效 1 项 · 已选 1 项')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '取消全选' }))
    expect(screen.getByRole('checkbox', { name: '导入 One' })).not.toBeChecked()
    expect(screen.getByRole('button', { name: '确认导入 0 项' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: '全选有效频道' }))
    expect(screen.getByRole('checkbox', { name: '导入 One' })).toBeChecked()
    expect(screen.getByRole('checkbox', { name: '导入 Invalid' })).not.toBeChecked()
  })

})
