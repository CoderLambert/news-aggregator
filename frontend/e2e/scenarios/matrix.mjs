// Acceptance requirements, independent of mock catalog/fixtures/implementation.
// Every row must describe an observable user journey, not just an HTTP code.
/** @type {readonly {id: string, path: string, journey: string, status?: number, probe?: string}[]} */
export const scenarioMatrix = Object.freeze([
  { id: 'normal', path: '/', journey: 'open-and-save' },
  { id: 'news-empty', path: '/', journey: 'empty-list' },
  { id: 'news-error', path: '/', journey: 'list-error', status: 503 },
  { id: 'news-retry', path: '/', journey: 'manual-retry' },
  { id: 'news-slow', path: '/', journey: 'slow-list' },
  { id: 'news-network-error', path: '/', journey: 'list-error', status: 0 },
  { id: 'news-malformed', path: '/', journey: 'list-error', status: 200 },
  { id: 'news-rate-limited', path: '/', journey: 'list-error', status: 429 },
  { id: 'search-race', path: '/', journey: 'search-race' },
  { id: 'detail-not-found', path: '/news/910001', journey: 'detail-error' },
  { id: 'summary-only', path: '/news/910001', journey: 'no-body' },
  { id: 'read-save-error', path: '/news/910001', journey: 'failed-save' },
  { id: 'read-conflict', path: '/news/910001', journey: 'conflict-recovery' },
  { id: 'read-load-retry', path: '/news/910001', journey: 'read-retry' },
  { id: 'auth-expired', path: '/news/910001', journey: 'no-personal-write', probe: '/api/auth/me/', status: 401 },
  { id: 'read-only', path: '/news/910001', journey: 'no-personal-write', probe: '/api/capabilities/', status: 200 },
  { id: 'capabilities-unavailable', path: '/news/910001', journey: 'no-personal-write', probe: '/api/capabilities/', status: 503 },
])
