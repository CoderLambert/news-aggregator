import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import DiscoverDialog from '@/features/rss/DiscoverDialog'
import { workspaceRequest } from '@/services/workspaceApi'
vi.mock('@/services/workspaceApi', () => ({ workspaceRequest: vi.fn(), workspaceError: () => '操作未完成，请重试。' }))
const request = vi.mocked(workspaceRequest)
beforeEach(() => {
  vi.clearAllMocks()
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', '') }
  HTMLDialogElement.prototype.close = function () { this.removeAttribute('open') }
})
afterEach(cleanup)
function setup() { return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}>
  <DiscoverDialog viewer={12} groups={[{ id: 7, name: 'Mine', source_ids: [] }]} onClose={vi.fn()} onDone={vi.fn()} />
</QueryClientProvider>) }

describe('RSS discovery and subscription', () => {
  it.each([0, 1, 3])('shows %i real candidates and never auto-subscribes', async count => {
    request.mockImplementation(async path => path.startsWith('/rss/directory/') ? { results: [], next_cursor: null } :
      { operation_id: 'discover', state: 'succeeded', candidates: Array.from({ length: count }, (_, i) => ({ url: `https://example.com/${i}`, title: `Feed ${i}`, candidate_token: `token-${i}` })) })
    setup()
    fireEvent.change(screen.getByLabelText('搜索订阅源、网站或 RSS 地址'), { target: { value: 'example.com' } })
    fireEvent.click(screen.getByRole('button', { name: '查找订阅' }))
    if (!count) expect(await screen.findByText('未发现网站声明的订阅源。可以粘贴网站公布的 RSS 地址，或明确尝试将此地址作为 Feed 添加。')).toBeInTheDocument()
    else expect(await screen.findAllByRole('radio')).toHaveLength(count)
    expect(screen.getByRole('button', { name: '确认订阅' })).toBeDisabled()
    expect(request.mock.calls.every(([path]) => path !== '/me/rss-subscriptions/')).toBe(true)
  })
  it('sends a direct URL through the ordinary subscription service with viewer, groups and an idempotency key', async () => {
    request.mockImplementation(async path => path.startsWith('/rss/directory/') ? { results: [], next_cursor: null } : path === '/me/rss-subscriptions/' ?
      { operation_id: 'register', state: 'pending', subscription: { name: 'My feed' } } : { state: 'succeeded', result: {} })
    setup()
    fireEvent.change(screen.getByLabelText('搜索订阅源、网站或 RSS 地址'), { target: { value: 'https://example.com/feed' } })
    fireEvent.click(screen.getByRole('button', { name: '查找订阅' }))
    fireEvent.click(screen.getByRole('checkbox', { name: 'Mine' }))
    fireEvent.click(screen.getByRole('button', { name: '确认订阅' }))
    await waitFor(() => expect(request).toHaveBeenCalledWith('/me/rss-subscriptions/', expect.objectContaining({ viewer: 12, idempotencyKey: expect.any(String), body: { feed_url: 'https://example.com/feed', group_ids: [7] } })))
    expect(await screen.findByText('来源已连接，首次文章同步将在后台完成。')).toBeInTheDocument()
  })
  it('searches the shared directory by keyword without contacting a publisher or subscribing', async () => {
    request.mockImplementation(async path => path.startsWith('/rss/directory/') ? {
      results: [{ id: 'github-feed', name: 'GitHub Blog', description: 'Engineering', kind: 'feed',
        public_url: 'https://github.blog/feed/', executable: true, subscribed: false, cached_articles: [] }],
      next_cursor: null,
    } : { state: 'failed' })
    setup()
    fireEvent.change(screen.getByLabelText('搜索订阅源、网站或 RSS 地址'), { target: { value: 'github' } })
    fireEvent.click(screen.getByRole('button', { name: '查找订阅' }))
    expect(await screen.findByText('GitHub Blog')).toBeInTheDocument()
    expect(request.mock.calls.some(([path]) => path === '/rss/directory/?q=github')).toBe(true)
    expect(request.mock.calls.every(([path]) => path !== '/rss/discovery/resolve/' && path !== '/me/rss-subscriptions/')).toBe(true)
  })
  it('offers a deliberate direct-feed fallback after zero website candidates, without auto-subscribing', async () => {
    request.mockImplementation(async path => path.startsWith('/rss/directory/') ? { results: [], next_cursor: null } :
      { operation_id: 'discover', state: 'succeeded', candidates: [] })
    setup()
    fireEvent.change(screen.getByLabelText('搜索订阅源、网站或 RSS 地址'), { target: { value: 'https://example.com/writings' } })
    fireEvent.click(screen.getByRole('button', { name: '查找订阅' }))
    fireEvent.click(await screen.findByRole('button', { name: '尝试直接添加此 Feed' }))
    expect(screen.getByRole('button', { name: '确认订阅' })).toBeEnabled()
    expect(request.mock.calls.every(([path]) => path !== '/me/rss-subscriptions/')).toBe(true)
  })
  it('keeps unconfigured route templates non-executable', async () => {
    request.mockResolvedValue({ results: [{ id: 'route', name: 'Template', description: 'Needs account', kind: 'route_template', public_url: '', executable: false, subscribed: false, cached_articles: [] }], next_cursor: null })
    setup()
    expect(await screen.findByRole('radio')).toBeDisabled()
    expect(screen.getByRole('button', { name: '确认订阅' })).toBeDisabled()
  })
})
