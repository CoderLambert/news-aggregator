import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('axios', () => ({ default: {
  create: () => ({ get: mocks.get, interceptors: { request: { use: vi.fn() } } }),
} }))
vi.mock('@/services/api', () => ({ fetchCsrfToken: vi.fn() }))

import { fetchArticleFetchDashboard } from '@/services/articleFetchAdminApi'

beforeEach(() => vi.clearAllMocks())

describe('article fetch metric response parsing', () => {
  it('retains validated, commit conflicts and physical HTTP evidence', async () => {
    mocks.get.mockResolvedValue({ data: {
      summary: { total: 2, success: 0, failed: 1, success_rate: 0 },
      recent_events: [{ id: 1, outcome: 'validated', persistence_outcome: 'persistence_conflict',
        logical_outcome: 'persistence_conflict', physical_requests: 2, http_statuses: [302, 200],
        retry_after_at: null }, { id: 2, outcome: 'failed', persistence_outcome: 'not_attempted',
        logical_outcome: 'rate_limited', physical_requests: 1, http_statuses: [429],
        retry_after_at: '2026-10-13T02:02:00Z' }],
    } })
    const signal = new AbortController().signal
    const dashboard = await fetchArticleFetchDashboard(signal)
    expect(mocks.get).toHaveBeenCalledWith('/dashboard/?days=7', { signal })
    expect(dashboard.summary.success).toBe(0)
    expect(dashboard.recentEvents[0]).toMatchObject({ outcome: 'validated', persistenceOutcome: 'persistence_conflict',
      logicalOutcome: 'persistence_conflict', physicalRequests: 2, httpStatuses: [302, 200] })
    expect(dashboard.recentEvents[1]).toMatchObject({ physicalRequests: 1, httpStatuses: [429],
      retryAfterAt: '2026-10-13T02:02:00Z' })
  })

  it('preserves old success as unknown persistence and default zero HTTP evidence', async () => {
    mocks.get.mockResolvedValue({ data: { summary: {}, recent_events: [{ id: 3, outcome: 'success' }] } })
    const dashboard = await fetchArticleFetchDashboard()
    expect(dashboard.recentEvents[0]).toMatchObject({ outcome: 'success', persistenceOutcome: 'not_attempted',
      physicalRequests: 0, httpStatuses: [], retryAfterAt: null })
  })
})
