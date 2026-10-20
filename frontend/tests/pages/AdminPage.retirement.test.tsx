import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import AdminPage from '@/pages/admin/AdminPage'
import { workspaceRequest } from '@/services/workspaceApi'

vi.mock('@/context/AuthContext', () => ({ useAuth: () => ({ user: { id: 17, isSuperuser: true } }) }))
vi.mock('@/services/workspaceApi', () => ({
  workspaceError: (error: Error) => error.message,
  workspaceRequest: vi.fn((path: string) => Promise.resolve(path.includes('/health/') ? {
    engine_ready: true, initial_sync: false, last_successful_incremental: null,
    last_successful_full_reconcile: null, lag: null, error_class: null,
  } : { results: [] })),
}))
vi.mock('@/services/searchIndexAdminApi', () => ({
  fetchSearchIndexDashboard: vi.fn(() => new Promise(() => {})),
  cancelSearchIndexRun: vi.fn(), createSearchIndexRun: vi.fn(), updateSearchIndexSettings: vi.fn(),
}))

it('loads existing RSS status independently while the retained index section is pending', async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><AdminPage /></QueryClientProvider>)
  expect(screen.getByRole('heading', { name: 'RSS 与搜索管理' })).toBeInTheDocument()
  expect(screen.getByLabelText('正在加载搜索索引状态')).toBeInTheDocument()
  expect(await screen.findByText(/RSS 连接状态 · 引擎可用/)).toBeInTheDocument()
  expect(vi.mocked(workspaceRequest).mock.calls.map(([path]) => path).sort()).toEqual([
    '/admin/rss/health/', '/me/rss-subscriptions/',
  ])
  expect(screen.queryByText('全文监控')).not.toBeInTheDocument()
  expect(screen.queryByText('抓取历史')).not.toBeInTheDocument()
  client.clear()
})
