import { afterAll, afterEach, beforeAll, beforeEach, expect, it } from 'vitest'
import { setupServer } from 'msw/node'
import { createScenarioBackend } from '@/mocks/backend'
import type { ScenarioBackend } from '@/mocks/backend'
import { scenarioHandlers } from '@/mocks/handlers'
import { fetchNews, fetchNewsDetail, fetchReadState, updateReadState, fetchCapabilities } from '@/services/api'
import { parseNewsSummary, parseNewsDetail, parsePage } from '@/types/news'
import { MOCK_VIEWER } from '@/mocks/fixtures'

// Runs in the repository's jsdom environment: real Axios/XHR, real interceptors and real parsers.
const origin = window.location.origin
const server = setupServer()
let backend: ScenarioBackend
function select(id: string) {
  backend?.reset()
  backend = createScenarioBackend(id, { origin })
  server.resetHandlers(...scenarioHandlers(backend, origin))
}
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
beforeEach(() => select('normal'))
afterEach(() => { backend.reset(); server.resetHandlers(); document.cookie = 'csrftoken=; Max-Age=0; Path=/' })
afterAll(() => server.close())

it('real fetchNews crosses MSW and the production parser', async () => {
  const result = parsePage(await fetchNews({ page: 1, page_size: 20 }), parseNewsSummary)
  expect(result.count).toBe(2)
  expect(backend.inspect().requests).toEqual([expect.objectContaining({ path: '/api/news/', status: 200 })])
})
it('real detail and capability clients consume synthetic wire data', async () => {
  expect(parseNewsDetail(await fetchNewsDetail(910001)).id).toBe(910001)
  expect((await fetchCapabilities()).features.accounts.enabled).toBe(true)
})
it('keeps the actual Axios viewer and CSRF request headers', async () => {
  const seen: Array<{ viewer: string | null; csrf: string | null; body: unknown }> = []
  const recording: ScenarioBackend = { scenario: backend.scenario, reset: () => backend.reset(), inspect: () => backend.inspect(),
    handle: async request => {
      if (request.method === 'PATCH') seen.push({ viewer: request.headers.get('X-Workspace-Viewer'),
        csrf: request.headers.get('X-CSRFToken'), body: await request.clone().json() })
      return backend.handle(request)
    } }
  server.resetHandlers(...scenarioHandlers(recording, origin))
  // Synthetic cookie exists only in this disposable jsdom test, never set by the development mock.
  document.cookie = 'csrftoken=synthetic-test-csrf; Path=/'
  expect(await updateReadState(910001, true, 0, MOCK_VIEWER.id)).toEqual({ is_read: true, version: 1 })
  expect(seen).toEqual([{ viewer: String(MOCK_VIEWER.id), csrf: 'synthetic-test-csrf', body: { is_read: true, expected_version: 0 } }])
})
it('actual API exposes a stale version as 409 and preserves the saved state', async () => {
  await updateReadState(910001, true, 0, MOCK_VIEWER.id)
  await expect(updateReadState(910001, false, 0, MOCK_VIEWER.id)).rejects.toMatchObject({ response: { status: 409 } })
  expect(await fetchReadState(910001)).toEqual({ is_read: true, version: 1 })
})
it('wrong-viewer writes cannot mutate the mock state', async () => {
  await expect(updateReadState(910001, true, 0, 999)).rejects.toMatchObject({ response: { status: 409 } })
  expect(await fetchReadState(910001)).toEqual({ is_read: false, version: 0 })
})
it('does not let malformed wire data bypass the real parser', async () => {
  select('news-malformed')
  const wire = await fetchNews()
  expect(() => parsePage(wire, parseNewsSummary)).toThrow()
})
it('the API client itself does not consume the query layer retry budget', async () => {
  select('news-retry')
  for (let index = 0; index < 2; index++) await expect(fetchNews()).rejects.toMatchObject({ response: { status: 503 } })
  expect(parsePage(await fetchNews(), parseNewsSummary).count).toBe(2)
})
it('AbortSignal still cancels the real Axios request', async () => {
  select('news-slow')
  const controller = new AbortController()
  const pending = fetchNews({}, controller.signal)
  const rejected = expect(pending).rejects.toMatchObject({ code: 'ERR_CANCELED' })
  controller.abort()
  await rejected
})
it('network failure is not disguised as an HTTP response', async () => {
  select('news-network-error')
  await expect(fetchNews()).rejects.toMatchObject({ code: 'ERR_NETWORK' })
})
