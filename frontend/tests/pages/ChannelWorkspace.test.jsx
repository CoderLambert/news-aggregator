import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider, useMutation } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import ChannelWorkspace from '@/pages/ChannelWorkspace'
import { changeChannelSubscriptions } from '@/services/api'

const state = vi.hoisted(() => ({ user: { id: 11, username: 'reader', isSuperuser: false }, enabled: true, error: false }))
vi.mock('@/context/AuthContext', () => ({ useAuth: () => ({ user: state.user, loading: false }) }))
vi.mock('@/services/api', () => ({ changeChannelSubscriptions: vi.fn().mockResolvedValue([]), updateChannelGroup: vi.fn().mockResolvedValue({}) }))
vi.mock('@/services/channelQueries', () => ({
  useChannelConfig: () => ({ enabled: state.enabled, accounts: state.enabled, ready: true, error: state.error, retry: vi.fn(), groups: { data: [] }, subscriptions: { data: [] } }),
  useChannelMutation: () => useMutation({ mutationFn: perform => perform() }),
}))
vi.mock('@/services/workspaceApi', async importOriginal => {
  const original = await importOriginal()
  const common = { logo: '', region: 'international', language: 'en', source_type: 'news', topics: ['frontend'], news_count: 3, subscription_reason: '', origin: 'catalog', needs_review: false, url: 'https://react.dev', feed_url: '', reading_policy: 'standard', updated_at: null, evidence_hash: 'test' }
  return { ...original, workspaceRequest: vi.fn().mockResolvedValue({ results: [] }), workspaceCatalogOptions: () => ({ queryKey: ['workspace', 'catalog'], queryFn: async () => ({ topics: [{ key: 'frontend', name: '前端开发', description: 'Web' }], presets: [], sources: [
    { ...common, id: 1, name: 'React Blog', description: 'React framework', subscription_status: 'active' },
    { ...common, id: 2, name: 'Retired Channel', description: 'Historical source', subscription_status: 'inactive' },
  ] }) }) }
})
function setup(path = '/channels') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}><ChannelWorkspace /></MemoryRouter></QueryClientProvider>)
}
beforeEach(() => { vi.clearAllMocks(); state.enabled = true; state.error = false })

describe('channel workspace directory', () => {
  it('renders actual catalog rows and filters by the search input', async () => {
    setup()
    expect(await screen.findByRole('link', { name: 'React Blog' })).toBeInTheDocument()
    fireEvent.change(screen.getByRole('searchbox', { name: '搜索频道' }), { target: { value: 'React' } })
    expect(screen.queryByRole('link', { name: 'Retired Channel' })).toBeNull()
  })
  it('keeps batch actions hidden until sources are selected', async () => {
    setup()
    await screen.findByRole('link', { name: 'React Blog' })
    expect(screen.queryByRole('region', { name: '批量操作' })).toBeNull()
    fireEvent.click(screen.getByRole('checkbox', { name: '选择 React Blog' }))
    expect(screen.getByRole('region', { name: '批量操作' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '批量订阅' }))
    await waitFor(() => expect(changeChannelSubscriptions).toHaveBeenCalledWith({ action: 'subscribe', source_ids: [1] }))
  })
  it('excludes inactive sources from a batch subscription', async () => {
    setup()
    await screen.findByRole('link', { name: 'React Blog' })
    fireEvent.click(screen.getByRole('checkbox', { name: '全选当前结果' }))
    fireEvent.click(screen.getByRole('button', { name: '批量订阅' }))
    await waitFor(() => expect(changeChannelSubscriptions).toHaveBeenCalledWith({ action: 'subscribe', source_ids: [1] }))
  })
  it('shows list and card switches without altering query filters', async () => {
    setup('/channels?q=React')
    await screen.findByRole('link', { name: 'React Blog' })
    fireEvent.click(screen.getByRole('button', { name: '卡片视图' }))
    expect(screen.getByRole('button', { name: '卡片视图' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('searchbox', { name: '搜索频道' })).toHaveValue('React')
  })
  it('hides account mutations when accounts are disabled', async () => {
    state.enabled = false
    setup()
    await screen.findByRole('link', { name: 'React Blog' })
    expect(screen.queryByRole('button', { name: '添加频道' })).toBeNull()
    expect(screen.queryByRole('checkbox', { name: '选择 React Blog' })).toBeNull()
  })
})
