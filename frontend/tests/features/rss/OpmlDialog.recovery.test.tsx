import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import OpmlDialog from '@/features/rss/OpmlDialog'
import { workspaceRequest } from '@/services/workspaceApi'

vi.mock('@/services/workspaceApi', () => ({ workspaceRequest: vi.fn(), workspaceError: () => '合成网络错误' }))
const request = vi.mocked(workspaceRequest)
const A = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
const B = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
const previewBatch = { id: A, status: 'preview', preview_token: 'synthetic-preview-a', groups: ['Tech'], items: [
  { id: 'one', title: 'One', feed_url: 'https://publisher.example/one.xml', groups: ['Tech'], status: 'preview', error_code: '', operation_id: null },
  { id: 'two', title: 'Two', feed_url: 'https://publisher.example/two.xml', groups: ['Tech'], status: 'preview', error_code: '', operation_id: null },
] }
const completeBatch = { ...previewBatch, status: 'complete', items: previewBatch.items.map(item => ({ ...item, status: 'succeeded' })) }
const partialBatch = { ...completeBatch, items: [completeBatch.items[0], { ...previewBatch.items[1], status: 'failed', error_code: 'timeout' }] }
const clients: QueryClient[] = []
function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(done => { resolve = done })
  return { promise, resolve }
}
function setup(viewer = 12) {
  // Component-level retry policy must override inherited retries for writes.
  const client = new QueryClient({ defaultOptions: { queries: { retry: 2 }, mutations: { retry: 2 } } })
  clients.push(client)
  const ui = (id: number) => <QueryClientProvider client={client}>
    <OpmlDialog viewer={id} groups={[{ id: id === 12 ? 7 : 8, name: id === 12 ? 'Mine' : 'Other', source_ids: [] }]} onClose={vi.fn()} />
  </QueryClientProvider>
  const view = render(ui(viewer))
  return { ...view, client, switchViewer: (id: number) => view.rerender(ui(id)) }
}
function selectFile(name = 'feeds.opml') {
  const file = new File(['<opml/>'], name, { type: 'text/xml' })
  fireEvent.change(screen.getByLabelText('OPML 文件'), { target: { files: [file] } })
  return file
}
async function preview() {
  selectFile()
  fireEvent.click(screen.getByRole('button', { name: '预览文件' }))
  await screen.findByRole('checkbox', { name: '导入 One' })
}
function resume(id = A) {
  fireEvent.change(screen.getByLabelText('恢复导入记录'), { target: { value: id } })
  fireEvent.click(screen.getByRole('button', { name: '查看进度' }))
}
const posts = (path: string) => request.mock.calls.filter(([url, options]) => url === path && options?.method === 'POST')
const reads = (id = A) => request.mock.calls.filter(([url, options]) => url === `/me/rss-imports/${id}/` && options?.method !== 'POST')

beforeEach(() => {
  vi.resetAllMocks()
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', '') }
  HTMLDialogElement.prototype.close = function () { this.removeAttribute('open') }
})
afterEach(() => { cleanup(); clients.splice(0).forEach(client => client.clear()) })

describe('RSS T21 recovery and owner isolation', () => {
  it('retries a failed preview only after an explicit request and uploads the same bytes', async () => {
    request.mockRejectedValueOnce(new Error('offline')).mockResolvedValue(previewBatch)
    setup()
    const file = selectFile()
    fireEvent.click(screen.getByRole('button', { name: '预览文件' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('文件预览失败')
    expect(request).toHaveBeenCalledTimes(1)
    expect(screen.queryByRole('button', { name: /确认导入/ })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '预览文件' }))
    await screen.findByRole('checkbox', { name: '导入 One' })
    expect(posts('/me/rss-imports/preview/')).toHaveLength(2)
    for (const [, options] of posts('/me/rss-imports/preview/')) expect((options?.body as FormData).get('file')).toBe(file)
    expect(posts('/me/rss-imports/confirm/')).toHaveLength(0)
  })

  it('clears old preview and selections as soon as a different file is chosen', async () => {
    request.mockResolvedValue(previewBatch)
    setup(); await preview()
    selectFile('replacement.opml')
    expect(screen.queryByRole('checkbox', { name: '导入 One' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /确认导入/ })).not.toBeInTheDocument()
    expect(request).toHaveBeenCalledTimes(1)
  })

  it('clears a preview when the file chooser is emptied', async () => {
    request.mockResolvedValue(previewBatch)
    setup(); await preview()
    fireEvent.change(screen.getByLabelText('OPML 文件'), { target: { files: [] } })
    expect(screen.getByRole('button', { name: '预览文件' })).toBeDisabled()
    expect(screen.queryByRole('button', { name: /确认导入/ })).not.toBeInTheDocument()
  })

  it('freezes a failed confirmation and replays precisely the same token, choices and groups', async () => {
    request.mockImplementation(async path => {
      if (path.endsWith('/preview/')) return previewBatch
      if (path.endsWith('/confirm/') && posts(path).length === 1) throw new Error('lost response')
      return completeBatch
    })
    setup(); await preview()
    fireEvent.click(screen.getByRole('checkbox', { name: '导入 Two' }))
    fireEvent.change(screen.getByRole('combobox', { name: 'Tech映射分组' }), { target: { value: '7' } })
    fireEvent.click(screen.getByRole('button', { name: '确认导入 1 项' }))
    await screen.findByRole('button', { name: '重试确认导入' })
    expect(screen.getByRole('checkbox', { name: '导入 One' })).toBeDisabled()
    expect(screen.getByRole('combobox', { name: 'Tech映射分组' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '确认导入 1 项' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: '重试确认导入' }))
    await screen.findByText(A, { selector: 'code' })
    const calls = posts('/me/rss-imports/confirm/')
    expect(calls).toHaveLength(2)
    expect(calls[0][1]?.body).toEqual({ preview_token: 'synthetic-preview-a', selected_ids: ['one'], group_map: { Tech: 7 } })
    expect(calls[1][1]?.body).toBe(calls[0][1]?.body)
    expect(posts('/me/rss-imports/preview/')).toHaveLength(1)
  })

  it('requires a fresh preview before changing a failed confirmation', async () => {
    request.mockImplementation(async path => {
      if (path.endsWith('/preview/')) return { ...previewBatch, preview_token: `token-${posts(path).length}` }
      throw new Error('lost response')
    })
    setup(); await preview()
    fireEvent.click(screen.getByRole('button', { name: '确认导入 2 项' }))
    await screen.findByRole('button', { name: '重试确认导入' })
    fireEvent.click(screen.getByRole('button', { name: '预览文件' }))
    await waitFor(() => expect(screen.getByRole('checkbox', { name: '导入 One' })).toBeEnabled())
    fireEvent.click(screen.getByRole('checkbox', { name: '导入 Two' }))
    fireEvent.click(screen.getByRole('button', { name: '确认导入 1 项' }))
    await waitFor(() => expect(posts('/me/rss-imports/confirm/')).toHaveLength(2))
    expect(posts('/me/rss-imports/confirm/')[1][1]?.body).toEqual({ preview_token: 'token-2', selected_ids: ['one'], group_map: {} })
  })

  it('preserves the confirmed record ID when progress fails and recovery sends GET only', async () => {
    request.mockImplementation(async (path, options) => {
      if (path.endsWith('/preview/')) return previewBatch
      if (path.endsWith('/confirm/')) return { ...previewBatch, status: 'confirmed', items: previewBatch.items.map(item => ({ ...item, status: 'pending' })) }
      if (options?.method !== 'POST' && reads().length === 1) throw new Error('offline')
      return completeBatch
    })
    setup(); await preview()
    fireEvent.click(screen.getByRole('button', { name: '确认导入 2 项' }))
    await screen.findByRole('button', { name: '重新读取导入进度' })
    expect(screen.getByText(A, { selector: 'code' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '重新读取导入进度' }))
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument())
    expect(reads()).toHaveLength(2)
    expect(posts('/me/rss-imports/confirm/')).toHaveLength(1)
    expect(posts('/me/rss-imports/preview/')).toHaveLength(1)
  })

  it('can explicitly reread the same restored record after a failed GET', async () => {
    request.mockRejectedValueOnce(new Error('offline')).mockResolvedValue(completeBatch)
    setup(); resume()
    await screen.findByRole('alert')
    expect(screen.getByText(A, { selector: 'code' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '查看进度' }))
    await screen.findByText('One')
    expect(reads()).toHaveLength(2)
    expect(request.mock.calls.every(([, options]) => options?.method !== 'POST')).toBe(true)
  })

  it('rejects malformed record identifiers before issuing requests', () => {
    setup()
    fireEvent.change(screen.getByLabelText('恢复导入记录'), { target: { value: '-'.repeat(36) } })
    expect(screen.getByRole('button', { name: '查看进度' })).toBeDisabled()
    fireEvent.submit(screen.getByLabelText('恢复导入记录').closest('form')!)
    expect(request).not.toHaveBeenCalled()
  })

  it('retries only the explicitly failed item, preserving already connected items', async () => {
    request.mockImplementation(async (path, options) => {
      if (options?.method === 'POST') return completeBatch
      return posts(path).length ? completeBatch : partialBatch
    })
    setup(); resume()
    fireEvent.click(await screen.findByRole('button', { name: '重试此项' }))
    await waitFor(() => expect(screen.queryByRole('button', { name: '重试此项' })).not.toBeInTheDocument())
    expect(posts(`/me/rss-imports/${A}/`)).toHaveLength(1)
    expect(posts(`/me/rss-imports/${A}/`)[0][1]).toEqual(expect.objectContaining({ viewer: 12, body: { selected_ids: ['two'] } }))
    expect(screen.getByText('One')).toBeInTheDocument()
  })

  it('reconciles a lost retry response with GET instead of replaying POST', async () => {
    request.mockImplementation(async (path, options) => {
      if (options?.method === 'POST') throw new Error('response lost after queueing')
      return posts(path).length ? completeBatch : partialBatch
    })
    setup(); resume()
    fireEvent.click(await screen.findByRole('button', { name: '重试此项' }))
    await screen.findByRole('button', { name: '重新读取导入进度' })
    expect(screen.getByRole('button', { name: '重试此项' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: '重新读取导入进度' }))
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument())
    expect(posts(`/me/rss-imports/${A}/`)).toHaveLength(1)
    expect(reads()).toHaveLength(2)
    expect(screen.queryByRole('button', { name: '重试此项' })).not.toBeInTheDocument()
  })

  it('stops automatic reads after a progress error even with pending cached items', async () => {
    request.mockImplementation(async path => {
      if (path.endsWith('/preview/')) return previewBatch
      if (path.endsWith('/confirm/')) return { ...previewBatch, status: 'confirmed', items: previewBatch.items.map(item => ({ ...item, status: 'pending' })) }
      throw new Error('offline')
    })
    setup(); await preview()
    fireEvent.click(screen.getByRole('button', { name: '确认导入 2 项' }))
    await screen.findByRole('button', { name: '重新读取导入进度' })
    await act(async () => { await new Promise(done => setTimeout(done, 2200)) })
    expect(reads()).toHaveLength(1)
    expect(posts('/me/rss-imports/confirm/')).toHaveLength(1)
  })

  it('shows skipped entries as not imported and does not poll a terminal batch', async () => {
    request.mockResolvedValue({ ...completeBatch, items: [completeBatch.items[0], previewBatch.items[1]] })
    setup(); resume()
    await screen.findByText('未选择，未导入')
    await act(async () => { await new Promise(done => setTimeout(done, 2200)) })
    expect(reads()).toHaveLength(1)
  })

  it('resets file, groups and record when the viewer changes and ignores a late preview', async () => {
    const delayed = deferred<typeof previewBatch>()
    request.mockReturnValueOnce(delayed.promise)
    const view = setup(); selectFile()
    fireEvent.click(screen.getByRole('button', { name: '预览文件' }))
    await waitFor(() => expect(request).toHaveBeenCalledTimes(1))
    const signal = request.mock.calls[0][1]?.signal
    view.switchViewer(13)
    expect(signal?.aborted).toBe(true)
    await act(async () => { delayed.resolve(previewBatch); await delayed.promise })
    expect(screen.queryByText('One')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '预览文件' })).toBeDisabled()
    expect(screen.getByLabelText('恢复导入记录')).toHaveValue('')
    expect(posts('/me/rss-imports/confirm/')).toHaveLength(0)
  })

  it('does not repopulate old viewer cache when confirmation resolves after an account switch', async () => {
    const delayed = deferred<typeof completeBatch>()
    request.mockResolvedValueOnce(previewBatch).mockReturnValueOnce(delayed.promise)
    const view = setup(); await preview()
    fireEvent.click(screen.getByRole('button', { name: '确认导入 2 项' }))
    await waitFor(() => expect(posts('/me/rss-imports/confirm/')).toHaveLength(1))
    view.switchViewer(13)
    await act(async () => { delayed.resolve(completeBatch); await delayed.promise })
    expect(view.client.getQueryData(['private', 'rss-import', 12, A])).toBeUndefined()
    expect(screen.queryByText(A)).not.toBeInTheDocument()
    expect(reads()).toHaveLength(0)
  })

  it('ignores an old progress response after another record is opened', async () => {
    const delayed = deferred<typeof completeBatch>()
    request.mockReturnValueOnce(delayed.promise).mockResolvedValue({ ...completeBatch, id: B, items: [] })
    setup(); resume()
    await waitFor(() => expect(reads()).toHaveLength(1))
    // A cancellation-aware transport normally rejects; this mock resolves late.
    fireEvent.change(screen.getByLabelText('恢复导入记录'), { target: { value: B } })
    fireEvent.click(screen.getByRole('button', { name: '查看进度' }))
    await waitFor(() => expect(reads(B)).toHaveLength(1))
    await act(async () => { delayed.resolve(completeBatch); await delayed.promise })
    expect(screen.getByText(B, { selector: 'code' })).toBeInTheDocument()
    expect(screen.queryByText('One')).not.toBeInTheDocument()
  })
})
