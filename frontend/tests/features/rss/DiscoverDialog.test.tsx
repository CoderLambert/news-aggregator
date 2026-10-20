import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ComponentProps } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import DiscoverDialog from '@/features/rss/DiscoverDialog'
import { workspaceRequest } from '@/services/workspaceApi'
vi.mock('@/services/workspaceApi', async importOriginal => ({ ...await importOriginal<typeof import('@/services/workspaceApi')>(), workspaceRequest: vi.fn(), workspaceError: () => '操作未完成，请重试。' }))
const request = vi.mocked(workspaceRequest)
beforeEach(() => {
  vi.clearAllMocks()
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', '') }
  HTMLDialogElement.prototype.close = function () { this.removeAttribute('open') }
})
afterEach(() => { cleanup(); vi.useRealTimers() })
function setup(props: Partial<ComponentProps<typeof DiscoverDialog>> = {}, client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })) {
  const view = (overrides: typeof props = {}) => <QueryClientProvider client={client}>
    <DiscoverDialog viewer={12} groups={[{ id: 7, name: 'Mine', source_ids: [] }]} onClose={vi.fn()} onDone={vi.fn()} {...props} {...overrides} />
  </QueryClientProvider>
  const result = render(view())
  return { ...result, rerenderDialog: (overrides: typeof props) => result.rerender(view(overrides)) }
}
function search(value: string) {
  fireEvent.change(screen.getByLabelText('搜索订阅源、网站或 RSS 地址'), { target: { value } })
  fireEvent.click(screen.getByRole('button', { name: '查找订阅' }))
}
function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(done => { resolve = done })
  return { promise, resolve }
}
const emptyDirectory = { results: [], next_cursor: null }
const discovered = { operation_id: 'discover', state: 'succeeded', candidates: [{ url: 'https://example.com/feed', title: 'Example feed', candidate_token: 'candidate' }] }
const saved = { operation_id: 'register', state: 'pending', subscription: { name: 'My feed' } }
const callsTo = (path: string) => request.mock.calls.filter(([requestedPath]) => requestedPath === path)

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
  it('normalizes a bare domain for the explicit fallback only after confirmation', async () => {
    request.mockImplementation(async path => path.startsWith('/rss/directory/') ? { results: [], next_cursor: null } :
      path === '/me/rss-subscriptions/' ? { operation_id: 'op', state: 'pending', subscription: { name: 'Feed' } } :
        { operation_id: 'discover', state: 'succeeded', candidates: [] })
    setup()
    fireEvent.change(screen.getByLabelText('搜索订阅源、网站或 RSS 地址'), { target: { value: 'example.com/writings' } })
    fireEvent.click(screen.getByRole('button', { name: '查找订阅' }))
    fireEvent.click(await screen.findByRole('button', { name: '尝试直接添加此 Feed' }))
    expect(request.mock.calls.some(([path]) => path === '/me/rss-subscriptions/')).toBe(false)
    fireEvent.click(screen.getByRole('button', { name: '确认订阅' }))
    await waitFor(() => expect(request).toHaveBeenCalledWith('/me/rss-subscriptions/',
      expect.objectContaining({ body: { feed_url: 'https://example.com/writings', group_ids: [] } })))
  })
  it('keeps unconfigured route templates non-executable', async () => {
    request.mockResolvedValue({ results: [{ id: 'route', name: 'Template', description: 'Needs account', kind: 'route_template', public_url: '', executable: false, subscribed: false, cached_articles: [] }], next_cursor: null })
    setup()
    expect(await screen.findByRole('radio')).toBeDisabled()
    expect(screen.getByRole('button', { name: '确认订阅' })).toBeDisabled()
  })

  it('reloads the failed directory search without discovering a website or writing subscriptions', async () => {
    let attempts = 0
    const retry = deferred<typeof emptyDirectory>()
    request.mockImplementation(async path => {
      if (path === '/rss/directory/?q=React') {
        if (++attempts === 1) throw new Error('offline')
        return retry.promise
      }
      return emptyDirectory
    })
    setup()
    search('React')
    fireEvent.click(await screen.findByRole('button', { name: '重新加载目录' }))
    expect(await screen.findByText('正在读取目录…')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '查找订阅' }))
    expect(callsTo('/rss/directory/?q=React')).toHaveLength(2)
    await act(async () => { retry.resolve(emptyDirectory) })
    expect(await screen.findByText('没有匹配的来源。可以尝试网站地址或直接添加 RSS。')).toBeInTheDocument()
    expect(callsTo('/rss/directory/?q=React')).toHaveLength(2)
    expect(callsTo('/rss/discovery/resolve/')).toHaveLength(0)
    expect(callsTo('/me/rss-subscriptions/')).toHaveLength(0)
  })

  it('retries a failed discovery POST from the keyboard with the same address and viewer', async () => {
    const user = userEvent.setup()
    let attempts = 0
    request.mockImplementation(async path => {
      if (path === '/rss/discovery/resolve/') {
        if (++attempts === 1) throw new Error('offline')
        return discovered
      }
      return emptyDirectory
    })
    setup()
    search('example.com')
    const retry = await screen.findByRole('button', { name: '重新查找订阅' })
    retry.focus()
    await user.keyboard('{Enter}')
    expect(await screen.findByText('Example feed')).toBeInTheDocument()
    expect(callsTo('/rss/discovery/resolve/')).toHaveLength(2)
    expect(callsTo('/rss/discovery/resolve/').map(([, options]) => options)).toEqual([
      { method: 'POST', viewer: 12, body: { input: 'example.com' } },
      { method: 'POST', viewer: 12, body: { input: 'example.com' } },
    ])
    expect(screen.getByRole('button', { name: '确认订阅' })).toBeDisabled()
    expect(callsTo('/me/rss-subscriptions/')).toHaveLength(0)
  })

  it('pauses failed discovery polling and recovers only its GET, without a second resolve POST', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
    let attempts = 0
    request.mockImplementation(async path => {
      if (path === '/rss/discovery/resolve/') return { operation_id: 'discover', state: 'pending' }
      if (path === '/me/rss-operations/discover/') {
        if (++attempts === 1) throw new Error('offline')
        return { state: 'succeeded', result: discovered }
      }
      return emptyDirectory
    })
    setup()
    search('example.com')
    const retry = await screen.findByRole('button', { name: '重新读取发现结果' })
    await act(async () => { await vi.advanceTimersByTimeAsync(6000) })
    expect(callsTo('/me/rss-operations/discover/')).toHaveLength(1)
    expect(screen.queryByText('后台正在发现订阅…可以关闭窗口后重新查询此地址。')).not.toBeInTheDocument()
    fireEvent.click(retry)
    expect(await screen.findByText('Example feed')).toBeInTheDocument()
    await act(async () => { await vi.advanceTimersByTimeAsync(6000) })
    expect(callsTo('/me/rss-operations/discover/')).toHaveLength(2)
    expect(callsTo('/rss/discovery/resolve/')).toHaveLength(1)
    expect(callsTo('/me/rss-subscriptions/')).toHaveLength(0)
  })

  it.each([
    ['failed', true, true], ['failed', false, false], ['manual_blocked', true, false], ['cancelled', true, false],
  ])('offers explicit discovery retry for state=%s retryable=%s only when allowed', async (state, retryable, allowed) => {
    let attempts = 0
    request.mockImplementation(async path => path === '/rss/discovery/resolve/'
      ? ++attempts === 1 ? { operation_id: 'discover', state, retryable, error_code: 'engine_unavailable' } : discovered
      : emptyDirectory)
    setup()
    search('example.com')
    expect(await screen.findByRole('alert')).toHaveTextContent('发现未完成')
    expect(callsTo('/rss/discovery/resolve/')).toHaveLength(1)
    if (allowed) {
      fireEvent.click(screen.getByRole('button', { name: '重新查找订阅' }))
      expect(await screen.findByText('Example feed')).toBeInTheDocument()
      expect(callsTo('/rss/discovery/resolve/')).toHaveLength(2)
    } else expect(screen.queryByRole('button', { name: '重新查找订阅' })).not.toBeInTheDocument()
    expect(callsTo('/me/rss-subscriptions/')).toHaveLength(0)
  })

  it('retries an unconfirmed save with the exact request and idempotency key without implicit mutation retries', async () => {
    let attempts = 0
    const retry = deferred<typeof saved>()
    request.mockImplementation(async path => {
      if (path === '/me/rss-subscriptions/') {
        if (++attempts === 1) throw new Error('response lost')
        return retry.promise
      }
      return path.startsWith('/rss/directory/') ? emptyDirectory : { state: 'succeeded', result: {} }
    })
    // The dialog must keep writes explicit even when the app enables retries.
    const client = new QueryClient({ defaultOptions: { mutations: { retry: 2, retryDelay: 0 } } })
    setup({}, client)
    search('https://example.com/feed')
    fireEvent.click(screen.getByRole('checkbox', { name: 'Mine' }))
    fireEvent.click(screen.getByRole('button', { name: '确认订阅' }))
    const retryButton = await screen.findByRole('button', { name: '重试保存订阅' })
    expect(callsTo('/me/rss-subscriptions/')).toHaveLength(1)
    fireEvent.click(retryButton)
    await waitFor(() => expect(screen.getByRole('button', { name: '保存中…' })).toBeDisabled())
    expect(screen.getByRole('checkbox', { name: 'Mine' })).toBeDisabled()
    expect(callsTo('/me/rss-subscriptions/')).toHaveLength(2)
    const original = callsTo('/me/rss-subscriptions/')[0][1]
    expect(original).toEqual({ method: 'POST', viewer: 12, idempotencyKey: expect.any(String), body: { feed_url: 'https://example.com/feed', group_ids: [7] } })
    expect(callsTo('/me/rss-subscriptions/')[1][1]).toEqual(original)
    await act(async () => { retry.resolve(saved) })
    expect(await screen.findByText('来源已连接，首次文章同步将在后台完成。')).toBeInTheDocument()
    expect(callsTo('/rss/discovery/resolve/')).toHaveLength(0)
  })

  it('discards a failed save intent and uses a new key when the chosen groups change', async () => {
    request.mockImplementation(async path => {
      if (path === '/me/rss-subscriptions/') throw new Error('offline')
      return emptyDirectory
    })
    setup()
    search('https://example.com/feed')
    fireEvent.click(screen.getByRole('checkbox', { name: 'Mine' }))
    fireEvent.click(screen.getByRole('button', { name: '确认订阅' }))
    await screen.findByRole('button', { name: '重试保存订阅' })
    fireEvent.click(screen.getByRole('checkbox', { name: 'Mine' }))
    expect(screen.queryByRole('button', { name: '重试保存订阅' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '确认订阅' }))
    await screen.findByRole('button', { name: '重试保存订阅' })
    const [first, second] = callsTo('/me/rss-subscriptions/').map(([, options]) => options)
    expect(second?.idempotencyKey).not.toBe(first?.idempotencyKey)
    expect(second?.body).toEqual({ feed_url: 'https://example.com/feed', group_ids: [] })
  })

  it('clears an old discovery failure when the user searches a new keyword', async () => {
    request.mockImplementation(async path => {
      if (path === '/rss/discovery/resolve/') throw new Error('offline')
      return emptyDirectory
    })
    setup()
    search('example.com')
    await screen.findByRole('button', { name: '重新查找订阅' })
    search('React')
    expect(await screen.findByText('没有匹配的来源。可以尝试网站地址或直接添加 RSS。')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(callsTo('/rss/discovery/resolve/')).toHaveLength(1)
    expect(callsTo('/rss/directory/?q=React')).toHaveLength(1)
  })

  it('recovers a saved subscription status through GET only and stops polling while offline or terminal', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
    let attempts = 0
    request.mockImplementation(async path => {
      if (path === '/me/rss-subscriptions/') return saved
      if (path === '/me/rss-operations/register/') {
        if (++attempts === 1) throw new Error('offline')
        return { state: 'succeeded', result: {} }
      }
      return emptyDirectory
    })
    setup()
    search('https://example.com/feed')
    fireEvent.click(screen.getByRole('button', { name: '确认订阅' }))
    const retry = await screen.findByRole('button', { name: '重新读取连接状态' })
    expect(screen.getByText('已订阅：My feed')).toBeInTheDocument()
    expect(screen.getByText('暂时无法读取连接状态，请稍后核对。')).toBeInTheDocument()
    expect(screen.queryByText('来源已连接，首次文章同步将在后台完成。')).not.toBeInTheDocument()
    await act(async () => { await vi.advanceTimersByTimeAsync(6000) })
    expect(callsTo('/me/rss-operations/register/')).toHaveLength(1)
    fireEvent.click(retry)
    expect(await screen.findByText('来源已连接，首次文章同步将在后台完成。')).toBeInTheDocument()
    await act(async () => { await vi.advanceTimersByTimeAsync(6000) })
    expect(callsTo('/me/rss-operations/register/')).toHaveLength(2)
    expect(callsTo('/me/rss-subscriptions/')).toHaveLength(1)
    expect(callsTo('/rss/directory/?q=')).toHaveLength(1)
    expect(callsTo('/rss/discovery/resolve/')).toHaveLength(0)
  })

  it('does not replay a failed save after closing and reopening the dialog', async () => {
    request.mockImplementation(async path => {
      if (path === '/me/rss-subscriptions/') throw new Error('response lost')
      return emptyDirectory
    })
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    const close = vi.fn()
    const first = setup({ onClose: close }, client)
    search('https://example.com/feed')
    fireEvent.click(screen.getByRole('button', { name: '确认订阅' }))
    await screen.findByRole('button', { name: '重试保存订阅' })
    fireEvent.click(screen.getByRole('button', { name: '取消' }))
    expect(close).toHaveBeenCalledOnce()
    first.unmount()
    setup({}, client)
    expect(screen.getByLabelText('搜索订阅源、网站或 RSS 地址')).toHaveValue('')
    expect(screen.queryByRole('button', { name: '重试保存订阅' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '确认订阅' })).toBeDisabled()
    await waitFor(() => expect(callsTo('/rss/directory/?q=')).toHaveLength(2))
    expect(callsTo('/me/rss-subscriptions/')).toHaveLength(1)
  })

  it('discards a failed account intent when viewer changes, including its groups and recovery button', async () => {
    request.mockImplementation(async path => {
      if (path === '/me/rss-subscriptions/') throw new Error('response lost')
      return emptyDirectory
    })
    const view = setup()
    search('https://example.com/feed')
    fireEvent.click(screen.getByRole('checkbox', { name: 'Mine' }))
    fireEvent.click(screen.getByRole('button', { name: '确认订阅' }))
    await screen.findByRole('button', { name: '重试保存订阅' })
    view.rerenderDialog({ viewer: 23, groups: [{ id: 9, name: 'Other account', source_ids: [] }] })
    expect(screen.getByLabelText('搜索订阅源、网站或 RSS 地址')).toHaveValue('')
    expect(screen.queryByRole('button', { name: '重试保存订阅' })).not.toBeInTheDocument()
    expect(screen.queryByRole('checkbox', { name: 'Mine' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '确认订阅' })).toBeDisabled()
    await waitFor(() => expect(callsTo('/rss/directory/?q=')).toHaveLength(2))
    expect(callsTo('/me/rss-subscriptions/')).toHaveLength(1)
    search('https://other.example/feed')
    fireEvent.click(screen.getByRole('checkbox', { name: 'Other account' }))
    fireEvent.click(screen.getByRole('button', { name: '确认订阅' }))
    await screen.findByRole('button', { name: '重试保存订阅' })
    expect(callsTo('/me/rss-subscriptions/')[1][1]).toEqual({ method: 'POST', viewer: 23, idempotencyKey: expect.any(String), body: { feed_url: 'https://other.example/feed', group_ids: [9] } })
    expect(callsTo('/me/rss-subscriptions/')[1][1]?.idempotencyKey).not.toBe(callsTo('/me/rss-subscriptions/')[0][1]?.idempotencyKey)
  })

  it('ignores a late save response from a previous viewer and does not poll that operation', async () => {
    const pending = deferred<typeof saved>()
    request.mockImplementation(async path => path === '/me/rss-subscriptions/' ? pending.promise : emptyDirectory)
    const view = setup()
    search('https://example.com/feed')
    fireEvent.click(screen.getByRole('button', { name: '确认订阅' }))
    await waitFor(() => expect(callsTo('/me/rss-subscriptions/')).toHaveLength(1))
    view.rerenderDialog({ viewer: 23, groups: [] })
    await act(async () => { pending.resolve(saved) })
    expect(screen.queryByText('已订阅：My feed')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '确认订阅' })).toBeDisabled()
    expect(callsTo('/me/rss-operations/register/')).toHaveLength(0)
    expect(callsTo('/me/rss-subscriptions/')).toHaveLength(1)
  })
})


it('recognizes rsshub aliases and refreshes viewer home queries after connection', async () => {
  request.mockImplementation(async path => path.startsWith('/rss/directory/') ? {results:[],next_cursor:null} : path === '/categories/' ? [{id:3,name:'人工智能'}] : path === '/me/rss-subscriptions/' ? {operation_id:'hub-op',state:'pending',subscription:null} : {state:'succeeded',result:{}})
  const client=new QueryClient({defaultOptions:{queries:{retry:false},mutations:{retry:false}}})
  const invalidate=vi.spyOn(client,'invalidateQueries')
  setup({},client)
  search('rsshub://twitter/user/elonmusk')
  expect(await screen.findByText(/已识别为 RSSHub/)).toBeInTheDocument()
  await screen.findByRole('option',{name:'人工智能'})
  fireEvent.change(await screen.findByRole('combobox',{name:'频道分类（用于首页筛选）'}),{target:{value:'3'}})
  fireEvent.click(screen.getByRole('button',{name:'确认订阅'}))
  await waitFor(()=>expect(request).toHaveBeenCalledWith('/me/rss-subscriptions/',expect.objectContaining({body:{feed_url:'rsshub://twitter/user/elonmusk',group_ids:[],category_id:3}})))
  await screen.findByText('来源已连接，首次文章同步将在后台完成。')
  await waitFor(()=>expect(invalidate.mock.calls.some(([options])=>JSON.stringify(options?.queryKey).includes('sources'))).toBe(true))
  expect(invalidate.mock.calls.some(([options])=>JSON.stringify(options?.queryKey).includes('viewerId'))).toBe(true)
})
it('uses server selection for a configured HTTPS RSSHub gateway without discovery credentials', async () => {
  request.mockImplementation(async path => path.startsWith('/rss/directory/') ? {results:[],next_cursor:null} : path === '/rss/discovery/resolve/' ? {state:'succeeded',operation_id:'',kind:'feed',feed_url:'rsshub://twitter/user/elonmusk'} : path === '/categories/' ? [] : {state:'succeeded',result:{}})
  setup()
  search('https://feeds.example.com/twitter/user/elonmusk')
  expect(await screen.findByText(/已识别为 RSSHub/)).toBeInTheDocument()
  expect(screen.getByRole('button',{name:'确认订阅'})).toBeEnabled()
  expect(request.mock.calls.some(([path])=>path.startsWith('/me/rss-operations/'))).toBe(false)
})
