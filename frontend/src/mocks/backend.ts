import { getScenario } from './catalog.ts'
import { MOCK_VIEWER, MOCK_CSRF, capabilityFixture, detailFixture, groupFixtures, rootFixtures,
  sourceFixtures, statsFixture, subscriptionFixtures, summaryFixtures } from './fixtures.ts'

export interface AuditEntry { sequence: number; method: string; path: string; outcome: 'pending' | 'response' | 'aborted' | 'network-error'; status: number | null }
export interface BackendSnapshot { scenario: string; active: number; requests: AuditEntry[]; unhandled: string[] }
export interface ScenarioBackend {
  readonly scenario: string
  handle(request: Request): Promise<Response>
  reset(): void
  inspect(): BackendSnapshot
}
interface ReadState { is_read: boolean; version: number }
const isObject = (value: unknown): value is Record<string, unknown> => typeof value === 'object' && value !== null && !Array.isArray(value)
function response(body: unknown, status = 200, extra: Record<string, string> = {}): Response {
  return Response.json(body, { status, headers: { 'Cache-Control': 'private, no-store', 'X-NewsHub-Mock': 'scenario-v1', ...extra } })
}
function error(status: number, code: string, message: string, extra: Record<string, string> = {}): Response {
  // Envelope from backend/api/rss/http.py, not the teaching app's simplified format.
  return response({ error: { code, message, retryable: [429, 502, 503].includes(status) }, request_id: 'synthetic-request' }, status, extra)
}
async function objectBody(request: Request): Promise<Record<string, unknown> | null> {
  try { const body: unknown = await request.json(); return isObject(body) ? body : null } catch { return null }
}
function wait(ms: number, signal: AbortSignal): Promise<void> {
  signal.throwIfAborted()
  return new Promise((resolve, reject) => {
    const abort = () => { clearTimeout(timer); signal.removeEventListener('abort', abort); reject(signal.reason) }
    const timer = setTimeout(() => { signal.removeEventListener('abort', abort); resolve() }, ms)
    signal.addEventListener('abort', abort, { once: true })
  })
}

/** No fetch/axios/proxy calls here. Every instance is an isolated, synthetic backend. */
export function createScenarioBackend(id: string, options: { origin: string }): ScenarioBackend {
  const scenario = getScenario(id)
  const configuredOrigin = new URL(options.origin)
  if (!['http:', 'https:'].includes(configuredOrigin.protocol) || configuredOrigin.username || configuredOrigin.password) {
    throw new Error('Mock origin must be an HTTP(S) origin without credentials')
  }
  const origin = configuredOrigin.origin
  let epoch = 0
  let resetController = new AbortController()
  let active = 0
  let sequence = 0
  let listAttempts = 0
  let readAttempts = 0
  let conflictInjected = false
  let authenticated = scenario.identity === 'member' && scenario.capabilities === 'full'
  let preference: { scope: string; group_id: number | null } = { scope: 'all', group_id: null }
  let readStates = new Map<number, ReadState>()
  let readArticles = new Set<number>()
  let requests: AuditEntry[] = []
  let unhandled: string[] = []
  const missing = () => error(404, 'not_found', '文章不存在或不可访问。')
  const current = (newsId: number): ReadState => readStates.get(newsId) ?? { is_read: false, version: 0 }
  const unavailable = () => error(503, 'unavailable', '合成服务暂不可用。')

  async function route(request: Request, url: URL, signal: AbortSignal): Promise<Response> {
    const { pathname: path } = url
    const method = request.method.toUpperCase()
    if (url.origin !== origin) return error(403, 'mock_origin_denied', 'Mock 不接受其他来源，也不会转发请求。')
    if (method === 'GET' && path === '/api/capabilities/') {
      return scenario.capabilities === 'unavailable' ? unavailable() : response(capabilityFixture(scenario.capabilities === 'read-only'))
    }
    if (method === 'GET' && path === '/api/auth/csrf/') {
      // Never set/overwrite a real localhost CSRF cookie. This is not Django SessionAuthentication.
      return response({ csrfToken: MOCK_CSRF })
    }
    if (method === 'GET' && path === '/api/auth/me/') {
      if (scenario.capabilities === 'read-only') return error(403, 'public_read_only', '当前站点只允许阅读。')
      return authenticated ? response(MOCK_VIEWER) : error(401, 'not_authenticated', '请先登录。')
    }
    if (path.startsWith('/api/me/') || path === '/api/auth/logout/') {
      // PublicPolicyMiddleware precedes view authentication in the real backend.
      if (scenario.capabilities === 'read-only') return error(403, 'public_read_only', '当前站点只允许阅读。')
      const viewer = request.headers.get('X-Workspace-Viewer')
      if (!['GET', 'HEAD', 'OPTIONS'].includes(method) && viewer !== null && (!authenticated || viewer !== String(MOCK_VIEWER.id))) {
        return error(409, 'stale', '账号已变化，请重新操作。')
      }
      if (!authenticated) return error(401, 'not_authenticated', '请先登录。')
    }
    if (method === 'POST' && path === '/api/auth/logout/') {
      authenticated = false
      return response({})
    }
    if (method === 'GET' && path === '/api/categories/') return response([{ id: 201, name: '前端工程' }])
    if (method === 'GET' && path === '/api/sources/') return response(sourceFixtures())
    if (method === 'GET' && path === '/api/smart-channels/catalog/') {
      return response({ topics: [{ key: 'frontend', name: '前端工程', description: '合成分类' }], presets: [], sources: sourceFixtures() })
    }
    if (method === 'GET' && path === '/api/smart-channels/dashboard/') return response({ kind: 'latest', stories: [] })
    if (method === 'GET' && path === '/api/me/channel-subscriptions/') return response(subscriptionFixtures())
    if (method === 'GET' && path === '/api/me/channel-group-roots/') return response(rootFixtures())
    if (method === 'GET' && path === '/api/me/channel-groups/') return response(groupFixtures())
    if (method === 'GET' && path === '/api/me/smart-channels/settings/') {
      return response({ mode: 'off', bindings: {}, revision: 1, ai_available: false, match_existing: false, ai_enabled: false,
        ai_model_id: null, daily_limit: 0, summary: { pending: 0, suggested: 0, applied: 0 } })
    }
    if (method === 'GET' && path === '/api/me/news-preferences/') return response(preference)
    if (method === 'PATCH' && path === '/api/me/news-preferences/') {
      const body = await objectBody(request)
      signal.throwIfAborted()
      if (!body || !['all', 'subscribed', 'ungrouped', 'group'].includes(String(body.scope)) ||
        (body.group_id !== null && body.group_id !== 401) || (body.scope === 'group' && body.group_id !== 401)) {
        return error(400, 'invalid_input', '请求范围无效。')
      }
      preference = { scope: String(body.scope), group_id: body.group_id as number | null }
      return response(preference)
    }
    if (path === '/api/me/reading-stats/') {
      if (method === 'POST') {
        const body = await objectBody(request)
        signal.throwIfAborted()
        if (!body || !summaryFixtures().some(article => article.id === body.news_id)) return missing()
        readArticles.add(body.news_id as number)
        return response(statsFixture(readArticles.size))
      }
      if (method === 'GET') return response(statsFixture(readArticles.size))
    }
    if (method === 'GET' && path === '/api/news/') {
      listAttempts++
      if (scenario.list === 'slow') await wait(1500, signal)
      const search = (url.searchParams.get('search') ?? '').trim()
      if (scenario.list === 'race' && search) await wait(search.includes('旧') ? 1500 : 50, signal)
      signal.throwIfAborted()
      if (scenario.list === 'error' || (scenario.list === 'retry' && listAttempts <= 2)) return unavailable()
      if (scenario.list === 'network-error') return Response.error()
      if (scenario.list === 'rate-limited') return error(429, 'rate_limited', '请求过于频繁。', { 'Retry-After': '3' })
      const page = Number(url.searchParams.get('page') ?? 1)
      const pageSize = Number(url.searchParams.get('page_size') ?? 20)
      if (!Number.isSafeInteger(page) || page < 1 || !Number.isSafeInteger(pageSize) || pageSize < 1 || pageSize > 100) {
        return error(400, 'invalid_input', '分页参数无效。')
      }
      let rows = scenario.list === 'empty' ? [] : summaryFixtures()
      if (scenario.list === 'race' && search) {
        rows = [summaryFixtures()[search.includes('旧') ? 0 : 1]]
        const title = search.includes('旧') ? '场景测试：旧请求结果' : '场景测试：新请求结果'
        rows = rows.map(row => ({ ...row, title, title_zh: title }))
      } else if (search) {
        rows = rows.filter(row => `${row.title} ${row.summary} ${row.source_name}`.toLowerCase().includes(search.toLowerCase()))
      }
      const scope = url.searchParams.get('scope') ?? 'all'
      if (!['all', 'subscribed', 'ungrouped', 'group'].includes(scope)) return error(400, 'invalid_input', '资讯范围无效。')
      if (scope !== 'all') {
        if (!authenticated) return error(401, 'not_authenticated', '请先登录。')
        if (scope === 'group' && url.searchParams.get('group_id') !== '401') return error(404, 'not_found', '分组不存在。')
        rows = scope === 'ungrouped' ? [] : rows.filter(row => row.source === 101)
      }
      const region = url.searchParams.get('region')
      if (region) rows = rows.filter(row => row.source_region === region)
      const sourceIds = url.searchParams.get('source')?.split(',').map(Number)
      if (sourceIds) rows = rows.filter(row => sourceIds.includes(row.source))
      const categoryIds = url.searchParams.get('category')?.split(',').map(Number)
      if (categoryIds) rows = rows.filter(row => categoryIds.includes(row.category))
      const count = rows.length
      const results: unknown[] = rows.slice((page - 1) * pageSize, page * pageSize)
      if (scenario.list === 'malformed' && results.length) {
        const malformed: Record<string, unknown> = { ...(results[0] as Record<string, unknown>) }
        delete malformed.title
        results[0] = malformed
      }
      const pageUrl = (value: number) => { const params = new URLSearchParams(url.searchParams); params.set('page', String(value)); return `/api/news/?${params}` }
      return response({ count, next: page * pageSize < count ? pageUrl(page + 1) : null, previous: page > 1 ? pageUrl(page - 1) : null, results })
    }
    const detailMatch = path.match(/^\/api\/news\/(\d+)\/$/)
    if (method === 'GET' && detailMatch) {
      if (scenario.detail === 'missing') return missing()
      const detail = detailFixture(Number(detailMatch[1]), scenario.detail === 'summary-only')
      return detail ? response(detail) : missing()
    }
    const readMatch = path.match(/^\/api\/me\/news\/(\d+)\/read-state\/$/)
    if (readMatch) {
      const newsId = Number(readMatch[1])
      if (scenario.detail === 'missing' || !summaryFixtures().some(article => article.id === newsId)) return missing()
      if (method === 'GET') {
        readAttempts++
        if (scenario.read === 'load-retry' && readAttempts <= 2) return unavailable()
        return response(current(newsId))
      }
      if (method === 'PATCH') {
        const body = await objectBody(request)
        signal.throwIfAborted()
        const expected = body?.expected_version
        if (!body || Object.keys(body).some(key => key !== 'is_read' && key !== 'expected_version') || typeof body.is_read !== 'boolean' ||
          (expected !== undefined && expected !== null && (typeof expected !== 'number' || !Number.isSafeInteger(expected) || expected < 0))) {
          return error(400, 'invalid_input', 'is_read 须为布尔值，expected_version 须为非负整数。')
        }
        if (scenario.read === 'save-error') return unavailable()
        if (scenario.read === 'conflict' && !conflictInjected) {
          conflictInjected = true
          readStates.set(newsId, { is_read: true, version: 1 })
          return error(409, 'stale', '状态已改变，请刷新后重试。')
        }
        const previous = current(newsId)
        if (expected !== undefined && expected !== null && expected !== previous.version) return error(409, 'stale', '状态已改变，请刷新后重试。')
        const version = previous.version === 0 ? 1 : previous.is_read === body.is_read ? previous.version : previous.version + 1
        const next: ReadState = { is_read: body.is_read, version }
        readStates.set(newsId, next)
        return response(next)
      }
    }
    unhandled.push(`${method} ${path}`)
    unhandled = unhandled.slice(-200)
    return error(501, 'mock_unhandled', '该接口尚未建立场景；请求已阻止，未连接真实后端。')
  }
  return {
    scenario: id,
    async handle(request) {
      const generation = epoch
      const signal = AbortSignal.any([request.signal, resetController.signal])
      signal.throwIfAborted()
      const entry: AuditEntry = { sequence: ++sequence, method: request.method, path: new URL(request.url).pathname, outcome: 'pending', status: null }
      requests.push(entry); requests = requests.slice(-200); active++
      try {
        const result = await route(request, new URL(request.url), signal)
        signal.throwIfAborted()
        entry.status = result.status
        entry.outcome = result.type === 'error' ? 'network-error' : 'response'
        return result
      } catch (cause) {
        if (signal.aborted) { entry.outcome = 'aborted'; throw signal.reason }
        throw cause
      } finally {
        if (generation === epoch) active--
      }
    },
    reset() {
      resetController.abort(new DOMException('Scenario reset', 'AbortError'))
      resetController = new AbortController(); epoch++; active = 0; sequence = 0
      listAttempts = 0; readAttempts = 0; conflictInjected = false
      authenticated = scenario.identity === 'member' && scenario.capabilities === 'full'
      preference = { scope: 'all', group_id: null }
      readStates = new Map(); readArticles = new Set(); requests = []; unhandled = []
    },
    inspect() { return structuredClone({ scenario: id, active, requests, unhandled }) },
  }
}
