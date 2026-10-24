import '@tests/helpers/commandDom'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import SmartGroupingWorkspace from '@/pages/SmartGroupingWorkspace'
import ExistingGroupOrganizer from '@/components/workspace/ExistingGroupOrganizer'
import type { ChannelGroup, ChannelGroupRoot } from '@/types/channels'
import { listAITaskPreferences } from '@/services/aiConnectionsApi'
import { workspaceRequest, type GroupingConfig, type Proposal } from '@/services/workspaceApi'
vi.mock('@/context/AuthContext', () => ({ useAuth: () => ({ user: { id: 1, isSuperuser: false }, loading: false }) }))
vi.mock('@/services/aiConnectionsApi', () => ({ listAITaskPreferences: vi.fn() }))
vi.mock('@/services/channelQueries', async original => ({ ...await original<typeof import('@/services/channelQueries')>(), useChannelConfig: () => ({ ready: true, error: false, roots: { data: roots }, groups: { data: groups }, subscriptions: { data: [{ source_id: 1, group_ids: [] }, { source_id: 2, group_ids: [8] }] } }) }))
vi.mock('@/services/workspaceApi', async original => ({ ...await original<typeof import('@/services/workspaceApi')>(), workspaceRequest: vi.fn(),
  workspaceCatalogOptions: () => ({ queryKey: ['test-group-catalog'], queryFn: () => request('/smart-channels/catalog/') }),
  workspaceConfigOptions: () => ({ queryKey: ['workspace', 1, 'grouping-config'], queryFn: () => request('/me/smart-channels/settings/') }),
}))
const roots: ChannelGroupRoot[] = [{ id: 3, name: '技术', version: 1, child_count: 1, created_at: '2026-01-01', updated_at: '2026-01-01' }]
const groups: ChannelGroup[] = [{ id: 8, root_id: 3, name: '前端开发', source_ids: [2], version: 1, created_at: '2026-01-01', updated_at: '2026-01-01' }]
const config = { mode: 'suggest', bindings: {}, revision: 1, ai_available: true, match_existing: true, ai_enabled: false, ai_model_id: null, daily_limit: 5, summary: { pending: 0, suggested: 1, applied: 0 } } as GroupingConfig
const proposal = { id: 'p1', target: 'groups', engine: 'rules', status: 'ready', source_ids: [1], topic_keys: [], result: [{ source_id: 1, name: 'React', group_ids: [8], topic_keys: [], reason: '可信频道主题', origin: 'catalog', needs_review: true }], error_code: '', created_at: '2026-10-22T00:00:00Z', expires_at: '', applied_count: 0, model_id: '', attempts: 0 } as Proposal
const request = vi.mocked(workspaceRequest)
type Options = Parameters<typeof workspaceRequest>[1]
let handler: (path: string, options?: Options) => unknown
const clients: QueryClient[] = []
// The history endpoint returns a paged object; a full page is not "more".
const page = (results: Proposal[], extra: { page?: number; count?: number; has_more?: boolean } = {}) => ({
  results, page: extra.page ?? 1, page_size: 30, count: extra.count ?? results.length, has_more: extra.has_more ?? false,
})
function defaults(path: string, options?: Options): unknown {
  if (path.startsWith('/smart-channels/catalog')) return { topics: [], presets: [], sources: [] }
  if (path.endsWith('/settings/')) return { ...config, ...options?.body as object }
  if (path.split('?')[0].endsWith('/proposals/')) return options?.method === 'POST' ? proposal : page([proposal])
  if (path.endsWith('/apply/')) return { ...proposal, status: 'applied', applied_count: 1 }
  if (path.endsWith('/undo/')) return { ...proposal, status: 'undone' }
  if (path.endsWith('/cancel/')) return { ...proposal, status: 'cancelled' }
  return proposal
}
beforeEach(() => {
  handler = defaults
  request.mockReset().mockImplementation(async <T,>(path: string, options?: Options) => await handler(path, options) as T)
  vi.mocked(listAITaskPreferences).mockReset().mockResolvedValue({ revision: 2, preferences: [{ task_kind: 'default', selection_source: 'byok', selection_state: 'available', model_config_id: 'model-1', model: { display_name: 'Saved model', model_id: 'saved' } }], subscription: { state: 'not_connected', model_id: null, display_name: null, research_eligible: false } } as Awaited<ReturnType<typeof listAITaskPreferences>>)
})
afterEach(() => { cleanup(); clients.splice(0).forEach(client => client.clear()) })
async function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } }); clients.push(client)
  const view = render(<QueryClientProvider client={client}><MemoryRouter><SmartGroupingWorkspace /></MemoryRouter></QueryClientProvider>)
  fireEvent.click(await screen.findByRole('button', { name: '整理频道' }))
  await screen.findByRole('heading', { name: 'AI 自动分组' })
  return { ...view, client }
}
function writes(method = 'POST') { return request.mock.calls.filter(([, options]) => options?.method === method) }
it('keeps hierarchy planning review-only and applies only selected exact rows', async () => {
  const row = { root_id: null, root_name: '工程', group_ids: [8], reason: '现有前端子分组属于工程主题' }
  const hierarchy = { ...proposal, id: 'hierarchy-1', target: 'hierarchy' as const, engine: 'ai' as const, result: [row] }
  handler = (path, options) => {
    const body = options?.body
    if (path === '/me/smart-channels/proposals/?target=hierarchy&page=1') return page([])
    if (path === '/me/smart-channels/proposals/' && options?.method === 'POST' &&
        body && typeof body === 'object' && 'target' in body && body.target === 'hierarchy') return hierarchy
    if (path.endsWith('/hierarchy-1/')) return hierarchy
    if (path.endsWith('/hierarchy-1/apply/')) return { ...hierarchy, status: 'applied' }
    return defaults(path, options)
  }
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } }); clients.push(client)
  render(<QueryClientProvider client={client}><MemoryRouter><SmartGroupingWorkspace /></MemoryRouter></QueryClientProvider>)
  expect(await screen.findByRole('heading', { name: '整理根分类与子分组' })).toBeInTheDocument()
  expect(screen.getByText(/确认前不会写入任何层级或成员数据/)).toBeInTheDocument()
  fireEvent.click(await screen.findByRole('checkbox', { name: '同意本次使用本人模型额度生成层级建议。' }))
  fireEvent.click(screen.getByRole('button', { name: '生成层级建议' }))
  const preview = await screen.findByRole('region', { name: '层级建议' })
  expect(within(preview).getByText('技术 / 前端开发 → 工程 / 前端开发')).toBeInTheDocument()
  expect(request.mock.calls.some(([path]) => path.endsWith('/apply/'))).toBe(false)
  const apply = within(preview).getByRole('button', { name: '确认应用层级移动' })
  await waitFor(() => expect(apply).toBeEnabled())
  fireEvent.click(apply)
  await waitFor(() => expect(request).toHaveBeenCalledWith('/me/smart-channels/proposals/hierarchy-1/apply/', expect.objectContaining({
    method: 'POST', viewer: 1, body: { rows: [row] },
  })))
})

function startRules() {
  fireEvent.click(screen.getByRole('button', { name: '免费规则匹配' }))
  fireEvent.click(screen.getByRole('button', { name: '匹配到已有分组' }))
}
it('organizes only ungrouped subscriptions against existing groups without model spending', async () => {
  await setup()
  expect(writes()).toHaveLength(0)
  startRules()
  await waitFor(() => expect(writes()).toHaveLength(1))
  expect(writes()[0][1]).toMatchObject({ viewer: 1, signal: expect.any(AbortSignal), body: { target: 'groups', source_ids: [1], engine: 'rules', consent: false } })
  expect(screen.queryByRole('heading', { name: '选择范围与主题' })).toBeNull()
  expect(screen.getByText('高级：按主题预设整理')).toBeInTheDocument()
})
it('starts one explicit AI planning job with the saved model and selected batch', async () => {
  await setup()
  const consent = await screen.findByRole('checkbox', { name: '同意本次使用上述个人模型额度生成分组建议。' })
  fireEvent.click(consent)
  fireEvent.click(screen.getByRole('button', { name: '生成 AI 分组建议' }))
  await waitFor(() => expect(writes()).toHaveLength(1))
  expect(writes()[0][1]).toMatchObject({ viewer: 1, body: {
    target: 'groups', source_ids: [1], engine: 'ai', consent: true, model_config_id: 'model-1',
  } })
})
it('makes batch AI planning the primary flow and keeps fixed topic templates secondary', async () => {
  await setup()
  expect(within(screen.getByRole('navigation', { name: '自动分组步骤' })).getAllByRole('listitem').map(item => item.textContent)).toEqual([
    expect.stringContaining('选择范围'), expect.stringContaining('AI 分析'), expect.stringContaining('检查建议'), expect.stringContaining('批量应用'),
  ])
  expect(screen.getByText('批量整理')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'AI 自动规划' })).toHaveAttribute('aria-pressed', 'true')
  expect(screen.getByText('次要入口 · 固定主题模板')).toBeInTheDocument()
  expect(screen.getByText(/默认请使用上方“整理频道”/)).toBeInTheDocument()
  expect(screen.queryByRole('heading', { name: '选择范围与主题' })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '高级：按主题预设整理' }))
  expect(await screen.findByRole('heading', { name: '选择范围与主题' })).toBeInTheDocument()
})
it('distinguishes suggested existing groups from unmatched channels and shows the matching reason', async () => {
  const mixed = { ...proposal, source_ids: [1, 2], result: [
    proposal.result[0],
    { ...proposal.result[0], source_id: 2, name: 'Unknown feed', group_ids: [], reason: '频道资料不足，无法可靠匹配' },
  ] }
  handler = (path, options) => path.split('?')[0].endsWith('/proposals/') && !options?.method ? page([mixed])
    : path.endsWith('/p1/') ? mixed : defaults(path, options)
  await setup()
  fireEvent.click(await screen.findByRole('button', { name: '查看建议' }))
  const matched = await screen.findByRole('group', { name: /React/ })
  expect(within(matched).getByText('待分析')).toBeInTheDocument()
  expect(within(matched).getByText('建议分组')).toBeInTheDocument()
  expect(within(matched).getByText('技术 / 前端开发')).toBeInTheDocument()
  expect(within(matched).getByText('建议依据')).toBeInTheDocument()
  expect(within(matched).getByText('可信频道主题')).toBeInTheDocument()
  const unmatched = screen.getByRole('group', { name: /Unknown feed/ })
  expect(within(unmatched).getByText('未匹配')).toBeInTheDocument()
  expect(within(unmatched).getByText('资料不足，暂时保持未分组')).toBeInTheDocument()
  expect(within(unmatched).getByText('可手动选择任一已有或 AI 建议的新路径。')).toBeInTheDocument()
  expect(within(unmatched).getByRole('button', { name: '调整 Unknown feed 的建议分组' })).toBeInTheDocument()
})
it('reviews group suggestions then applies only existing group IDs and allows undo', async () => {
  await setup()
  fireEvent.click(await screen.findByRole('button', { name: '查看建议' }))
  await waitFor(() => expect(screen.getByRole('button', { name: '确认并批量应用' })).toBeEnabled())
  fireEvent.click(screen.getByRole('button', { name: '确认并批量应用' }))
  await waitFor(() => expect(writes()[0][0]).toBe('/me/smart-channels/proposals/p1/apply/'))
  expect(writes()[0][1]?.body).toEqual({ assignments: [{ source_id: 1, group_ids: [8], new_group_paths: [] }] })
  fireEvent.click(await screen.findByRole('button', { name: '撤销本次新增归属' }))
  await waitFor(() => expect(writes()[1][0]).toBe('/me/smart-channels/proposals/p1/undo/'))
})
it('reviews AI-proposed new groups and creates them through one bulk payload', async () => {
  const aiPlan = { ...proposal, engine: 'ai' as const, result: [{
    ...proposal.result[0], group_ids: [], new_group_paths: [{ root_id: 3, root_name: null, name: 'AI 工程' }], reason: '近期内容集中于模型工程',
  }] }
  handler = (path, options) => path.split('?')[0].endsWith('/proposals/') && !options?.method ? page([aiPlan])
    : path.endsWith('/p1/') ? aiPlan : defaults(path, options)
  await setup()
  fireEvent.click(await screen.findByRole('button', { name: '查看建议' }))
  const channel = await screen.findByRole('group', { name: /React/ })
  expect(within(channel).getByText('待确认 AI 建议')).toBeInTheDocument()
  expect(within(channel).getByText('技术 / AI 工程')).toBeInTheDocument()
  await waitFor(() => expect(screen.getByRole('button', { name: '确认并批量应用' })).toBeEnabled())
  fireEvent.click(screen.getByRole('button', { name: '确认并批量应用' }))
  await waitFor(() => expect(writes()[0][1]?.body).toEqual({ assignments: [{
    source_id: 1, group_ids: [], new_group_paths: [{ root_id: 3, root_name: null, name: 'AI 工程' }],
  }] }))
})
it('blocks an assignment that would exceed the limit after existing memberships are counted', async () => {
  const fullRoots = [{ ...roots[0], child_count: 4 }]
  const fullGroups = [
    groups[0],
    { ...groups[0], id: 9, name: '后端开发', source_ids: [1] },
    { ...groups[0], id: 10, name: '产品设计', source_ids: [1] },
    { ...groups[0], id: 11, name: '候选分组', source_ids: [] },
  ]
  const overLimit = { ...proposal, result: [{ ...proposal.result[0], group_ids: [11] }] }
  handler = (path, options) => path.split('?')[0].endsWith('/proposals/') && !options?.method ? page([overLimit])
    : path.endsWith('/p1/') ? overLimit : defaults(path, options)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } }); clients.push(client)
  render(<QueryClientProvider client={client}><MemoryRouter>
    <ExistingGroupOrganizer viewer={1} initialConfig={config} roots={fullRoots} groups={fullGroups}
      subscriptions={[{ id: 1, groupIds: [8, 9, 10] }]} />
  </MemoryRouter></QueryClientProvider>)
  fireEvent.click(await screen.findByRole('button', { name: '查看建议' }))
  await waitFor(() => expect(screen.getByRole('button', { name: '取消任务' })).toBeEnabled())
  expect(screen.getByRole('button', { name: '确认并批量应用' })).toBeDisabled()
})
it('requires new explicit saved-model consent for unattended AI and never saves by toggling', async () => {
  await setup()
  fireEvent.click(screen.getByRole('checkbox', { name: '后台 AI 生成待确认建议' }))
  const save = screen.getByRole('button', { name: '保存自动整理设置' })
  expect(save).toBeDisabled()
  expect(writes('PATCH')).toHaveLength(0)
  await waitFor(() => expect(screen.getByRole('checkbox', { name: /单独授权上述本人模型/ })).toBeEnabled())
  fireEvent.click(screen.getByRole('checkbox', { name: /单独授权上述本人模型/ }))
  expect(save).toBeEnabled()
  fireEvent.click(save)
  await waitFor(() => expect(writes('PATCH')).toHaveLength(1))
  expect(writes('PATCH')[0][1]).toMatchObject({ viewer: 1, body: { ai_enabled: true, model_config_id: 'model-1', consent: true, match_existing: true, daily_limit: 5 } })
})
it('retries the same preview request after response loss without duplicate task identity', async () => {
  let failed = false
  handler = (path, options) => { if (options?.method === 'POST' && !failed) { failed = true; throw Error('lost') }; return defaults(path, options) }
  await setup()
  startRules()
  fireEvent.click(await screen.findByRole('button', { name: '重试同一次建议' }))
  await waitFor(() => expect(writes()).toHaveLength(2))
  expect(writes()[1][1]?.body).toEqual(writes()[0][1]?.body)
})
it('aborts pending private writes on unmount and cannot populate the old viewer cache', async () => {
  let finish!: (value: unknown) => void
  // Promise.withResolvers is unavailable under the application's ES2022 lib.
  const pending = new Promise<unknown>(resolve => { finish = resolve })
  handler = (path, options) => options?.method === 'POST' ? pending : defaults(path, options)
  const { unmount, client } = await setup()
  startRules()
  await waitFor(() => expect(writes()).toHaveLength(1))
  const signal = writes()[0][1]?.signal
  unmount()
  expect(signal?.aborted).toBe(true)
  await act(async () => finish(proposal))
  expect(client.getQueryData(['workspace', 1, 'proposal', 'p1'])).toBeUndefined()
})
it('cancels a queued persisted task without applying a suggestion', async () => {
  handler = (path, options) => { const value = defaults(path, options); return path.split('?')[0].endsWith('/proposals/') && options?.method === 'POST' ? { ...proposal, status: 'queued' } : value }
  await setup()
  startRules()
  await waitFor(() => expect(screen.getByRole('button', { name: '取消任务' })).toBeEnabled())
  fireEvent.click(screen.getByRole('button', { name: '取消任务' }))
  await waitFor(() => expect(writes()[1][0]).toBe('/me/smart-channels/proposals/p1/cancel/'))
  expect(writes().some(([path]) => path.endsWith('/apply/'))).toBe(false)
})
it('reconciles an unknown apply outcome before allowing any further writes', async () => {
  let applied = false
  handler = (path, options) => {
    if (path.endsWith('/apply/')) { applied = true; throw Error('response lost') }
    if (path.endsWith('/p1/') && applied) return { ...proposal, status: 'applied', applied_count: 1 }
    return defaults(path, options)
  }
  await setup()
  fireEvent.click(await screen.findByRole('button', { name: '查看建议' }))
  await waitFor(() => expect(screen.getByRole('button', { name: '确认并批量应用' })).toBeEnabled())
  fireEvent.click(screen.getByRole('button', { name: '确认并批量应用' }))
  await screen.findByRole('button', { name: '读取操作结果' })
  expect(screen.getByRole('button', { name: '确认并批量应用' })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: '读取操作结果' }))
  await waitFor(() => expect(screen.getByRole('button', { name: '撤销本次新增归属' })).toBeEnabled())
  expect(writes()).toHaveLength(1)
})
it('fails closed when organization configuration cannot be loaded', async () => {
  handler = path => { if (path.endsWith('/settings/')) throw Error('offline'); return defaults(path) }
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } }); clients.push(client)
  render(<QueryClientProvider client={client}><MemoryRouter><SmartGroupingWorkspace /></MemoryRouter></QueryClientProvider>)
  await screen.findByRole('heading', { name: '整理配置未能加载' })
  expect(screen.queryByRole('button', { name: '生成 AI 分组建议' })).toBeNull()
  expect(writes()).toHaveLength(0)
})
it('uses a legacy settings change as the authoritative mode when saving other drafts', async () => {
  let saved = { ...config }
  handler = (path, options) => {
    if (path.endsWith('/settings/')) { if (options?.method === 'PATCH') saved = { ...saved, ...options.body as object }; return saved }
    return defaults(path, options)
  }
  await setup()
  fireEvent.click(screen.getByRole('button', { name: '高级：按主题预设整理' }))
  fireEvent.click(screen.getByRole('radio', { name: /关闭后续自动整理/ }))
  fireEvent.click(screen.getByRole('button', { name: '保存后续整理模式' }))
  await waitFor(() => expect(screen.getByRole('combobox', { name: '自动整理模式' })).toHaveValue('off'))
  fireEvent.click(screen.getByRole('button', { name: '保存自动整理设置' }))
  await waitFor(() => expect(writes('PATCH')).toHaveLength(2))
  expect(writes('PATCH')[1][1]?.body).toMatchObject({ mode: 'off', ai_enabled: false })
})
it('keeps an explicitly edited mode while following untouched server settings', async () => {
  const { client } = await setup()
  fireEvent.change(screen.getByRole('combobox', { name: '自动整理模式' }), { target: { value: 'auto' } })
  await act(async () => client.setQueryData(['workspace', 1, 'grouping-config'], { ...config, mode: 'off', match_existing: false, revision: 2 }))
  expect(screen.getByRole('combobox', { name: '自动整理模式' })).toHaveValue('auto')
  await waitFor(() => expect(screen.getByRole('checkbox', { name: '匹配已有个人分组' })).not.toBeChecked())
  fireEvent.click(screen.getByRole('button', { name: '保存自动整理设置' }))
  await waitFor(() => expect(writes('PATCH')).toHaveLength(1))
  expect(writes('PATCH')[0][1]?.body).toMatchObject({ mode: 'auto', match_existing: false })
})

it('keeps mixed proposal history routed to the matching groups or legacy topics editor', async () => {
  handler = (path, options) => path.split('?')[0].endsWith('/proposals/') && !options?.method
    ? page([proposal, { ...proposal, id: 'topic1', target: 'topics', source_ids: [1, 2, 3], topic_keys: ['frontend'] }])
    : defaults(path, options)
  await setup()
  expect(await screen.findByRole('button', { name: '查看建议' })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: '高级：按主题预设整理' }))
  const legacyHistory = screen.getByRole('heading', { name: '整理记录与待确认建议' }).closest('section')!
  await waitFor(() => expect(within(legacyHistory).getAllByRole('listitem')).toHaveLength(1))
  expect(within(legacyHistory).getByText(/3 个频道/)).toBeInTheDocument()
})
it('keeps an untouched advanced mode synchronized when the default organizer saves settings', async () => {
  let saved = { ...config }
  handler = (path, options) => {
    if (path.endsWith('/settings/')) { if (options?.method === 'PATCH') saved = { ...saved, ...options.body as object }; return saved }
    return defaults(path, options)
  }
  await setup()
  fireEvent.click(screen.getByRole('button', { name: '高级：按主题预设整理' }))
  fireEvent.change(screen.getByRole('combobox', { name: '自动整理模式' }), { target: { value: 'off' } })
  fireEvent.click(screen.getByRole('button', { name: '保存自动整理设置' }))
  await waitFor(() => expect(screen.getByRole('radio', { name: /关闭后续自动整理/ })).toBeChecked())
  expect(screen.getByRole('button', { name: '保存后续整理模式' })).toBeDisabled()
})
it('loads an older pending group proposal and keeps its editor when browsing back to newer history', async () => {
  const old = { ...proposal, id: 'older-pending' }
  handler = (path, options) => {
    if (path === '/me/smart-channels/proposals/?target=groups&page=1') return page(Array.from({ length: 30 }, (_, index) => ({ ...proposal, id: 'recent-' + index, status: 'applied' })), { count: 31, has_more: true })
    if (path === '/me/smart-channels/proposals/?target=groups&page=2') return page([old], { page: 2, count: 31 })
    if (path === '/me/smart-channels/proposals/older-pending/') return old
    if (path === '/me/smart-channels/proposals/older-pending/apply/') return { ...old, status: 'applied', applied_count: 1 }
    return defaults(path, options)
  }
  await setup()
  const history = screen.getByRole('heading', { name: '建议与整理记录' }).closest('section')!
  fireEvent.click(await within(history).findByRole('button', { name: '较早记录' }))
  fireEvent.click(await within(history).findByRole('button', { name: '查看建议' }))
  await waitFor(() => expect(screen.getByRole('button', { name: '确认并批量应用' })).toBeEnabled())
  fireEvent.click(within(history).getByRole('button', { name: '较新记录' }))
  await waitFor(() => expect(within(history).getByText('第 1 页')).toBeInTheDocument())
  fireEvent.click(screen.getByRole('button', { name: '确认并批量应用' }))
  await waitFor(() => expect(writes()[0][0]).toBe('/me/smart-channels/proposals/older-pending/apply/'))
  expect(writes()[0][1]?.body).toEqual({ assignments: [{ source_id: 1, group_ids: [8], new_group_paths: [] }] })
})
it('explains why too many personal groups pause background organization', async () => {
  handler = (path, options) => path.endsWith('/settings/') ? { ...config, error_code: 'too_many_groups' } : defaults(path, options)
  await setup()
  expect(screen.getByText('个人分组超过本次整理上限（200 个），后台整理已暂停；可先调整分组。')).toBeInTheDocument()
})
it.each(['uncheck', 'mode-off'] as const)('revokes saved background AI without a usable model or site availability through %s', async action => {
  let saved = { ...config, ai_enabled: true, ai_available: false }
  handler = (path, options) => {
    if (path.endsWith('/settings/')) { if (options?.method === 'PATCH') saved = { ...saved, ...options.body as object }; return saved }
    return defaults(path, options)
  }
  vi.mocked(listAITaskPreferences).mockResolvedValue({ revision: 3, preferences: [],
    subscription: { state: 'not_connected', model_id: null, display_name: null, research_eligible: false } })
  await setup()
  const ai = screen.getByRole('checkbox', { name: '后台 AI 生成待确认建议' })
  expect(ai).toBeChecked()
  if (action === 'uncheck') {
    expect(ai).toBeEnabled()
    fireEvent.click(ai)
  } else fireEvent.change(screen.getByRole('combobox', { name: '自动整理模式' }), { target: { value: 'off' } })
  const save = screen.getByRole('button', { name: '保存自动整理设置' })
  expect(save).toBeEnabled()
  fireEvent.click(save)
  await waitFor(() => expect(writes('PATCH')).toHaveLength(1))
  expect(writes('PATCH')[0][1]?.body).toEqual({ mode: action === 'mode-off' ? 'off' : 'suggest', match_existing: true, ai_enabled: false, daily_limit: 5 })
})
it('mounts one group chooser at a time, preserves other rows, and restores focus on Escape', async () => {
  const twoSources = { ...proposal, source_ids: [1, 2], result: [...proposal.result, { ...proposal.result[0], source_id: 2, name: 'Vue' }] }
  handler = (path, options) => path.split('?')[0].endsWith('/proposals/') && !options?.method ? page([twoSources])
    : path.endsWith('/p1/') ? twoSources : defaults(path, options)
  await setup()
  fireEvent.click(await screen.findByRole('button', { name: '查看建议' }))
  await waitFor(() => expect(screen.getByRole('button', { name: '确认并批量应用' })).toBeEnabled())
  expect(screen.queryByRole('checkbox', { name: '技术 / 前端开发' })).toBeNull()
  const adjustReact = screen.getByRole('button', { name: '调整 React 的建议分组' })
  fireEvent.click(adjustReact)
  const reactGroup = screen.getByRole('checkbox', { name: '技术 / 前端开发' })
  expect(reactGroup).toBeChecked()
  fireEvent.click(reactGroup)
  fireEvent.keyDown(reactGroup, { key: 'Escape' })
  expect(adjustReact).toHaveFocus()
  expect(adjustReact).toHaveAttribute('aria-expanded', 'false')
  expect(screen.queryByRole('checkbox', { name: '技术 / 前端开发' })).toBeNull()
  expect(screen.getByText('资料不足，暂时保持未分组')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: '调整 Vue 的建议分组' }))
  expect(screen.getAllByRole('checkbox', { name: '技术 / 前端开发' })).toHaveLength(1)
  expect(screen.getByRole('checkbox', { name: '技术 / 前端开发' })).toBeChecked()
  const adjustVue = screen.getByRole('button', { name: '调整 Vue 的建议分组' })
  fireEvent.keyDown(adjustVue, { key: 'Escape' })
  expect(adjustVue).toHaveFocus()
  expect(adjustVue).toHaveAttribute('aria-expanded', 'false')
  fireEvent.click(screen.getByRole('button', { name: '确认并批量应用' }))
  await waitFor(() => expect(writes()[0][1]?.body).toEqual({ assignments: [{ source_id: 2, group_ids: [8], new_group_paths: [] }] }))
})
it('treats a full older page as the end when the contract says has_more is false', async () => {
  handler = (path, options) => {
    if (path === '/me/smart-channels/proposals/?target=groups&page=1') return page(Array.from({ length: 30 }, (_, index) => ({ ...proposal, id: 'full-' + index, status: 'applied' })), { count: 30, has_more: false })
    return defaults(path, options)
  }
  await setup()
  const history = screen.getByRole('heading', { name: '建议与整理记录' }).closest('section')!
  expect(await within(history).findAllByRole('button', { name: '查看任务' })).toHaveLength(30)
  expect(within(history).getByRole('button', { name: '较早记录' })).toBeDisabled()
})
it('keeps exactly one page heading when the advanced organizer is expanded', async () => {
  await setup()
  expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1)
  fireEvent.click(screen.getByRole('button', { name: '高级：按主题预设整理' }))
  expect(await screen.findByRole('combobox', { name: '自动整理模式' })).toBeInTheDocument()
  // The advanced entry is a panel inside the page, not a second page shell.
  expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1)
  expect(screen.getAllByRole('heading', { name: '按主题预设整理' })).toHaveLength(1)
  expect(screen.getByRole('heading', { name: '整理记录与待确认建议' })).toBeInTheDocument()
})

it('follows the saved authoritative mode instead of resurrecting a stale draft', async () => {
  const initial = { ...config, mode: 'suggest' as GroupingConfig['mode'] }
  handler = (path, options) => {
    if (path.endsWith('/settings/')) return options?.method === 'PATCH' ? { ...initial, ...(options.body as object) } : initial
    return defaults(path, options)
  }
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  clients.push(client)
  const view = (mode: GroupingConfig['mode']) => (
    <QueryClientProvider client={client}><MemoryRouter>
      <ExistingGroupOrganizer viewer={1} initialConfig={{ ...initial, mode }} roots={roots} groups={groups}
        subscriptions={[{ id: 1, groupIds: [] }]} />
    </MemoryRouter></QueryClientProvider>)
  const rendered = render(view('suggest'))
  const select = () => screen.getByRole('combobox', { name: '自动整理模式' })
  expect(select()).toHaveValue('suggest')
  fireEvent.change(select(), { target: { value: 'off' } })
  expect(select()).toHaveValue('off')
  fireEvent.click(screen.getByRole('button', { name: '保存自动整理设置' }))
  await screen.findByText('自动整理设置已保存。')
  // The parent re-renders with the saved config, then another settings entry
  // point changes the mode: no cleared draft may overwrite that value.
  rendered.rerender(view('off'))
  expect(select()).toHaveValue('off')
  rendered.rerender(view('auto'))
  expect(select()).toHaveValue('auto')
})
