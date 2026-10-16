import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import ConnectionStatus from '@/features/rss/ConnectionStatus'
import { workspaceRequest } from '@/services/workspaceApi'

vi.mock('@/services/workspaceApi', () => ({ workspaceRequest: vi.fn(), workspaceError: () => '加载失败' }))
afterEach(() => { cleanup(); vi.clearAllMocks() })
const request = vi.mocked(workspaceRequest)
function setup(admin = false) {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <ConnectionStatus viewer={12} admin={admin} />
  </QueryClientProvider>)
}
it('shows connection completion without claiming article synchronization and never requests admin health for a reader', async () => {
  request.mockResolvedValue({ results: [{ id: 1, name: 'My feed', feeds: [{ id: 'feed', connection_state: 'ready', desired_mode: 'full_content' }] }] })
  setup()
  expect(await screen.findByText('My feed')).toBeInTheDocument()
  expect(screen.getByText(/来源已连接/)).toBeInTheDocument()
  expect(screen.getByText(/文章同步由后台继续完成/)).toBeInTheDocument()
  expect(request.mock.calls.map(call => call[0])).toEqual(['/me/rss-subscriptions/'])
})
it('keeps unknown health separate from completed synchronization', async () => {
  request.mockImplementation(async path => (path.includes('/health/') ? {
    engine_ready: false, initial_sync: true, lag: null, last_successful_incremental: null,
    last_successful_full_reconcile: null, error_class: 'network',
  } : { results: [] }) as never)
  setup(true)
  await waitFor(() => expect(screen.getByText(/引擎状态待确认/)).toBeInTheDocument())
  expect(screen.getByText('尚未完成')).toBeInTheDocument()
  expect(screen.getByText(/不等于待处理文章数量/)).toHaveTextContent('未知')
  expect(screen.getByText('network')).toBeInTheDocument()
})
