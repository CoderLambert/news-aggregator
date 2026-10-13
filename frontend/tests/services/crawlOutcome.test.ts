import { describe, expect, it } from 'vitest'
import { crawlBatchDisplay, crawlRunDisplayStatus, crawlRunReason } from '@/services/crawlOutcome'
import type { CrawlRun, CrawlBatch } from '@/types/crawlerAdmin'
const run = (overrides: Partial<CrawlRun> = {}): CrawlRun => ({
  id: 'one', batchId: 'batch', spiderName: 'devto', targetName: 'DEV', status: 'failed',
  queuedAt: '', startedAt: null, heartbeatAt: null, finishedAt: null, durationSeconds: 1,
  exitCode: 0, items: 310, responses: 7, errors: 2, httpStatuses: { '200': 7 },
  finishReason: 'finished', safeError: '来源结果：partial', retryOf: null, latestRetryId: null,
  latestRetryStatus: null, cancelRequestedAt: null, entriesCommitted: 310, outcome: 'partial', ...overrides,
})
describe('crawl result presentation', () => {
  it('shows partial success without changing historical status', () => {
    const value = run()
    expect(crawlRunDisplayStatus(value)).toBe('partial')
    expect(value.status).toBe('failed')
    expect(crawlRunReason(value)).toContain('已入库内容保留')
  })
  it('distinguishes waiting, network failure and process failure', () => {
    expect(crawlRunDisplayStatus(run({ entriesCommitted: 0, outcome: 'deferred' }))).toBe('deferred')
    expect(crawlRunDisplayStatus(run({ entriesCommitted: 0, outcome: 'network_error' }))).toBe('network_error')
    expect(crawlRunDisplayStatus(run({ exitCode: 1 }))).toBe('failed')
  })
  it('counts partial results separately from failures and deferrals', () => {
    const batch = { status: 'failed', runs: [run(), run({ entriesCommitted: 0, outcome: 'deferred' }), run({ entriesCommitted: 0, outcome: 'network_error' })] } as CrawlBatch
    expect(crawlBatchDisplay(batch)).toEqual({ status: 'partial', counts: { succeeded: 0, partial: 1, deferred: 1, failed: 1, cancelled: 0 } })
  })
  it('retains active state and precise errors', () => {
    const value = run({ safeError: 'HTTP 405：未获得有效 Feed。' })
    expect(crawlRunReason(value)).toBe(value.safeError)
    expect(crawlBatchDisplay({ status: 'running', runs: [value] } as CrawlBatch).status).toBe('running')
  })
})
