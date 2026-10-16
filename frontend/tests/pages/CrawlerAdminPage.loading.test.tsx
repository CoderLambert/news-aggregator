import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import CrawlerAdminPage from '@/pages/admin/CrawlerAdminPage'
import { fetchCrawlerDashboard, fetchRecentCrawlBatches } from '@/services/crawlerAdminApi'

vi.mock('@/components/admin/AdminLayout', () => ({ default: ({ children }: { children: React.ReactNode }) => <>{children}</> }))
vi.mock('@/components/admin/ArticleFetchMonitorSection', () => ({ default: () => null }))
vi.mock('@/components/admin/SourceConfigSection', () => ({ default: () => null }))
vi.mock('@/context/AuthContext', () => ({ useAuth: () => ({ refresh: vi.fn() }) }))
vi.mock('@/services/searchIndexAdminApi', () => ({
  fetchSearchIndexDashboard: vi.fn().mockRejectedValue(new Error('fixture')),
  cancelSearchIndexRun: vi.fn(), createSearchIndexRun: vi.fn(), updateSearchIndexSettings: vi.fn(),
}))
vi.mock('@/services/crawlerAdminApi', () => ({
  CrawlerAdminApiError: class extends Error {},
  fetchCrawlerDashboard: vi.fn(), fetchRecentCrawlBatches: vi.fn(),
  fetchCrawlerReadiness: vi.fn().mockResolvedValue({ sources: [] }),
  cancelCrawlRun: vi.fn(), createCrawlBatch: vi.fn(), retryCrawlRun: vi.fn(),
  updateCrawlerSettings: vi.fn(), updateCrawlerTarget: vi.fn(),
}))

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(fetchCrawlerDashboard).mockResolvedValue({
    settings: { schedulerEnabled: true, intervalSeconds: 3600, workerOnline: true, updatedAt: '2026-10-16', runOnWorkerStart: false, nextRunAt: null, workerHeartbeatAt: null, workerInstanceId: '' },
    targets: [], recentBatches: [], activeRun: null, serverTime: '2026-10-16',
  })
  vi.mocked(fetchRecentCrawlBatches).mockResolvedValue([])
})

it('renders the dashboard without history and fetches history only when expanded', async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const view = render(<QueryClientProvider client={client}><CrawlerAdminPage /></QueryClientProvider>)
  await screen.findByRole('heading', { name: '来源管理' })
  expect(fetchRecentCrawlBatches).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: '查看最近抓取历史' }))
  await screen.findByText('暂无抓取历史。')
  expect(fetchRecentCrawlBatches).toHaveBeenCalledTimes(1)
  fireEvent.click(screen.getByRole('button', { name: '收起抓取历史' }))
  await client.invalidateQueries({ queryKey: ['crawlerAdmin', 'history'] })
  await waitFor(() => expect(screen.queryByText('暂无抓取历史。')).not.toBeInTheDocument())
  expect(fetchRecentCrawlBatches).toHaveBeenCalledTimes(1)
  view.unmount()
  client.clear()
})
