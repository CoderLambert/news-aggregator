import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import ChannelIntakePanel from '@/components/workspace/ChannelIntakePanel'
import { workspaceRequest } from '@/services/workspaceApi'

vi.mock('@/services/workspaceApi', async original => ({ ...(await original()), workspaceRequest: vi.fn() }))
function mount(admin = false) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={client}><ChannelIntakePanel viewer={8} admin={admin} /></QueryClientProvider>)
}
beforeEach(() => vi.resetAllMocks())
describe('channel application review', () => {
  it('loads owner history lazily and does not offer review controls', async () => {
    workspaceRequest.mockResolvedValue({ count: 1, next: null, results: [{ id: 1, url: 'https://publisher.example/rss', url_safe: true, status: 'rejected', review_reason: '请使用官方 Feed', reviewed_at: null }] })
    mount()
    expect(workspaceRequest).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: '我的接入申请' }))
    expect(await screen.findByText('审核说明：请使用官方 Feed')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '批准受理' })).not.toBeInTheDocument()
  })
  it('requires an admin review reason and never implies activation', async () => {
    const item = { id: 1, url: 'https://publisher.example/rss', url_safe: true, status: 'pending', review_reason: '', reviewed_at: null }
    workspaceRequest.mockImplementation(async (_path, options = {}) => {
      if (options.method === 'POST') { item.status = options.body.decision; item.review_reason = options.body.reason; return item }
      return { count: 1, next: null, results: [{ ...item }] }
    })
    mount(true)
    fireEvent.click(screen.getByRole('button', { name: '审核频道接入申请' }))
    const approve = await screen.findByRole('button', { name: '批准受理' })
    expect(approve).toBeDisabled()
    fireEvent.change(screen.getByLabelText('审核说明'), { target: { value: '请登记经过许可的来源策略' } })
    fireEvent.click(approve)
    await waitFor(() => expect(workspaceRequest).toHaveBeenCalledWith('/admin/smart-channels/intake/1/', expect.objectContaining({ method: 'POST', body: { decision: 'approved', reason: '请登记经过许可的来源策略' } })))
    expect(await screen.findByText('已批准受理，尚未启用采集')).toBeInTheDocument()
  })
})
