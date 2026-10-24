import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createScenarioBackend } from '../../src/mocks/backend.ts'
import { scenarios } from '../../src/mocks/catalog.ts'

const origin = 'http://127.0.0.1:9530'
const articleId = 910001
const readPath = `/api/me/news/${articleId}/read-state/`
function request(path, method = 'GET', body, headers = {}, signal) {
  return new Request(origin + path, {
    method, signal,
    headers: { ...(body === undefined ? {} : { 'Content-Type': 'application/json' }), ...headers },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  })
}
const listPath = '/api/news/?representation=summary&page=1&page_size=20'
const patch = (body, headers) => request(readPath, 'PATCH', body, headers)
const json = async response => ({ status: response.status, data: await response.json() })

test('unknown scenario is rejected rather than silently using normal', () => {
  assert.throws(() => createScenarioBackend('typo', { origin }), /Unknown scenario/)
})
test('registry IDs are unique', () => {
  assert.equal(new Set(scenarios.map(s => s.id)).size, scenarios.length)
})
test('normal uses summary DTOs, not detail bodies', async () => {
  const backend = createScenarioBackend('normal', { origin })
  const response = await backend.handle(request(listPath))
  const body = await response.json()
  assert.equal(response.status, 200)
  assert.equal(body.count, 2)
  assert.equal(body.results[0].id, 910001)
  assert.equal('full_content' in body.results[0], false)
  assert.equal('content' in body.results[0], false)
  assert.equal(response.headers.get('X-NewsHub-Mock'), 'scenario-v1')
})
test('pagination returns distinct rows and stable relative next/previous URLs', async () => {
  const backend = createScenarioBackend('normal', { origin })
  const first = await (await backend.handle(request('/api/news/?page_size=1'))).json()
  assert.equal(first.count, 2)
  assert.equal(first.results.length, 1)
  const next = await (await backend.handle(request(first.next))).json()
  assert.equal(next.results[0].id, 910002)
  assert.equal(next.next, null)
  assert.ok(next.previous.startsWith('/api/news/'))
})
test('invalid pagination is not silently accepted', async () => {
  const backend = createScenarioBackend('normal', { origin })
  for (const query of ['page=-1', 'page_size=0', 'page=1.5', 'page_size=999']) {
    assert.equal((await backend.handle(request('/api/news/?' + query))).status, 400)
  }
})
test('empty list is a valid 200 response', async () => {
  const backend = createScenarioBackend('news-empty', { origin })
  assert.deepEqual(await json(await backend.handle(request(listPath))), {
    status: 200, data: { count: 0, next: null, previous: null, results: [] },
  })
})
test('manual retry scenario accounts for the production automatic retry', async () => {
  const backend = createScenarioBackend('news-retry', { origin })
  const statuses = []
  for (let i = 0; i < 3; i++) statuses.push((await backend.handle(request(listPath))).status)
  assert.deepEqual(statuses, [503, 503, 200])
  backend.reset()
  assert.equal((await backend.handle(request(listPath))).status, 503)
})
test('network error remains a network failure, not a 500 JSON response', async () => {
  const backend = createScenarioBackend('news-network-error', { origin })
  assert.equal((await backend.handle(request(listPath))).type, 'error')
})
test('malformed contract scenario deliberately omits a required field', async () => {
  const backend = createScenarioBackend('news-malformed', { origin })
  const body = await (await backend.handle(request(listPath))).json()
  assert.equal('title' in body.results[0], false)
})
test('detail missing is 404', async () => {
  const backend = createScenarioBackend('detail-not-found', { origin })
  assert.equal((await backend.handle(request(`/api/news/${articleId}/`))).status, 404)
})
test('summary-only never contains the restricted body', async () => {
  const backend = createScenarioBackend('summary-only', { origin })
  const body = await (await backend.handle(request(`/api/news/${articleId}/`))).json()
  assert.equal(body.reading_policy, 'rss_summary_only')
  assert.equal(body.body_access_granted, false)
  assert.equal(body.full_content, '')
  assert.equal(body.has_full_content, false)
})
test('read state matches backend v0 -> v1 -> idempotent v1 -> v2', async () => {
  const backend = createScenarioBackend('normal', { origin })
  assert.deepEqual(await (await backend.handle(request(readPath))).json(), { is_read: false, version: 0 })
  const first = await (await backend.handle(patch({ is_read: true, expected_version: 0 }))).json()
  assert.deepEqual(first, { is_read: true, version: 1 })
  const repeated = await (await backend.handle(patch({ is_read: true, expected_version: 1 }))).json()
  assert.deepEqual(repeated, first)
  const last = await (await backend.handle(patch({ is_read: false, expected_version: 1 }))).json()
  assert.deepEqual(last, { is_read: false, version: 2 })
})
test('creating an explicit unread row still creates version 1', async () => {
  const backend = createScenarioBackend('normal', { origin })
  assert.deepEqual(await (await backend.handle(patch({ is_read: false, expected_version: 0 }))).json(), { is_read: false, version: 1 })
})
test('missing/null expected_version retains the current Python contract', async () => {
  const backend = createScenarioBackend('normal', { origin })
  assert.equal((await backend.handle(patch({ is_read: true }))).status, 200)
  assert.equal((await backend.handle(patch({ is_read: false, expected_version: null }))).status, 200)
})
test('stale version returns the actual RSS envelope and does not write', async () => {
  const backend = createScenarioBackend('normal', { origin })
  await backend.handle(patch({ is_read: true, expected_version: 0 }))
  const response = await backend.handle(patch({ is_read: false, expected_version: 0 }))
  const body = await response.json()
  assert.equal(response.status, 409)
  assert.equal(body.error.code, 'stale')
  assert.equal(body.error.retryable, false)
  assert.equal(typeof body.request_id, 'string')
  assert.deepEqual(await (await backend.handle(request(readPath))).json(), { is_read: true, version: 1 })
})
test('two writes from v0 cannot both succeed', async () => {
  const backend = createScenarioBackend('normal', { origin })
  const results = await Promise.all([true, false].map(is_read => backend.handle(patch({ is_read, expected_version: 0 }))))
  assert.deepEqual(results.map(r => r.status).sort(), [200, 409])
})
test('different backend instances do not share state', async () => {
  const a = createScenarioBackend('normal', { origin })
  const b = createScenarioBackend('normal', { origin })
  await a.handle(patch({ is_read: true, expected_version: 0 }))
  assert.deepEqual(await (await b.handle(request(readPath))).json(), { is_read: false, version: 0 })
})
test('articles have independent read states', async () => {
  const backend = createScenarioBackend('normal', { origin })
  await backend.handle(patch({ is_read: true, expected_version: 0 }))
  assert.deepEqual(await (await backend.handle(request('/api/me/news/910002/read-state/'))).json(), { is_read: false, version: 0 })
})
test('save failure never mutates read state', async () => {
  const backend = createScenarioBackend('read-save-error', { origin })
  assert.equal((await backend.handle(patch({ is_read: true, expected_version: 0 }))).status, 503)
  assert.deepEqual(await (await backend.handle(request(readPath))).json(), { is_read: false, version: 0 })
})
test('conflict is a business sequence, not an unconditional 409', async () => {
  const backend = createScenarioBackend('read-conflict', { origin })
  assert.equal((await backend.handle(patch({ is_read: true, expected_version: 0 }))).status, 409)
  const latest = await (await backend.handle(request(readPath))).json()
  assert.deepEqual(latest, { is_read: true, version: 1 })
  assert.equal((await backend.handle(patch({ is_read: false, expected_version: latest.version }))).status, 200)
})
test('read fetch retry fails twice then recovers', async () => {
  const backend = createScenarioBackend('read-load-retry', { origin })
  const statuses = []
  for (let i = 0; i < 3; i++) statuses.push((await backend.handle(request(readPath))).status)
  assert.deepEqual(statuses, [503, 503, 200])
})
for (const [label, body] of [
  ['boolean coercion', { is_read: 'true' }], ['negative version', { is_read: true, expected_version: -1 }],
  ['boolean version', { is_read: true, expected_version: true }], ['unknown field', { is_read: true, owner: 2 }],
  ['array body', []], ['null body', null], ['unsafe integer', { is_read: true, expected_version: Number.MAX_SAFE_INTEGER + 1 }],
]) {
  test(`invalid read write: ${label}`, async () => {
    const backend = createScenarioBackend('normal', { origin })
    assert.equal((await backend.handle(patch(body))).status, 400)
    assert.deepEqual(await (await backend.handle(request(readPath))).json(), { is_read: false, version: 0 })
  })
}
test('expired identity cannot read or write personal state', async () => {
  const backend = createScenarioBackend('auth-expired', { origin })
  assert.equal((await backend.handle(request('/api/auth/me/'))).status, 401)
  assert.equal((await backend.handle(request(readPath))).status, 401)
  assert.equal((await backend.handle(patch({ is_read: true }))).status, 401)
})
test('read-only disables account capability and rejects writes', async () => {
  const backend = createScenarioBackend('read-only', { origin })
  const caps = await (await backend.handle(request('/api/capabilities/'))).json()
  assert.equal(caps.site_mode, 'read_only')
  assert.equal(caps.features.accounts.enabled, false)
  assert.notEqual((await backend.handle(patch({ is_read: true }))).status, 200)
})
test('unknown API is an audited 501; no generic success fallback', async () => {
  const backend = createScenarioBackend('normal', { origin })
  assert.equal((await backend.handle(request('/api/not-implemented/', 'POST', {}))).status, 501)
  assert.equal(backend.inspect().unhandled.length, 1)
})
test('cross-origin Request is rejected, not proxied', async () => {
  const backend = createScenarioBackend('normal', { origin })
  assert.equal((await backend.handle(new Request('https://news.lambert.host/api/news/'))).status, 403)
})
test('aborted delayed request is rejected without a response commit', async () => {
  const backend = createScenarioBackend('news-slow', { origin })
  const controller = new AbortController()
  const pending = backend.handle(request(listPath, 'GET', undefined, {}, controller.signal))
  controller.abort()
  await assert.rejects(pending, { name: 'AbortError' })
  assert.equal(backend.inspect().active, 0)
})
test('reset fences pending requests and restores fixture state', async () => {
  const backend = createScenarioBackend('news-slow', { origin })
  const pending = backend.handle(request(listPath))
  backend.reset()
  await assert.rejects(pending, { name: 'AbortError' })
  assert.equal(backend.inspect().active, 0)
  assert.equal(backend.inspect().requests.length, 0)
})
test('audit logs do not retain query strings, bodies or credentials', async () => {
  const backend = createScenarioBackend('normal', { origin })
  await backend.handle(request('/api/news/?search=secret-query', 'GET', undefined, { Authorization: 'Bearer secret-token' }))
  const serialized = JSON.stringify(backend.inspect())
  assert.equal(serialized.includes('secret-query'), false)
  assert.equal(serialized.includes('secret-token'), false)
})
test('returned audit snapshot cannot mutate backend counters', async () => {
  const backend = createScenarioBackend('normal', { origin })
  await backend.handle(request(listPath))
  const snapshot = backend.inspect()
  snapshot.requests.length = 0
  assert.equal(backend.inspect().requests.length, 1)
})

test('public policy rejects private reads before authentication in read-only mode', async () => {
  const backend = createScenarioBackend('read-only', { origin })
  const result = await backend.handle(request(readPath))
  assert.equal(result.status, 403)
  assert.equal((await result.json()).error.code, 'public_read_only')
})
test('wrong viewer and expired-viewer writes get the middleware 409 fence', async () => {
  for (const scenario of ['normal', 'auth-expired']) {
    const backend = createScenarioBackend(scenario, { origin })
    const result = await backend.handle(patch({ is_read: true, expected_version: 0 }, { 'X-Workspace-Viewer': '99999' }))
    assert.equal(result.status, 409)
    assert.equal((await result.json()).error.code, 'stale')
  }
})
