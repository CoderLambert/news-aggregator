import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import PrivateTranslationPanel from '@/components/news-detail/PrivateTranslationPanel'
import { WorkspaceError } from '@/services/workspaceApi'
import * as models from '@/services/aiConnectionsApi'
import * as api from '@/services/privateTranslationApi'
vi.mock('@/services/aiConnectionsApi', async original => ({
  ...await original<typeof import('@/services/aiConnectionsApi')>(),
  listAIConnections: vi.fn(), listAIModels: vi.fn(), listAITaskPreferences: vi.fn(),
}))
vi.mock('@/services/privateTranslationApi', async original => ({
  ...await original<typeof import('@/services/privateTranslationApi')>(),
  latestPrivateTranslation: vi.fn(), startPrivateTranslation: vi.fn(), cancelPrivateTranslation: vi.fn(), retryPrivateTranslation: vi.fn(),
}))
const completed: api.PrivateTranslationTask = {
  task_id: '11111111-1111-4111-8111-111111111111', request_id: '22222222-2222-4222-8222-222222222222', news_id: 1, status: 'succeeded',
  generation: 1, retry_of: null, progress: '私有中文', error_code: '', model_config_id: 'model', target_language: 'zh', previous_result: null,
  result: { result_id: 4, task_id: '11111111-1111-4111-8111-111111111111', content: '私有中文', scope: 'private', provider: 'deepseek', model: 'Flash' },
}
function view(viewer = 7, sourceMarkdown = 'a'.repeat(100)) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  const changed = vi.fn()
  const tree = (id: number) => <QueryClientProvider client={client}><MemoryRouter>
    <PrivateTranslationPanel viewer={id} newsId={1} sourceRevision={1} sourceMarkdown={sourceMarkdown} onTaskChange={changed} />
  </MemoryRouter></QueryClientProvider>
  return { ...render(tree(viewer)), tree, client, changed }
}
const noSubscription: models.ChatGPTTaskOption = {
  state: 'not_connected', model_id: null, display_name: null, research_eligible: false,
}
beforeEach(() => {
  vi.resetAllMocks()
  vi.stubGlobal('EventSource', class { addEventListener() {} close() {} })
  vi.mocked(models.listAIConnections).mockResolvedValue([{ id: 'connection', is_enabled: true, key_saved: true, display_name: 'Mine' } as models.AIConnection])
  vi.mocked(models.listAIModels).mockResolvedValue([{ id: 'model', model_id: 'deepseek-flash', display_name: 'Flash', has_trusted_route: true,
    article_chat_supported: true, capabilities: { text: 'supported', tools: 'unknown' } } as models.AIModel])
  vi.mocked(models.listAITaskPreferences).mockResolvedValue({ revision: 1, preferences: [
    { task_kind: 'full_translation', selection_source: 'byok', model_config_id: 'model', selection_state: 'available', model: null },
  ], subscription: noSubscription })
  vi.mocked(api.latestPrivateTranslation).mockResolvedValue(null)
  vi.mocked(api.startPrivateTranslation).mockResolvedValue(completed)
  vi.mocked(api.retryPrivateTranslation).mockResolvedValue(completed)
  vi.mocked(api.cancelPrivateTranslation).mockResolvedValue({ task_id: completed.task_id, status: 'cancelled', error_code: 'translation_cancelled' })
})
afterEach(() => { cleanup(); vi.unstubAllGlobals() })
it('uses the saved translation model and one explicit billable click, without a model form or auto send', async () => {
  const rendered = view()
  const start = await screen.findByRole('button', { name: '翻译为中文' })
  await waitFor(() => expect(start).toBeEnabled())
  expect(screen.queryByRole('combobox')).toBeNull()
  expect(screen.queryByRole('checkbox')).toBeNull()
  expect(screen.queryByText(/可能产生费用|Mine · Flash/)).toBeNull()
  expect(api.startPrivateTranslation).not.toHaveBeenCalled()
  fireEvent.click(start); fireEvent.click(start)
  await screen.findByRole('button', { name: '重新翻译' })
  expect(api.startPrivateTranslation).toHaveBeenCalledOnce()
  expect(api.startPrivateTranslation).toHaveBeenCalledWith(1, 'model', expect.any(String), 7, expect.any(AbortSignal))
  expect(rendered.changed).toHaveBeenCalledWith(completed)
})
it('inherits only the explicitly saved default, never the first available model', async () => {
  vi.mocked(models.listAITaskPreferences).mockResolvedValue({ revision: 1, preferences: [
    { task_kind: 'full_translation', selection_source: 'inherit', model_config_id: null, selection_state: 'inherit_default', model: null },
    { task_kind: 'default', selection_source: 'byok', model_config_id: 'model', selection_state: 'available', model: null },
  ], subscription: noSubscription })
  view(); await waitFor(() => expect(screen.getByRole('button', { name: '翻译为中文' })).toBeEnabled())
  expect(api.startPrivateTranslation).not.toHaveBeenCalled()
})
it.each(['unset', 'needs_reselection', 'needs_verification'] as const)('blocks missing or stale model configuration without adding a configuration form (%s)', async state => {
  vi.mocked(models.listAITaskPreferences).mockResolvedValue({ revision: 1, preferences: [
    { task_kind: 'full_translation', selection_source: 'byok', model_config_id: 'model', selection_state: state, model: null },
  ], subscription: noSubscription })
  view()
  expect(await screen.findByText('默认翻译模型当前不可用。')).toBeInTheDocument()
  expect(screen.queryByRole('link')).toBeNull()
  expect(api.startPrivateTranslation).not.toHaveBeenCalled()
})
it('does not use an unverified text model even if its preference remains saved', async () => {
  vi.mocked(models.listAITaskPreferences).mockResolvedValue({ revision: 2, preferences: [
    { task_kind: 'full_translation', selection_source: 'byok', model_config_id: 'model', selection_state: 'needs_verification', model: null },
  ], subscription: noSubscription })
  view(); await screen.findByText('默认翻译模型当前不可用。')
  expect(api.startPrivateTranslation).not.toHaveBeenCalled()
})
it('reopens completed history with GET only and reports it to the article reader', async () => {
  vi.mocked(api.latestPrivateTranslation).mockResolvedValue(completed)
  const first = view(); await screen.findByRole('button', { name: '重新翻译' }); first.unmount()
  const second = view(); await screen.findByRole('button', { name: '重新翻译' })
  expect(second.changed).toHaveBeenCalledWith(completed)
  expect(api.startPrivateTranslation).not.toHaveBeenCalled()
  expect(api.retryPrivateTranslation).not.toHaveBeenCalled()
})
it('keeps history available when the inference gate closes', async () => {
  vi.mocked(models.listAITaskPreferences).mockRejectedValue(new models.ConnectionRequestError(403))
  vi.mocked(api.latestPrivateTranslation).mockResolvedValue(completed)
  const rendered = view(); await screen.findByText(/个人模型调用已关闭/)
  await waitFor(() => expect(rendered.changed).toHaveBeenCalledWith(completed))
  expect(screen.queryByRole('button')).toBeNull()
  expect(api.startPrivateTranslation).not.toHaveBeenCalled()
})
it('rejects oversized Unicode input without truncation or sending', async () => {
  view(7, '😀'.repeat(64001)); await screen.findByText(/文章过长/)
  await waitFor(() => expect(screen.getByRole('button', { name: '翻译为中文' })).toBeDisabled())
  expect(api.startPrivateTranslation).not.toHaveBeenCalled()
})
it('accepts the Unicode boundary without repeating model configuration or fee explanations', async () => {
  view(7, '😀'.repeat(64000)); await waitFor(() => expect(screen.getByRole('button', { name: '翻译为中文' })).toBeEnabled())
  expect(screen.queryByText(/长文最多|可能产生费用/)).toBeNull()
  expect(api.startPrivateTranslation).not.toHaveBeenCalled()
})
it('reconciles an unknown POST with GET and never automatically resubmits', async () => {
  vi.mocked(api.startPrivateTranslation).mockRejectedValue(new Error('lost'))
  view(); const start = await screen.findByRole('button', { name: '翻译为中文' }); await waitFor(() => expect(start).toBeEnabled()); fireEvent.click(start)
  await screen.findByRole('button', { name: '读取翻译状态' })
  fireEvent.click(screen.getByRole('button', { name: '读取翻译状态' }))
  expect(api.startPrivateTranslation).toHaveBeenCalledOnce()
  expect(api.retryPrivateTranslation).not.toHaveBeenCalled()
})
it('does not transfer a late result after switching viewers', async () => {
  let finish!: (value: api.PrivateTranslationTask) => void
  vi.mocked(api.startPrivateTranslation).mockImplementation(() => new Promise(resolve => { finish = resolve }))
  const rendered = view(); const start = await screen.findByRole('button', { name: '翻译为中文' }); await waitFor(() => expect(start).toBeEnabled()); fireEvent.click(start)
  await waitFor(() => expect(api.startPrivateTranslation).toHaveBeenCalledOnce())
  rendered.rerender(rendered.tree(8)); await act(async () => finish(completed))
  expect(rendered.changed).not.toHaveBeenCalledWith(completed)
})
it('known rejection requires another explicit action and never retries automatically', async () => {
  vi.mocked(api.startPrivateTranslation).mockRejectedValue(new WorkspaceError('invalid', 400))
  view(); const start = await screen.findByRole('button', { name: '翻译为中文' }); await waitFor(() => expect(start).toBeEnabled()); fireEvent.click(start)
  await screen.findByText(/请求未获接受/)
  expect(api.startPrivateTranslation).toHaveBeenCalledOnce()
  expect(api.retryPrivateTranslation).not.toHaveBeenCalled()
})
it('regeneration is a separate explicit new paid attempt', async () => {
  vi.mocked(api.latestPrivateTranslation).mockResolvedValue(completed)
  view(); const retry = await screen.findByRole('button', { name: '重新翻译' }); await waitFor(() => expect(retry).toBeEnabled())
  expect(api.retryPrivateTranslation).not.toHaveBeenCalled(); fireEvent.click(retry)
  await waitFor(() => expect(api.retryPrivateTranslation).toHaveBeenCalledOnce())
  expect(api.retryPrivateTranslation).toHaveBeenCalledWith(completed.task_id, 'model', expect.any(String), 7, expect.any(AbortSignal))
})
it('cancels the captured task generation and clears partial private content', async () => {
  const running = { ...completed, status: 'running', result: null } as api.PrivateTranslationTask
  vi.mocked(api.latestPrivateTranslation).mockResolvedValueOnce(running).mockResolvedValue({ ...running, status: 'cancelled', progress: '' })
  const rendered = view(); fireEvent.click(await screen.findByRole('button', { name: '取消翻译' }))
  await waitFor(() => expect(api.cancelPrivateTranslation).toHaveBeenCalledWith(completed.task_id, 1, 7, expect.any(AbortSignal)))
  await waitFor(() => expect(rendered.changed.mock.calls.some(([value]) => value?.status === 'cancelled' && value.progress === '' && value.result === null)).toBe(true))
})
it('receives read-only SSE progress and rejects foreign task frames without a paid send', async () => {
  const running = { ...completed, status: 'running', result: null, progress: '' } as api.PrivateTranslationTask
  vi.mocked(api.latestPrivateTranslation).mockResolvedValue(running)
  const listeners = new Map<string, (event: MessageEvent<string>) => void>()
  const close = vi.fn()
  vi.stubGlobal('EventSource', class { addEventListener(kind: string, handler: (event: MessageEvent<string>) => void) { listeners.set(kind, handler) } close = close })
  const rendered = view(); await screen.findByRole('button', { name: '全文翻译中' })
  await act(async () => { listeners.get('message')?.(new MessageEvent('message', { data: JSON.stringify({ ...running, progress: '## 新段落' }) })); await new Promise(resolve => requestAnimationFrame(resolve)) })
  expect(rendered.changed).toHaveBeenCalledWith(expect.objectContaining({ progress: '## 新段落' }))
  act(() => listeners.get('message')?.(new MessageEvent('message', { data: JSON.stringify({ ...running, task_id: 'foreign' }) })))
  expect(close).toHaveBeenCalled()
  expect(rendered.changed).not.toHaveBeenCalledWith(expect.objectContaining({ task_id: 'foreign' }))
  expect(api.startPrivateTranslation).not.toHaveBeenCalled()
  expect(api.retryPrivateTranslation).not.toHaveBeenCalled()
})

it('shows that a mostly-Chinese article was kept without a model call', async () => {
  if (completed.result === null) throw new Error('fixture')
  const skippedResult: api.PrivateTranslationResult = {
    ...completed.result, skipped_reason: 'mostly_chinese',
  }
  vi.mocked(api.latestPrivateTranslation).mockResolvedValue({
    ...completed,
    result: skippedResult,
  })
  view()
  expect(await screen.findByText('原文主要是中文，已保留全文，未调用模型翻译。')).toBeInTheDocument()
  expect(api.startPrivateTranslation).not.toHaveBeenCalled()
})
it('parses a mostly-Chinese skip and rejects an unknown skip reason', () => {
  if (completed.result === null) throw new Error('fixture')
  const parsed = api.parsePrivateTranslation({
    ...completed,
    result: { ...completed.result, skipped_reason: 'mostly_chinese' },
  })
  expect(parsed.result?.skipped_reason).toBe('mostly_chinese')
  expect(() => api.parsePrivateTranslation({
    ...completed,
    result: { ...completed.result, skipped_reason: 'title_only' },
  })).toThrow(/Invalid private translation result/)
})
it('resumes a queued task only on a click with its original identity and frozen model', async () => {
  const queued = { ...completed, status: 'queued', model_config_id: 'original-model', result: null, progress: '' } as api.PrivateTranslationTask
  vi.mocked(api.latestPrivateTranslation).mockResolvedValue(queued)
  view(); const resume = await screen.findByRole('button', { name: '继续翻译' }); await waitFor(() => expect(resume).toBeEnabled())
  expect(api.startPrivateTranslation).not.toHaveBeenCalled(); fireEvent.click(resume)
  await waitFor(() => expect(api.startPrivateTranslation).toHaveBeenCalledWith(1, 'original-model', queued.request_id, 7, expect.any(AbortSignal)))
})
