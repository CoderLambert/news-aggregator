import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { cleanup, render, screen, waitFor, act } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import RssRecommendationsPage from '@/pages/admin/RssRecommendationsPage'
import { workspaceRequest } from '@/services/workspaceApi'
const auth = vi.hoisted(() => ({ user: { id: 17, isSuperuser: false, rssCapabilities: { reviewPublicRss: true, manageReviewers: false, reviewerVersion: 1 } }, refresh: vi.fn() }))
vi.mock('@/context/AuthContext', () => ({ useAuth: () => auth }))
vi.mock('@/services/workspaceApi', async importOriginal => ({ ...await importOriginal<typeof import('@/services/workspaceApi')>(), workspaceRequest: vi.fn(), workspaceError: () => '请求失败' }))
const row = { candidate_id: 'candidate', name: 'Public recommendation', feed_url: 'https://example.com/feed', category_id: 1, category_name: '科技', language: 'en', version: 1, state: 'pending', connection_state: 'ready', public_source_id: null, scope_description: '公开范围', can_review: false, can_verify: false, reason: '', error_code: '', member_sync_complete: false, created_at: new Date().toISOString() }
let client: QueryClient
beforeEach(() => {
  vi.clearAllMocks(); client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  vi.mocked(workspaceRequest).mockResolvedValue({ results: [row], count: 1, counts: { pending: 1 }, page: 1, page_size: 25 })
})
afterEach(() => { cleanup(); client.clear() })
it('reviewer sees public queue without engine, role-management or self-approval controls', async () => {
  render(<QueryClientProvider client={client}><MemoryRouter><RssRecommendationsPage /></MemoryRouter></QueryClientProvider>)
  expect(await screen.findByText('Public recommendation')).toBeInTheDocument()
  expect(screen.queryByRole('link', { name: '运行概览' })).not.toBeInTheDocument()
  expect(screen.queryByRole('link', { name: '频道审核员' })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: '通过审核' })).not.toBeInTheDocument()
})

it('hides cached review data when the server revokes authority', async () => {
  render(<QueryClientProvider client={client}><MemoryRouter><RssRecommendationsPage /></MemoryRouter></QueryClientProvider>)
  await screen.findByText('Public recommendation')
  vi.mocked(workspaceRequest).mockRejectedValue(Object.assign(new Error('revoked'), { status: 403 }))
  await act(async () => { await client.invalidateQueries() })
  await waitFor(() => expect(screen.queryByText('Public recommendation')).not.toBeInTheDocument())
  expect(auth.refresh).toHaveBeenCalled()
})
it('refreshes home when a pending recommendation leaves the filtered queue', async () => {
  const invalidate=vi.spyOn(client,'invalidateQueries')
  render(<QueryClientProvider client={client}><MemoryRouter><RssRecommendationsPage /></MemoryRouter></QueryClientProvider>)
  await screen.findByText('Public recommendation')
  const query=client.getQueryCache().findAll().find(item=>item.queryKey.includes('queue'))!
  await act(async()=>{client.setQueryData(query.queryKey,{results:[],count:0,counts:{pending:0,published:1},page:1,page_size:25})})
  await waitFor(()=>expect(invalidate.mock.calls.some(([options])=>JSON.stringify(options?.queryKey).includes('sources'))).toBe(true))
})
