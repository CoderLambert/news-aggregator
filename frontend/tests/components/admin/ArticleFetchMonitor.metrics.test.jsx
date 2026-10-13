import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({ dashboard: null }))
vi.mock('@tanstack/react-query', () => ({
  queryOptions: (options) => options,
  useQuery: () => ({ data: mocks.dashboard, isLoading: false, isError: false, refetch: vi.fn() }),
  useMutation: () => ({ isPending: false, mutate: vi.fn() }),
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
}))
vi.mock('@/services/articleFetchAdminApi', () => ({
  createJinaPolicy: vi.fn(), updateJinaPolicy: vi.fn(), fetchArticleFetchDashboard: vi.fn(),
}))

import ArticleFetchMonitorSection from '@/components/admin/ArticleFetchMonitorSection'

const event = (id, changes) => ({
  id, newsId: id, domain: `metrics-${id}.example`, outcome: 'validated',
  provider: 'synthetic', failureCodes: [], qualityScore: 1, contentLength: 500,
  elapsedMs: 12, createdAt: '2026-10-13T02:00:00Z',
  persistenceOutcome: 'not_attempted', logicalOutcome: 'validated',
  physicalRequests: 0, httpStatuses: [], retryAfterAt: null, ...changes,
})

function renderMonitor(events) {
  mocks.dashboard.recentEvents = events
  render(<MemoryRouter><ArticleFetchMonitorSection /></MemoryRouter>)
}

function eventRow(id) {
  return within(screen.getByRole('link', { name: `新闻 #${id}` }).closest('tr'))
}

beforeEach(() => {
  mocks.dashboard = {
    windowDays: 7, retentionDays: 30,
    summary: { total: 6, success: 1, failed: 1, successRate: 1 / 6, unresolvedArticles: 2 },
    policies: [], domains: [], topFailureCodes: [], providers: [], recentEvents: [], serverTime: '',
  }
})

describe('article fetch ingestion metrics', () => {
  it('keeps validation, saved content, no-op and lost commits separate', () => {
    renderMonitor([
      event(1, {}), event(2, { persistenceOutcome: 'committed' }),
      event(3, { persistenceOutcome: 'noop' }), event(4, { persistenceOutcome: 'persistence_conflict' }),
    ])
    expect(eventRow(1).getByText('验证通过，未提交')).toBeInTheDocument()
    expect(eventRow(1).queryByText('正文已提交')).not.toBeInTheDocument()
    expect(eventRow(2).getByText('正文已提交')).toBeInTheDocument()
    expect(eventRow(3).getByText('正文未变')).toBeInTheDocument()
    expect(eventRow(4).getByText('提交冲突')).toBeInTheDocument()
    expect(eventRow(4).queryByText('正文已提交')).not.toBeInTheDocument()
  })

  it('does not relabel historical or unbound diagnostic success as saved content', () => {
    renderMonitor([event(1, { outcome: 'success' }), event(2, { outcome: 'legacy_validated' })])
    expect(eventRow(1).getByText('历史成功，提交未知')).toBeInTheDocument()
    expect(eventRow(2).getByText('诊断验证通过')).toBeInTheDocument()
    expect(eventRow(1).queryByText('正文已提交')).not.toBeInTheDocument()
    expect(eventRow(2).queryByText('正文已提交')).not.toBeInTheDocument()
  })

  it('shows zero-send budget deferral and actual redirect/429 requests with cooldown', () => {
    renderMonitor([
      event(1, { outcome: 'failed', logicalOutcome: 'budget_deferred' }),
      event(2, { outcome: 'failed', logicalOutcome: 'rate_limited', physicalRequests: 2,
        httpStatuses: [302, 429], retryAfterAt: '2026-10-13T02:02:00Z' }),
    ])
    expect(eventRow(1).getByText('预算延期')).toBeInTheDocument()
    expect(eventRow(1).getByText('HTTP — · 0 次请求')).toBeInTheDocument()
    expect(eventRow(2).getByText(/HTTP 302, 429 · 2 次请求 · 冷却至/)).toBeInTheDocument()
  })
})
