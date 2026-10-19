import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import PrivateTranslationPanel from '@/components/news-detail/PrivateTranslationPanel'
import { WorkspaceError } from '@/services/workspaceApi'
import * as models from '@/services/aiConnectionsApi'
import * as api from '@/services/privateTranslationApi'

vi.mock('@/services/aiConnectionsApi', async original => ({
  ...await original<typeof import('@/services/aiConnectionsApi')>(),
  listAIConnections: vi.fn(), listAIModels: vi.fn(),
}))
vi.mock('@/services/privateTranslationApi', async original => ({
  ...await original<typeof import('@/services/privateTranslationApi')>(),
  latestPrivateTranslation: vi.fn(), startPrivateTranslation: vi.fn(), cancelPrivateTranslation: vi.fn(), retryPrivateTranslation: vi.fn(),
}))
vi.mock('@/components/news-detail/MarkdownContent', () => ({ default: ({ content }: { content: string }) => <div>{content}</div> }))
const completed: api.PrivateTranslationTask = {
  task_id: '11111111-1111-4111-8111-111111111111', request_id: '22222222-2222-4222-8222-222222222222', news_id: 1, status: 'succeeded',
  generation: 1, retry_of: null, progress: '私有中文', error_code: '', model_config_id: 'model', target_language: 'zh', previous_result: null,
  result: { result_id: 4, task_id: '11111111-1111-4111-8111-111111111111',
    content: '私有中文', scope: 'private', provider: 'deepseek', model: 'Flash' },
}
function view(viewer = 7, sourceMarkdown = 'a'.repeat(100)) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  const tree = (id: number) => <QueryClientProvider client={client}><MemoryRouter>
    <PrivateTranslationPanel viewer={id} newsId={1} sourceRevision={1} sourceMarkdown={sourceMarkdown} />
  </MemoryRouter></QueryClientProvider>
  return { ...render(tree(viewer)), tree, client }
}
beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(models.listAIConnections).mockResolvedValue([
    { id: 'connection', is_enabled: true, key_saved: true, display_name: 'Mine' } as models.AIConnection,
  ])
  vi.mocked(models.listAIModels).mockResolvedValue([
    { id: 'model', model_id: 'deepseek-flash', display_name: 'Flash', has_trusted_route: true,
      article_chat_supported: true, capabilities: { text: 'supported', tools: 'unknown' } } as models.AIModel,
  ])
  vi.mocked(api.latestPrivateTranslation).mockResolvedValue(null)
  vi.mocked(api.startPrivateTranslation).mockResolvedValue(completed)
  vi.mocked(api.cancelPrivateTranslation).mockResolvedValue({
    task_id: completed.task_id, status: 'cancelled', error_code: 'translation_cancelled',
  })
  vi.mocked(api.retryPrivateTranslation).mockResolvedValue({
    ...completed, task_id: '33333333-3333-4333-8333-333333333333',
    request_id: '44444444-4444-4444-8444-444444444444', retry_of: completed.task_id,
    status: 'queued', result: null, previous_result: completed.result, progress: '',
  })
})
afterEach(cleanup)
describe('T05 private translation', () => {
  it('never submits on mount and requires explicit model and one-call consent', async () => {
    view()
    await screen.findByRole('option', { name: 'Mine · Flash' })
    const start = screen.getByRole('button', { name: '开始私有翻译' })
    expect(start).toBeDisabled()
    expect(api.startPrivateTranslation).not.toHaveBeenCalled()
    fireEvent.change(screen.getByRole('combobox', { name: '翻译模型' }), { target: { value: 'model' } })
    const consent = screen.getByRole('checkbox')
    fireEvent.click(consent)
    await waitFor(() => expect(start).toBeEnabled())
    fireEvent.click(start)
    fireEvent.click(start)
    await screen.findByText('私有翻译已完成')
    expect(api.startPrivateTranslation).toHaveBeenCalledOnce()
    expect(api.startPrivateTranslation).toHaveBeenCalledWith(1, 'model', expect.any(String), 7, expect.any(AbortSignal))
    expect(consent).not.toBeChecked()
    expect(screen.getByText('私有中文')).toBeInTheDocument()
  })
  it('recovers same result with GET only and never submits after reopening', async () => {
    vi.mocked(api.latestPrivateTranslation).mockResolvedValue(completed)
    const first = view()
    await screen.findByText('私有翻译已完成')
    first.unmount()
    view()
    await screen.findByText('私有翻译已完成')
    expect(screen.getByText(/私有结果 #4/)).toBeInTheDocument()
    expect(api.startPrivateTranslation).not.toHaveBeenCalled()
  })
  it('oversized article is rejected by the UI without truncation or send', async () => {
    view(7, 'a'.repeat(64001))
    await screen.findByRole('option', { name: 'Mine · Flash' })
    fireEvent.change(screen.getByRole('combobox', { name: '翻译模型' }), { target: { value: 'model' } })
    fireEvent.click(screen.getByRole('checkbox'))
    expect(screen.getByRole('button', { name: '开始私有翻译' })).toBeDisabled()
    expect(screen.getByText(/原文超过全文翻译上限/)).toBeInTheDocument()
    expect(api.startPrivateTranslation).not.toHaveBeenCalled()
  })
  it('unknown POST only reconciles GET and cannot automatically replay', async () => {
    vi.mocked(api.startPrivateTranslation).mockRejectedValue(new Error('lost response'))
    view()
    await screen.findByRole('option', { name: 'Mine · Flash' })
    fireEvent.change(screen.getByRole('combobox', { name: '翻译模型' }), { target: { value: 'model' } })
    fireEvent.click(screen.getByRole('checkbox'))
    fireEvent.click(screen.getByRole('button', { name: '开始私有翻译' }))
    await screen.findByText(/提交结果未知/)
    fireEvent.click(screen.getByRole('button', { name: '读取任务状态' }))
    expect(api.startPrivateTranslation).toHaveBeenCalledOnce()
    expect(screen.getByRole('button', { name: '开始私有翻译' })).toBeDisabled()
  })
  it('viewer switch ignores a previous late private POST result', async () => {
    let finish!: (task: api.PrivateTranslationTask) => void
    vi.mocked(api.startPrivateTranslation).mockImplementation(() => new Promise(resolve => { finish = resolve }))
    const rendered = view()
    await screen.findByRole('option', { name: 'Mine · Flash' })
    fireEvent.change(screen.getByRole('combobox', { name: '翻译模型' }), { target: { value: 'model' } })
    fireEvent.click(screen.getByRole('checkbox'))
    fireEvent.click(screen.getByRole('button', { name: '开始私有翻译' }))
    await waitFor(() => expect(api.startPrivateTranslation).toHaveBeenCalledOnce())
    rendered.rerender(rendered.tree(8))
    await screen.findByRole('option', { name: 'Mine · Flash' })
    expect(screen.queryByText('私有中文')).not.toBeInTheDocument()
    const model = screen.getByRole('combobox', { name: '翻译模型' })
    expect(model).toHaveValue('')
    fireEvent.change(model, { target: { value: 'model' } })
    const consent = screen.getByRole('checkbox')
    expect(consent).not.toBeChecked()
    expect(screen.getByRole('button', { name: '开始私有翻译' })).toBeDisabled()
    await act(async () => finish(completed))
    expect(screen.queryByText('私有中文')).not.toBeInTheDocument()
  })
  it('known admission rejection is actionable and allows fresh explicit consent, never auto retries', async () => {
    vi.mocked(api.startPrivateTranslation).mockRejectedValue(new WorkspaceError('rejected', 400))
    view()
    await screen.findByRole('option', { name: 'Mine · Flash' })
    fireEvent.change(screen.getByRole('combobox', { name: '翻译模型' }), { target: { value: 'model' } })
    fireEvent.click(screen.getByRole('checkbox'))
    fireEvent.click(screen.getByRole('button', { name: '开始私有翻译' }))
    await screen.findByText(/请求未获接受/)
    expect(screen.queryByText(/提交结果未知/)).not.toBeInTheDocument()
    expect(screen.getByText(/原文可能超出预算，或包含暂不支持的引用围栏、列表行内围栏或四格及以上缩进围栏/)).toBeInTheDocument()
    expect(api.startPrivateTranslation).toHaveBeenCalledOnce()
    fireEvent.click(screen.getByRole('checkbox'))
    await waitFor(() => expect(screen.getByRole('button', { name: '开始私有翻译' })).toBeEnabled())
    expect(api.startPrivateTranslation).toHaveBeenCalledOnce()
  })
  it('counts Unicode codepoints consistently with backend and enforces exact boundary', async () => {
    const boundary = view(7, '😀'.repeat(64000))
    await screen.findByRole('option', { name: 'Mine · Flash' })
    expect(screen.queryByText(/原文超过全文翻译上限/)).not.toBeInTheDocument()
    boundary.unmount()
    view(7, '😀'.repeat(64001))
    expect(screen.getByText(/原文超过全文翻译上限/)).toBeInTheDocument()
  })
  it('admits bounded long source only with explicit multi-request fee consent', async () => {
    view(7, 'A'.repeat(5000) + '\n\n' + 'B'.repeat(5000))
    await screen.findByRole('option', { name: 'Mine · Flash' })
    expect(screen.getByText(/长文最多可能产生 8 次服务商费用/)).toBeInTheDocument()
    fireEvent.change(screen.getByRole('combobox', { name: '翻译模型' }), { target: { value: 'model' } })
    const start = screen.getByRole('button', { name: '开始私有翻译' })
    expect(start).toBeDisabled()
    fireEvent.click(screen.getByRole('checkbox'))
    await waitFor(() => expect(start).toBeEnabled())
    fireEvent.click(start)
    await screen.findByText('私有翻译已完成')
    expect(api.startPrivateTranslation).toHaveBeenCalledOnce()
  })
  it('explains dispatched long requests may still be billed after failure and does not replay', async () => {
    vi.mocked(api.latestPrivateTranslation).mockResolvedValue({
      ...completed, status: 'failed', result: null, progress: '第一段已验证。\n\n',
      error_code: 'translation_failed',
    } as api.PrivateTranslationTask)
    view(7, 'A'.repeat(5000) + '\n\n' + 'B'.repeat(5000))
    await screen.findByText(/本次翻译未完成/)
    expect(screen.getByText(/已派发的服务商请求仍可能产生费用/)).toBeInTheDocument()
    expect(screen.getByText(/长文最多可能产生 8 次服务商费用/)).toBeInTheDocument()
    fireEvent.change(screen.getByRole('combobox', { name: '翻译模型' }), { target: { value: 'model' } })
    const consent = screen.getByRole('checkbox', { name: /长文最多顺序发送 8 次个人模型请求/ })
    expect(consent).not.toBeChecked()
    expect(api.startPrivateTranslation).not.toHaveBeenCalled()
    expect(api.retryPrivateTranslation).not.toHaveBeenCalled()
  })
  it('cancels only through the explicit action and retains uncertain billing warning', async () => {
    const running: api.PrivateTranslationTask = {
      ...completed, status: 'running', generation: 7, result: null, progress: '未完成片段',
    }
    const cancelled: api.PrivateTranslationCancelReceipt = {
      task_id: running.task_id, status: 'cancelled', error_code: 'translation_cancelled',
    }
    const cancelledTask: api.PrivateTranslationTask = {
      ...running, status: 'cancelled', error_code: 'translation_cancelled', progress: '',
    }
    vi.mocked(api.latestPrivateTranslation).mockResolvedValueOnce(running).mockResolvedValue(cancelledTask)
    vi.mocked(api.cancelPrivateTranslation).mockResolvedValue(cancelled)
    view()
    await screen.findByText('正在翻译，以下内容尚未完成')
    expect(screen.getByRole('button', { name: '明确取消任务' })).toBeEnabled()
    expect(screen.getByText(/取消不会保证已派发请求停止或免除费用/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '明确取消任务' }))
    await screen.findByText(/任务已取消/)
    expect(screen.queryByText('未完成片段')).not.toBeInTheDocument()
    expect(api.cancelPrivateTranslation).toHaveBeenCalledOnce()
    expect(api.cancelPrivateTranslation).toHaveBeenCalledWith(running.task_id, 7, 7, expect.any(AbortSignal))
    expect(api.startPrivateTranslation).not.toHaveBeenCalled()
    expect(api.retryPrivateTranslation).not.toHaveBeenCalled()
  })
  it('requires fresh consent for an explicit new task and keeps the old result visible', async () => {
    const failed: api.PrivateTranslationTask = {
      ...completed, status: 'failed', result: null, previous_result: null, progress: '',
    }
    const prior = { ...completed.result!, task_id: completed.task_id }
    vi.mocked(api.latestPrivateTranslation).mockResolvedValue({ ...failed, previous_result: prior })
    view()
    await screen.findByText('本次翻译未完成。已派发的服务商请求仍可能产生费用，不会自动重复收费请求。')
    expect(screen.getByText('此前成功的私有译文（结果 #4）')).toBeInTheDocument()
    fireEvent.change(screen.getByRole('combobox', { name: '翻译模型' }), { target: { value: 'model' } })
    const retry = screen.getByRole('button', { name: '重新生成（新任务）' })
    expect(retry).toBeDisabled()
    fireEvent.click(screen.getByRole('checkbox'))
    await waitFor(() => expect(retry).toBeEnabled())
    fireEvent.click(retry)
    await screen.findByText('任务：33333333-3333-4333-8333-333333333333')
    expect(api.retryPrivateTranslation).toHaveBeenCalledOnce()
    expect(api.retryPrivateTranslation).toHaveBeenCalledWith(failed.task_id, 'model', expect.any(String), 7, expect.any(AbortSignal))
    expect(api.startPrivateTranslation).not.toHaveBeenCalled()
    expect(screen.getByText('此前成功的私有译文（结果 #4）')).toBeInTheDocument()
    expect(screen.getByText('私有中文')).toBeInTheDocument()
  })
  it('explicitly recovers a queued retry through its parent and same idempotency key', async () => {
    const queuedRetry: api.PrivateTranslationTask = {
      ...completed,
      task_id: '33333333-3333-4333-8333-333333333333',
      request_id: '44444444-4444-4444-8444-444444444444',
      status: 'queued', retry_of: completed.task_id, result: null,
      previous_result: completed.result, progress: '',
    }
    vi.mocked(api.latestPrivateTranslation).mockResolvedValue(queuedRetry)
    view()
    await screen.findByText('任务：33333333-3333-4333-8333-333333333333')
    fireEvent.click(screen.getByRole('checkbox'))
    fireEvent.click(screen.getByRole('button', { name: '恢复排队任务' }))
    await waitFor(() => expect(api.retryPrivateTranslation).toHaveBeenCalledOnce())
    expect(api.retryPrivateTranslation).toHaveBeenCalledWith(
      completed.task_id, 'model', queuedRetry.request_id, 7, expect.any(AbortSignal),
    )
    expect(api.startPrivateTranslation).not.toHaveBeenCalled()
  })
  it('rejects malformed terminal and partial result DTOs', () => {
    expect(() => api.parsePrivateTranslation({ ...completed, result: null })).toThrow()
    expect(() => api.parsePrivateTranslation({ ...completed, status: 'running' })).toThrow()
    expect(() => api.parsePrivateTranslation({ ...completed, generation: 0 })).toThrow()
    expect(() => api.parsePrivateTranslation({ ...completed, previous_result: { ...completed.result, scope: 'shared' } })).toThrow()
    expect(() => api.parsePrivateTranslation({ ...completed, result: { ...completed.result, scope: 'shared' } })).toThrow()
  })
})
