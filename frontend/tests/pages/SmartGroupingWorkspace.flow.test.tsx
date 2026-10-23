import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { listAITaskPreferences } from '@/services/aiConnectionsApi'
import { Organizer, ProposalEditor } from '@/pages/SmartGroupingWorkspace'
import { workspaceKeys, workspaceRequest, type Catalog, type GroupingConfig, type Proposal } from '@/services/workspaceApi'

vi.mock('@/services/aiConnectionsApi', () => ({ listAITaskPreferences: vi.fn() }))
vi.mock('@/services/workspaceApi', async importOriginal => ({
  ...await importOriginal<typeof import('@/services/workspaceApi')>(), workspaceRequest: vi.fn(),
}))
const request = vi.mocked(workspaceRequest)
const topics = [{ key: 'frontend', name: '前端开发', description: 'Web 平台' }]
const catalog: Catalog = { topics, presets: [{ key: 'dev', name: '开发者', topics: ['frontend'] }], sources: [] }
const config: GroupingConfig = { mode: 'suggest', bindings: {}, revision: 1, ai_available: false }
const proposal: Proposal = {
  id: '7f40e403-d118-4339-a615-a934d96ce5e3', engine: 'rules', status: 'ready', source_ids: [1], topic_keys: ['frontend'],
  result: [{ source_id: 1, name: 'React Blog', topic_keys: ['frontend'], reason: '框架资料', origin: 'catalog', needs_review: false }],
  created_at: '2026-10-17T00:00:00Z', expires_at: '2099-10-18T00:00:00Z', error_code: '', applied_count: 0, model_id: '', attempts: 0,
}
const clients: QueryClient[] = []
// History pages are an explicit contract: a full first page is not the same as
// "has_more", so mocks must state count/has_more instead of relying on length.
const page = (results: Proposal[], extra: { page?: number; count?: number; has_more?: boolean } = {}) => ({
  results, page: extra.page ?? 1, page_size: 30, count: extra.count ?? results.length, has_more: extra.has_more ?? false,
})
type Options = Parameters<typeof workspaceRequest>[1]
let handler: (path: string, options?: Options) => unknown
function defaults(path: string, options?: Options): unknown {
  if (path.endsWith('/settings/')) return { ...config, ...(options?.body as object ?? {}) }
  if (path.split('?')[0].endsWith('/proposals/')) return options?.method === 'POST' ? { ...proposal } : page([])
  if (path.endsWith('/apply/')) return { ...proposal, status: 'applied', applied_count: 1 }
  if (path.endsWith('/undo/')) return { ...proposal, status: 'undone' }
  if (path.endsWith('/cancel/')) return { ...proposal, status: 'cancelled' }
  return { ...proposal }
}
function setup(subscriptions = [{ id: 1, groupIds: [] as number[] }], viewer = 1, aiAvailable = false) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  clients.push(client)
  const view = render(<QueryClientProvider client={client}><MemoryRouter>
    <Organizer viewer={viewer} admin={false} initialConfig={{ ...config, ai_available: aiAvailable }} catalog={catalog} groups={[]} subscriptions={subscriptions} />
  </MemoryRouter></QueryClientProvider>)
  return { ...view, client }
}
function postCalls() { return request.mock.calls.filter(([, options]) => options?.method === 'POST') }
async function generate() {
  fireEvent.click(screen.getByRole('button', { name: '生成分组预览' }))
  await waitFor(() => expect(screen.getByRole('button', { name: '确认应用分组' })).toBeEnabled())
}
beforeEach(() => {
  vi.mocked(listAITaskPreferences).mockReset().mockResolvedValue({ revision: 0, preferences: [] })
  handler = defaults
  request.mockReset()
  request.mockImplementation(async <T,>(path: string, options?: Options): Promise<T> => await handler(path, options) as T)
})
afterEach(() => { cleanup(); clients.splice(0).forEach(client => client.clear()) })

describe('AG-04 guided grouping', () => {
  it('shows four stages and makes no write from opening the page', async () => {
    setup()
    expect(within(screen.getByRole('navigation', { name: '整理步骤' })).getAllByRole('listitem')).toHaveLength(4)
    await waitFor(() => expect(request).toHaveBeenCalled())
    expect(postCalls()).toHaveLength(0)
  })
  it('explains why an empty account cannot generate and links to channels', () => {
    setup([])
    expect(screen.getByText('还没有订阅频道，先添加来源再整理。')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '去添加频道' })).toHaveAttribute('href', '/channels')
    expect(screen.getByRole('button', { name: '生成分组预览' })).toBeDisabled()
  })
  it('explains an empty ungrouped scope without starting work', () => {
    setup([{ id: 1, groupIds: [8] }])
    fireEvent.change(screen.getByRole('combobox', { name: '整理范围' }), { target: { value: 'ungrouped' } })
    expect(screen.getByText(/所有已订阅频道都已分组/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '生成分组预览' })).toBeDisabled()
    expect(postCalls()).toHaveLength(0)
  })
  it('requires a topic and exposes the reason the action is disabled', () => {
    setup()
    fireEvent.click(screen.getByRole('checkbox', { name: /前端开发/ }))
    expect(screen.getByText('请至少选择一个主题。')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '生成分组预览' })).toBeDisabled()
  })
  it('generates a read-only preview then focuses its heading', async () => {
    setup()
    await generate()
    expect(screen.getByRole('heading', { name: '分组建议预览' })).toHaveFocus()
    expect(postCalls()).toHaveLength(1)
    expect(postCalls()[0][1]).toMatchObject({ viewer: 1, body: { source_ids: [1], topic_keys: ['frontend'], engine: 'rules', consent: false } })
  })
  it('retries the exact creation snapshot and request id after response loss', async () => {
    let attempts = 0
    handler = (path, options) => {
      if (path.split('?')[0].endsWith('/proposals/') && options?.method === 'POST' && attempts++ === 0) throw new Error('lost response')
      return defaults(path, options)
    }
    setup()
    fireEvent.click(screen.getByRole('button', { name: '生成分组预览' }))
    await screen.findByText(/创建结果尚未确认/)
    expect(screen.getByRole('combobox', { name: '整理范围' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: '重试同一次预览' }))
    await screen.findByRole('button', { name: '确认应用分组' })
    expect(postCalls()).toHaveLength(2)
    expect(postCalls()[1][1]?.body).toEqual(postCalls()[0][1]?.body)
  })
  it('rejects a same-tick double submit before React rerenders', async () => {
    let finish!: (value: unknown) => void
    handler = (path, options) => options?.method === 'POST' ? new Promise(resolve => { finish = resolve }) : defaults(path, options)
    setup()
    const button = screen.getByRole('button', { name: '生成分组预览' })
    act(() => { fireEvent.click(button); fireEvent.click(button) })
    await waitFor(() => expect(postCalls()).toHaveLength(1))
    await act(async () => finish(proposal))
  })
  it('lets the user return to choices without silently creating a new task', async () => {
    handler = (path, options) => { if (options?.method === 'POST') throw new Error('network'); return defaults(path, options) }
    setup()
    fireEvent.click(screen.getByRole('button', { name: '生成分组预览' }))
    fireEvent.click(await screen.findByRole('button', { name: '返回修改选择' }))
    expect(screen.getByRole('combobox', { name: '整理范围' })).not.toBeDisabled()
    expect(screen.getByText(/服务端可能已创建任务/)).toBeInTheDocument()
    expect(postCalls()).toHaveLength(1)
  })
  it('does not submit an unsaved future grouping mode with this preview', async () => {
    setup()
    fireEvent.click(screen.getByRole('radio', { name: /自动加入已有分组/ }))
    expect(screen.getByText('后续整理模式尚未保存。')).toBeInTheDocument()
    await generate()
    fireEvent.click(screen.getByRole('button', { name: '确认应用分组' }))
    await waitFor(() => expect(postCalls()).toHaveLength(2))
    expect(postCalls()[1][1]?.body).toMatchObject({ mode: 'suggest' })
  })
  it('requires an explicit save for the future grouping mode', async () => {
    setup()
    fireEvent.click(screen.getByRole('radio', { name: /自动加入已有分组/ }))
    expect(request.mock.calls.some(([, options]) => options?.method === 'PATCH')).toBe(false)
    fireEvent.click(screen.getByRole('button', { name: '保存后续整理模式' }))
    await screen.findByText('后续整理模式已保存，现有频道归属保持不变。')
    expect(request.mock.calls.find(([, options]) => options?.method === 'PATCH')?.[1]?.body).toEqual({ mode: 'auto' })
  })
  it('reconciles a lost apply response with GET instead of repeating the write', async () => {
    let applied = false
    handler = (path, options) => {
      if (path.endsWith('/apply/')) { applied = true; throw new Error('response lost') }
      if (path.endsWith('/' + proposal.id + '/') && applied) return { ...proposal, status: 'applied', applied_count: 1 }
      return defaults(path, options)
    }
    setup()
    await generate()
    fireEvent.click(screen.getByRole('button', { name: '确认应用分组' }))
    fireEvent.click(await screen.findByRole('button', { name: '读取操作结果' }))
    await screen.findByText('已新增 1 条分组归属。')
    expect(request.mock.calls.filter(([path]) => path.endsWith('/apply/'))).toHaveLength(1)
  })
  it('does not let a late old-account creation resurrect cleared private caches', async () => {
    let finish!: (value: unknown) => void
    handler = (path, options) => options?.method === 'POST' ? new Promise(resolve => { finish = resolve }) : defaults(path, options)
    const view = setup()
    fireEvent.click(screen.getByRole('button', { name: '生成分组预览' }))
    await waitFor(() => expect(postCalls()).toHaveLength(1))
    const signal = postCalls()[0][1]?.signal
    view.unmount(); view.client.clear()
    await act(async () => finish(proposal))
    expect(signal?.aborted).toBe(true)
    expect(view.client.getQueryData(workspaceKeys.proposal(1, proposal.id))).toBeUndefined()
  })
  it('stops polling on a failed status read and retries only that GET', async () => {
    const queued = { ...proposal, status: 'queued' }
    let reads = 0
    handler = (path, options) => {
      if (path.split('?')[0].endsWith('/proposals/') && options?.method === 'POST') return queued
      if (path.endsWith('/' + proposal.id + '/')) { if (++reads === 1) throw new Error('offline'); return proposal }
      return defaults(path, options)
    }
    setup()
    fireEvent.click(screen.getByRole('button', { name: '生成分组预览' }))
    fireEvent.click(await screen.findByRole('button', { name: '重试' }))
    await screen.findByRole('button', { name: '确认应用分组' })
    expect(reads).toBe(2)
    expect(postCalls()).toHaveLength(1)
  })
  it('restores a saved preview from history without generating again', async () => {
    handler = (path, options) => path.split('?')[0].endsWith('/proposals/') && !options?.method ? page([proposal]) : defaults(path, options)
    setup()
    fireEvent.click(await screen.findByRole('button', { name: '查看' }))
    await screen.findByRole('button', { name: '确认应用分组' })
    expect(screen.getByRole('heading', { name: '分组建议预览' })).toHaveFocus()
    expect(postCalls()).toHaveLength(0)
  })
  it('Escape collapses the editable member list and restores its toggle focus', () => {
    render(<ProposalEditor proposal={proposal} topics={topics} groups={[]} mode="suggest" busy={false} onApply={vi.fn()} onCancel={vi.fn()} />)
    const toggle = screen.getByRole('button', { name: '调整频道归属' })
    fireEvent.click(toggle)
    const checkbox = screen.getByRole('checkbox', { name: /React Blog/ })
    checkbox.focus()
    fireEvent.keyDown(checkbox, { key: 'Escape' })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(toggle).toHaveFocus()
  })
})


it('binds an explicitly consented AI preview to the displayed verified default model', async () => {
  const id = '20adf7e7-44d7-4444-8888-105a61db3141'
  vi.mocked(listAITaskPreferences).mockResolvedValue({ revision: 3, preferences: [{
    task_kind: 'default', selection_state: 'available', model_config_id: id,
    model: { id, connection_id: 'synthetic', model_id: 'deepseek-chat', display_name: '我的分类模型' },
  }] })
  setup(undefined, 1, true)
  fireEvent.click(screen.getByRole('button', { name: 'AI 精细分类' }))
  await screen.findByText(/本次分类模型：我的分类模型/)
  expect(postCalls()).toHaveLength(0)
  expect(screen.getByRole('button', { name: '生成分组预览' })).toBeDisabled()
  fireEvent.click(screen.getByRole('checkbox', { name: /同意本次使用上述个人模型额度/ }))
  fireEvent.click(screen.getByRole('button', { name: '生成分组预览' }))
  await waitFor(() => expect(postCalls()).toHaveLength(1))
  expect(postCalls()[0][1]?.body).toMatchObject({ engine: 'ai', model_config_id: id, consent: true })
  expect(screen.getByRole('checkbox', { name: /同意本次使用上述个人模型额度/ })).not.toBeChecked()
})
