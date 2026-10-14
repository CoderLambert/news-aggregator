import { describe, expect, it } from 'vitest'
import { parseCrawlerReadiness } from '@/services/crawlerAdminApi'

describe('crawler readiness parsing', () => {
  it('decodes bounded safe sources and keeps worker heartbeat separate from success', () => {
    const snapshot = parseCrawlerReadiness({
      scheduler: { configured: true, enabled: false },
      workers: { crawler: { online: true }, search_index: { online: false } },
      sources: [
        { source_key: 'bbc', display_name: 'BBC', registered: true, supported: true,
          enabled: true, state: 'scheduler_paused', suggested_action: 'review_scheduler_switch',
          last_result: 'succeeded', last_feed_success_at: null, next_poll_at: null },
        { source_key: 'unknown', display_name: '', state: 'bogus' },
      ],
    })
    expect(snapshot.crawlerWorkerOnline).toBe(true)
    expect(snapshot.schedulerEnabled).toBe(false)
    expect(snapshot.sources).toHaveLength(1)
    expect(snapshot.sources[0].state).toBe('scheduler_paused')
  })
})
