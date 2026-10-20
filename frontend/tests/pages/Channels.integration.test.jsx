import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AuthContext } from '@/context/AuthContext'
import { CapabilitiesTestProvider, readOnlyCapabilities } from '../helpers/capabilities'
import NewsList from '@/pages/NewsList'
import ChannelsPage from '@/pages/ChannelsPage'
import * as api from '@/services/api'

vi.mock('@/services/api', () => ({
  fetchSources: vi.fn(), fetchCategories: vi.fn(), fetchNews: vi.fn(), fetchNewsDetail: vi.fn(),
  fetchChannelSubscriptions: vi.fn(), fetchChannelGroups: vi.fn(), fetchNewsPreferences: vi.fn(),
  saveNewsPreferences: vi.fn(), changeChannelSubscriptions: vi.fn(), createChannelGroup: vi.fn(),
  updateChannelGroup: vi.fn(), deleteChannelGroup: vi.fn(),
}))
const channels = [
  { id: 1, name: 'OpenAI Blog', language: 'en', source_type: 'news', description: 'AI research', subscription_status: 'active', news_count: 1 },
  { id: 2, name: 'DeepMind', language: 'en', source_type: 'news', description: 'Research', subscription_status: 'active', news_count: 0 },
  { id: 3, name: 'WebKit', language: 'en', source_type: 'news', description: 'Web', subscription_status: 'active', news_count: 1 },
  { id: 4, name: 'Reuters', language: 'en', source_type: 'news', description: '', subscription_status: 'inactive', news_count: 1 },
]
const story = (id, title) => ({ id, title, content: 'Summary', title_zh: '', content_zh: '', source: id,
  source_name: channels.find(c => c.id === id)?.name ?? 'Source', category: 8, category_name: '科技',
  publish_time: '2026-10-13T10:00:00Z', url: `https://example.com/${id}` })
const page = (...stories) => ({ count: stories.length, next: null, previous: null, results: stories })
const deferred = () => { let resolve; let reject; const promise = new Promise((a, b) => { resolve = a; reject = b }); return { resolve, reject, promise } }
function NavigationProbe() {
  const location = useLocation(); const navigate = useNavigate()
  return <><output data-testid="url">{location.search}</output><button onClick={() => navigate(-1)}>back</button><button onClick={() => navigate(1)}>forward</button></>
}
function setup(element, url = '/', { user = { id: 71, username: 'channel-reader' }, capabilities } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  render(<QueryClientProvider client={client}><CapabilitiesTestProvider client={client} value={capabilities}>
    <AuthContext.Provider value={{ user, loading: false, login: vi.fn(), register: vi.fn(), logout: vi.fn(), refresh: vi.fn() }}>
      <MemoryRouter initialEntries={[url]}>{element}<NavigationProbe /></MemoryRouter>
    </AuthContext.Provider>
  </CapabilitiesTestProvider></QueryClientProvider>)
  return client
}
let subscriptions, groups
beforeEach(() => {
  vi.clearAllMocks()
  subscriptions = [{ id: 10, source_id: 1, group_ids: [11] }, { id: 12, source_id: 3, group_ids: [] }]
  groups = [{ id: 11, name: 'AI', source_ids: [1] }, { id: 13, name: '前端', source_ids: [3] }, { id: 14, name: '空分组', source_ids: [] }]
  api.fetchSources.mockResolvedValue(channels.map(channel => ({ ...channel, region: 'international' })))
  api.fetchCategories.mockResolvedValue([{ id: 8, name: '科技' }])
  api.fetchChannelSubscriptions.mockImplementation(async () => subscriptions)
  api.fetchChannelGroups.mockImplementation(async () => groups)
  api.fetchNewsPreferences.mockResolvedValue({ scope: 'all', group_id: null })
  api.saveNewsPreferences.mockImplementation(async value => value)
  api.fetchNews.mockResolvedValue(page())
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', { configurable: true, value: function () { this.setAttribute('open', '') } })
  Object.defineProperty(HTMLDialogElement.prototype, 'close', { configurable: true, value: function () { this.removeAttribute('open') } })
})
afterEach(() => vi.restoreAllMocks())

describe('personal reading scopes', () => {
  it('restores the account preference before fetching articles; explicit URL wins', async () => {
    api.fetchNewsPreferences.mockResolvedValue({ scope: 'group', group_id: 11 })
    setup(<NewsList />, '/?search=learning&category=8')
    await waitFor(() => expect(api.fetchNews).toHaveBeenCalledWith(expect.objectContaining({ scope: 'group', group_id: 11, search: 'learning', category: '8' }), expect.any(AbortSignal)))
    expect(api.fetchNews.mock.calls.every(([params]) => params.scope === 'group')).toBe(true)
    expect(screen.getByTestId('url')).toHaveTextContent('scope=group')
  })
  it('keeps search/category, clears temporary sources and pagination, and supports history and mobile selection', async () => {
    api.fetchNewsPreferences.mockResolvedValue({ scope: 'group', group_id: 13 })
    setup(<NewsList />, '/?scope=group&group_id=11&search=ai&category=8&source=1&page=2')
    await waitFor(() => expect(api.fetchNews).toHaveBeenCalledWith(expect.objectContaining({ group_id: 11 }), expect.any(AbortSignal)))
    fireEvent.click(screen.getByRole('button', { name: '前端', exact: true }))
    await waitFor(() => expect(api.fetchNews).toHaveBeenLastCalledWith(expect.objectContaining({ scope: 'group', group_id: 13, search: 'ai', category: '8', page: 1 }), expect.any(AbortSignal)))
    expect(screen.getByTestId('url')).not.toHaveTextContent('source=')
    fireEvent.click(screen.getByRole('button', { name: 'back', exact: true }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'AI', exact: true })).toHaveAttribute('aria-pressed', 'true'))
    fireEvent.click(screen.getByRole('button', { name: 'forward', exact: true }))
    await waitFor(() => expect(screen.getByRole('combobox', { name: '查看范围' })).toHaveValue('group:13'))
    fireEvent.change(screen.getByRole('combobox', { name: '查看范围' }), { target: { value: 'ungrouped' } })
    await waitFor(() => expect(api.fetchNews).toHaveBeenLastCalledWith(expect.objectContaining({ scope: 'ungrouped', search: 'ai', category: '8', page: 1 }), expect.any(AbortSignal)))
    fireEvent.click(screen.getByRole('button', { name: '筛选，已选 1 个条件' }))
    const sources = screen.getByRole('group', { name: '来源' })
    expect(within(sources).getByRole('button', { name: 'WebKit' })).toBeInTheDocument()
    expect(within(sources).queryByRole('button', { name: 'OpenAI Blog' })).toBeNull()
    fireEvent.click(within(screen.getByRole('region', { name: '新闻筛选' })).getByRole('button', { name: '清除分类与来源' }))
    await waitFor(() => expect(screen.getByTestId('url')).not.toHaveTextContent('category='))
    expect(screen.getByTestId('url')).toHaveTextContent('search=ai')
    expect(screen.getByTestId('url')).toHaveTextContent('scope=ungrouped')
  })
  it('aborts the previous request and clears its articles when switching quickly', async () => {
    const pending = deferred()
    api.fetchNews.mockImplementation((params) => params.group_id === 13 ? pending.promise : Promise.resolve(page(story(1, 'AI article'))))
    setup(<NewsList />, '/?scope=group&group_id=11')
    expect(await screen.findByRole('heading', { name: 'AI article' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '前端', exact: true }))
    await waitFor(() => expect(api.fetchNews).toHaveBeenCalledWith(expect.objectContaining({ group_id: 13 }), expect.any(AbortSignal)))
    expect(screen.queryByRole('heading', { name: 'AI article' })).toBeNull()
    const oldSignal = api.fetchNews.mock.calls.find(([p]) => p.group_id === 13)[1]
    fireEvent.click(screen.getByRole('button', { name: '空分组', exact: true }))
    await waitFor(() => expect(oldSignal.aborted).toBe(true))
    await act(async () => pending.resolve(page(story(3, 'Late outside article'))))
    expect(screen.queryByRole('heading', { name: 'Late outside article' })).toBeNull()
  })
  it('distinguishes empty groups and unsubscribed accounts without widening the scope', async () => {
    subscriptions = []
    setup(<NewsList />, '/?scope=group&group_id=14')
    expect(await screen.findByRole('link', { name: '添加频道' })).toBeInTheDocument()
    expect(api.fetchNews.mock.calls.every(([p]) => p.scope === 'group')).toBe(true)
    fireEvent.click(screen.getByRole('button', { name: '我的订阅' }))
    expect(await screen.findByRole('link', { name: '选择频道' })).toBeInTheDocument()
    expect(api.fetchNews.mock.calls.every(([p]) => p.scope !== 'all')).toBe(true)
  })
  it('falls back from a deleted group and saves the replacement preference', async () => {
    setup(<NewsList />, '/?scope=group&group_id=999&source=1&page=2')
    expect(await screen.findByText('该分组已删除或不可访问，已返回我的订阅。')).toBeInTheDocument()
    await waitFor(() => expect(api.fetchNews).toHaveBeenCalledWith(expect.objectContaining({ scope: 'subscribed', page: 1 }), expect.any(AbortSignal)))
    expect(api.fetchNews.mock.calls.some(([p]) => p.group_id === 999)).toBe(false)
    await waitFor(() => expect(api.saveNewsPreferences).toHaveBeenCalledWith({ scope: 'subscribed', group_id: null }))
  })
  it('fails closed on configuration errors and retries without showing all articles', async () => {
    api.fetchChannelGroups.mockRejectedValueOnce(new Error('offline'))
    setup(<NewsList />, '/?scope=subscribed')
    expect(await screen.findByRole('alert')).toHaveTextContent('配置加载失败')
    expect(api.fetchNews).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: '重试', exact: true }))
    await waitFor(() => expect(api.fetchNews).toHaveBeenCalledWith(expect.objectContaining({ scope: 'subscribed' }), expect.any(AbortSignal)))
  })
  it('limits read-only mode to the existing public feed', async () => {
    setup(<NewsList />, '/?scope=group&group_id=11', { user: null, capabilities: readOnlyCapabilities() })
    await waitFor(() => expect(api.fetchNews).toHaveBeenCalled())
    expect(api.fetchChannelGroups).not.toHaveBeenCalled()
    expect(api.fetchNewsPreferences).not.toHaveBeenCalled()
    expect(screen.queryByRole('button', { name: '我的订阅' })).toBeNull()
    expect(screen.getByRole('link', { name: '频道目录' })).toBeInTheDocument()
  })
})

describe('regional reading', () => {
  it('combines region with the group, preserves search/category and restores browser history', async () => {
    setup(<NewsList />, '/?scope=group&group_id=11&region=international&search=ai&category=8&source=1&page=2')
    await waitFor(() => expect(api.fetchNews).toHaveBeenCalledWith(expect.objectContaining({ region: 'international', group_id: 11, page: 2 }), expect.any(AbortSignal)))
    fireEvent.click(within(screen.getByRole('group', { name: '频道地区' })).getByRole('button', { name: '国内', exact: true }))
    await waitFor(() => expect(api.fetchNews).toHaveBeenLastCalledWith(expect.objectContaining({ region: 'domestic', group_id: 11, search: 'ai', category: '8', page: 1 }), expect.any(AbortSignal)))
    expect(screen.getByTestId('url')).not.toHaveTextContent('source=')
    fireEvent.click(screen.getByRole('button', { name: 'back', exact: true }))
    await waitFor(() => expect(screen.getByTestId('url')).toHaveTextContent('region=international'))
    fireEvent.click(screen.getByRole('button', { name: '清除全部条件' }))
    await waitFor(() => expect(screen.getByTestId('url')).toHaveTextContent('scope=group'))
    expect(screen.getByTestId('url')).not.toHaveTextContent('region=')
    expect(screen.getByTestId('url')).toHaveTextContent('group_id=11')
  })
  it('does not broaden an invalid URL region into the full public feed', async () => {
    setup(<NewsList />, '/?scope=all&region=invalid')
    expect(await screen.findByRole('alert')).toHaveTextContent('无效的频道地区')
    expect(api.fetchNews).not.toHaveBeenCalled()
    fireEvent.click(within(screen.getByRole('group', { name: '频道地区' })).getByRole('button', { name: '国际', exact: true }))
    await waitFor(() => expect(api.fetchNews).toHaveBeenCalledWith(expect.objectContaining({ region: 'international' }), expect.any(AbortSignal)))
  })
  it('filters channel management by region independently of language', async () => {
    api.fetchSources.mockResolvedValue([...channels.map(c => ({ ...c, region: 'international' })),
      { id: 9, name: 'PV Magazine 中文版', region: 'domestic', language: 'zh', source_type: 'news', subscription_status: 'active' }])
    setup(<ChannelsPage />)
    expect(await screen.findByRole('heading', { name: 'OpenAI Blog' })).toBeInTheDocument()
    fireEvent.click(within(screen.getByRole('group', { name: '频道地区' })).getByRole('button', { name: '国内', exact: true }))
    expect(screen.getByRole('heading', { name: 'PV Magazine 中文版' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'OpenAI Blog' })).toBeNull()
  })
  it('marks medical articles and handles RSS entries without abstracts', async () => {
    api.fetchNews.mockResolvedValue(page({ ...story(2, 'Medical research'), content: '', is_medical: true, reading_policy: 'rss_summary_only' }))
    setup(<NewsList />, '/?scope=all')
    expect(await screen.findByText('新闻资讯，不构成医疗建议')).toBeInTheDocument()
    expect(screen.getByText('来源未提供摘要')).toBeInTheDocument()
  })
})

describe('channel management', () => {
  it('subscribes a zero-article channel and sets multiple groups', async () => {
    api.changeChannelSubscriptions.mockImplementation(async payload => {
      if (payload.action === 'subscribe') subscriptions = [...subscriptions, { id: 15, source_id: 2, group_ids: [] }]
      else subscriptions = subscriptions.map(s => payload.source_ids.includes(s.source_id) ? { ...s, group_ids: payload.group_ids } : s)
      return subscriptions
    })
    setup(<ChannelsPage />)
    const heading = await screen.findByRole('heading', { name: 'DeepMind' })
    fireEvent.click(within(heading.closest('article')).getByRole('button', { name: '订阅', exact: true }))
    await waitFor(() => expect(within(heading.closest('article')).getByText('已订阅 · 未加入分组')).toBeInTheDocument())
    fireEvent.click(within(heading.closest('article')).getByRole('button', { name: '管理分组' }))
    fireEvent.click(within(heading.closest('article')).getByRole('checkbox', { name: 'AI', exact: true }))
    await waitFor(() => expect(api.changeChannelSubscriptions).toHaveBeenLastCalledWith({ action: 'set_groups', source_ids: [2], group_ids: [11] }))
    await waitFor(() => expect(within(heading.closest('article')).getByRole('checkbox', { name: 'AI', exact: true })).toBeEnabled())
    fireEvent.click(within(heading.closest('article')).getByRole('checkbox', { name: '前端', exact: true }))
    await waitFor(() => expect(api.changeChannelSubscriptions).toHaveBeenLastCalledWith({ action: 'set_groups', source_ids: [2], group_ids: [11, 13] }))
  })
  it('confirms cancellation with affected groups; retired channels cannot gain subscriptions', async () => {
    api.changeChannelSubscriptions.mockResolvedValue([])
    setup(<ChannelsPage />)
    const ai = (await screen.findByRole('heading', { name: 'OpenAI Blog' })).closest('article')
    const retired = screen.getByRole('heading', { name: 'Reuters' }).closest('article')
    expect(within(retired).getByRole('button', { name: '订阅', exact: true })).toBeDisabled()
    const cancelSubscription = within(ai).getByRole('button', { name: '取消订阅', exact: true })
    cancelSubscription.focus()
    fireEvent.click(cancelSubscription)
    const dialog = await screen.findByRole('alertdialog')
    expect(dialog).toHaveTextContent('AI')
    expect(api.changeChannelSubscriptions).not.toHaveBeenCalled()
    expect(within(dialog).getByRole('button', { name: '取消', exact: true })).toHaveFocus()
    fireEvent.click(within(dialog).getByRole('button', { name: '取消', exact: true }))
    expect(cancelSubscription).toHaveFocus()
    fireEvent.click(cancelSubscription)
    fireEvent.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: '确认', exact: true }))
    await waitFor(() => expect(api.changeChannelSubscriptions).toHaveBeenCalledWith({ action: 'unsubscribe', source_ids: [1] }))
  })
  it('manages groups and batches membership without unsubscribing channels', async () => {
    api.createChannelGroup.mockImplementation(async name => { groups = [...groups, { id: 21, name, source_ids: [] }]; return groups.at(-1) })
    api.updateChannelGroup.mockImplementation(async (id, payload) => { groups = groups.map(g => g.id === id ? { ...g, ...(payload.name ? { name: payload.name } : {}) } : g); return groups.find(g => g.id === id) })
    api.deleteChannelGroup.mockImplementation(async id => { groups = groups.filter(g => g.id !== id) })
    setup(<ChannelsPage />)
    fireEvent.click(await screen.findByRole('button', { name: '分组管理' }))
    fireEvent.change(await screen.findByRole('textbox', { name: '新分组名称' }), { target: { value: '  新频道分组  ' } })
    fireEvent.click(screen.getByRole('button', { name: '创建分组' }))
    expect(await screen.findByRole('button', { name: '新频道分组 (0)' })).toHaveAttribute('aria-pressed', 'true')
    fireEvent.click(screen.getByRole('checkbox', { name: '选择 OpenAI Blog' }))
    fireEvent.click(screen.getByRole('button', { name: '添加到当前分组' }))
    await waitFor(() => expect(api.updateChannelGroup).toHaveBeenCalledWith(21, { add_source_ids: [1] }))
    await waitFor(() => expect(screen.getByRole('button', { name: '从当前分组移除' })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: '从当前分组移除' }))
    await waitFor(() => expect(api.updateChannelGroup).toHaveBeenCalledWith(21, { remove_source_ids: [1] }))
    await waitFor(() => expect(screen.getByRole('button', { name: '删除分组' })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: '删除分组' }))
    expect(await screen.findByRole('alertdialog')).toHaveTextContent('频道订阅会保留')
    fireEvent.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: '确认', exact: true }))
    await waitFor(() => expect(api.deleteChannelGroup).toHaveBeenCalledWith(21))
    expect(api.changeChannelSubscriptions).not.toHaveBeenCalled()
  })
})
