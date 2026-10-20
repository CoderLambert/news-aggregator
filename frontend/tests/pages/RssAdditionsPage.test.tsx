import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import RssAdditionsPage from '@/pages/RssAdditionsPage'
import { workspaceRequest } from '@/services/workspaceApi'
const auth = vi.hoisted(() => ({ user: { id: 17, isSuperuser: false } }))
vi.mock('@/context/AuthContext', () => ({ useAuth: () => auth }))
vi.mock('@/services/workspaceApi', async importOriginal => ({ ...await importOriginal<typeof import('@/services/workspaceApi')>(), workspaceRequest: vi.fn(), workspaceError: () => '请求未完成' }))
const request = vi.mocked(workspaceRequest)
const row = { operation_id: 'op', source_id: 1, name: 'https://example.com/feed', feed_url: 'https://example.com/feed', state: 'unknown', version: 1, actions: ['reconcile', 'cancel'], error_code: 'create_unknown', cooldown_until: new Date(0).toISOString(), connection_state: 'unknown', created_at: new Date().toISOString(), recovery_of: null }
let client: QueryClient
beforeEach(() => {
  vi.clearAllMocks(); auth.user = { id: 17, isSuperuser: false }
  client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  request.mockImplementation(async path => path.startsWith('/me/rss-additions/') ? { results: [row], count: 1, page: 1, page_size: 25 } : { results: [], count: 0, page: 1, page_size: 25 })
})
afterEach(() => { cleanup(); client.clear() })
function view() { return <QueryClientProvider client={client}><MemoryRouter><RssAdditionsPage /></MemoryRouter></QueryClientProvider> }
it('shows durable unknown additions with reconcile and cancel, never blind retry', async () => {
  render(view())
  expect(await screen.findByText('https://example.com/feed')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: '核对连接结果' })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: '重新连接' })).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: '核对连接结果' }))
  await waitFor(() => expect(request).toHaveBeenCalledWith('/me/rss-additions/op/actions/', expect.objectContaining({ viewer: 17, body: { action: 'reconcile', expected_version: 1 }, idempotencyKey: expect.any(String) })))
})
it('clears personal rows immediately on account change', async () => {
  const result = render(view())
  await screen.findByText('https://example.com/feed')
  auth.user = { id: 18, isSuperuser: false }
  request.mockResolvedValue({ results: [], count: 0, page: 1, page_size: 25 })
  result.rerender(view())
  await waitFor(() => expect(screen.queryByText('https://example.com/feed')).not.toBeInTheDocument())
})
it('distinguishes connected feeds with readable articles from pending article sync', async () => {
  request.mockResolvedValue({ results: [{ ...row, state: 'succeeded', actions: [], article_count: 2, article_state: 'ready' }], count: 1, page: 1, page_size: 25 })
  render(view())
  expect(await screen.findByText(/已有 2 篇文章可阅读/)).toBeInTheDocument()
  expect(screen.queryByText(/文章将在后台同步/)).not.toBeInTheDocument()
})
it('invalidates viewer home sources when polling observes newly readable articles', async () => {
  const invalidate=vi.spyOn(QueryClient.prototype,'invalidateQueries')
  request.mockResolvedValue({results:[{...row,state:'succeeded',actions:[],article_count:1,article_state:'ready'}],count:1,page:1,page_size:25})
  render(view())
  await screen.findByText(/已有 1 篇文章可阅读/)
  await waitFor(()=>expect(invalidate.mock.calls.some(([options])=>JSON.stringify(options?.queryKey).includes('sources'))).toBe(true))
  invalidate.mockRestore()
})
it('refreshes home when a pending addition disappears from the filtered list', async () => {
  request.mockResolvedValue({results:[{...row,state:'pending',actions:['cancel']}],count:1,page:1,page_size:25})
  const invalidate=vi.spyOn(client,'invalidateQueries')
  render(view());await screen.findByText('https://example.com/feed')
  const query=client.getQueryCache().findAll().find(item=>item.queryKey.includes('additions'))!
  await import('@testing-library/react').then(({act})=>act(async()=>{client.setQueryData(query.queryKey,{results:[],count:0,page:1,page_size:25})}))
  await waitFor(()=>expect(invalidate.mock.calls.some(([options])=>JSON.stringify(options?.queryKey).includes('sources'))).toBe(true))
})
it('explains a nonexistent RSSHub route as a source failure after admission', async () => {
  request.mockResolvedValue({results:[{...row,name:'rsshub://route-not-present',feed_url:'rsshub://route-not-present',state:'failed',actions:['retry'],error_code:'feed_source_not_found'}],count:1,page:1,page_size:25})
  render(view())
  expect(await screen.findByText(/路由不存在或源站返回 404/)).toBeInTheDocument()
  expect(screen.getByRole('button',{name:'重新连接'})).toBeInTheDocument()
})
