import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, expect, it, vi } from 'vitest'
import AIUsageSection from '@/components/workspace/AIUsageSection'
import { listAIUsage, type AIUsage } from '@/services/aiConnectionsApi'
vi.mock('@/services/aiConnectionsApi', () => ({ listAIUsage: vi.fn() }))
beforeEach(() => vi.resetAllMocks())
const data: AIUsage = {
  summary: { calls: 1, input_tokens: null, output_tokens: null, input_tokens_unknown_calls: 1, output_tokens_unknown_calls: 1 },
  attempts: [{ id: 'one', source: 'business', task_kind: 'article_qa', model_id: 'private-model-A', provider_id: 'deepseek',
    status: 'unknown', input_tokens: null, output_tokens: null, latency_ms: null, created_at: '2026-10-20T00:00:00Z' }],
  has_more: false,
}
it('shows unknown usage without inventing zero tokens and refreshes only the read endpoint', async () => {
  vi.mocked(listAIUsage).mockResolvedValue(data)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><AIUsageSection viewer={1} /></QueryClientProvider>)
  expect(await screen.findByText('未知 / 未知')).toBeInTheDocument()
  expect(screen.getByText('结果未知')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: '刷新记录' }))
  await waitFor(() => expect(listAIUsage).toHaveBeenCalledTimes(2))
})
it('removes the previous viewer records while the next viewer response is pending', async () => {
  vi.mocked(listAIUsage).mockResolvedValueOnce(data)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const view = render(<QueryClientProvider client={client}><AIUsageSection viewer={1} /></QueryClientProvider>)
  await screen.findByText(/private-model-A/)
  let resolve!: (value: AIUsage) => void
  vi.mocked(listAIUsage).mockImplementationOnce(() => new Promise(done => { resolve = done }))
  view.rerender(<QueryClientProvider client={client}><AIUsageSection viewer={2} /></QueryClientProvider>)
  expect(screen.queryByText(/private-model-A/)).not.toBeInTheDocument()
  await act(async () => resolve({ ...data, attempts: [] }))
  expect(await screen.findByText(/暂无调用记录/)).toBeInTheDocument()
})
