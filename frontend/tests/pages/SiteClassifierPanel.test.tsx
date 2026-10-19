import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { expect, it, vi } from 'vitest'
import { SiteClassifierPanel } from '@/pages/SmartGroupingWorkspace'
import { workspaceRequest, type SiteClassifier } from '@/services/workspaceApi'
vi.mock('@/services/workspaceApi', async original => ({
  ...await original<typeof import('@/services/workspaceApi')>(), workspaceRequest: vi.fn(),
}))
vi.mock('@/services/aiConnectionsApi', () => ({ listAITaskPreferences: vi.fn(async () => ({ revision: 0, preferences: [] })) }))
it('reads queue status without dispatch and lets an operator stop outstanding work', async () => {
  const config: SiteClassifier = {
    enabled: true, is_owner: true, daily_limit: 10, jobs: [], intake_requests: [], model_id: 'deepseek-chat',
    runtime: { feature_enabled: true, model_binding_valid: true, ready_to_dispatch: true,
      daily_used: 3, daily_remaining: 7, job_counts: { queued: 2, running: 1 }, expired_leases: 1,
      failed_dispatched_jobs: 0, next_retry_at: null },
  }
  vi.mocked(workspaceRequest).mockImplementation(async (_path, options) => {
    if (options?.method === 'PATCH') return { ...config, enabled: false, runtime: { ...config.runtime!, ready_to_dispatch: false,
      job_counts: { cancelled: 3 } } } as never
    return config as never
  })
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  render(<QueryClientProvider client={client}><MemoryRouter><SiteClassifierPanel viewer={1} /></MemoryRouter></QueryClientProvider>)
  await screen.findByText('后台模型授权与开关就绪')
  expect(screen.getByText(/今日已入队 3 \/ 10/)).toBeInTheDocument()
  expect(screen.getByText(/1 个任务运行已过期/)).toBeInTheDocument()
  expect(vi.mocked(workspaceRequest).mock.calls.filter(([, options]) => options?.method)).toHaveLength(0)
  fireEvent.click(screen.getByRole('button', { name: '刷新后台状态' }))
  await waitFor(() => expect(workspaceRequest).toHaveBeenCalledTimes(2))
  fireEvent.click(screen.getByRole('checkbox', { name: '开启全站新来源 AI 分类' }))
  fireEvent.click(screen.getByRole('button', { name: '保存站点设置' }))
  await screen.findByText('后台分类已关闭')
  const write = vi.mocked(workspaceRequest).mock.calls.find(([, options]) => options?.method === 'PATCH')
  expect(write?.[1]?.body).toMatchObject({ enabled: false, consent: false, daily_limit: 10 })
  expect(screen.getByText(/已取消 3/)).toBeInTheDocument()
})
