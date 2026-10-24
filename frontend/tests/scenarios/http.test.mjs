import assert from 'node:assert/strict'
import { test } from 'node:test'
import http from 'node:http'
import { startMockServer } from '../../scripts/mock-backend.mjs'

async function withServer(scenario, fn) {
  const app = await startMockServer({ port: 0, scenario })
  try { await fn(app) } finally { await app.close() }
}
function raw(origin, headers) {
  return new Promise((resolve, reject) => {
    const req = http.get(origin + '/api/news/', { headers }, res => {
      res.resume(); res.on('end', () => resolve(res.statusCode))
    })
    req.on('error', reject)
  })
}
test('HTTP adapter serves real JSON without Django', () => withServer('normal', async ({ origin }) => {
  const result = await fetch(origin + '/api/news/')
  assert.equal(result.status, 200)
  assert.equal(result.headers.get('x-newshub-mock'), 'scenario-v1')
  assert.equal((await result.json()).count, 2)
}))
test('HTTP mock has no public bind option', async () => {
  await assert.rejects(startMockServer({ port: -1 }), /port/)
})
test('Host and Origin checks reject browser cross-site and DNS-rebinding requests', () => withServer('normal', async ({ origin }) => {
  assert.equal(await raw(origin, { Host: 'evil.invalid' }), 403)
  assert.equal(await raw(origin, { Origin: 'https://evil.invalid' }), 403)
}))
test('unknown APIs fail explicitly instead of forwarding', () => withServer('normal', async ({ origin }) => {
  assert.equal((await fetch(origin + '/api/unknown/')).status, 501)
}))
test('body bound rejects oversized JSON', () => withServer('normal', async ({ origin }) => {
  const result = await fetch(origin + '/api/me/news/910001/read-state/', {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text: 'x'.repeat(70_000) }),
  })
  assert.equal(result.status, 413)
}))
test('HTTP network-failure scenario terminates the connection, not a fake HTTP 500', () => withServer('news-network-error', async ({ origin }) => {
  await assert.rejects(fetch(origin + '/api/news/'))
}))
test('reset requires an explicit non-simple control header', () => withServer('news-retry', async ({ origin }) => {
  assert.equal((await fetch(origin + '/__mock__/reset', { method: 'POST' })).status, 403)
  for (const expected of [503, 503, 200]) assert.equal((await fetch(origin + '/api/news/')).status, expected)
  const reset = await fetch(origin + '/__mock__/reset', { method: 'POST', headers: { 'X-NewsHub-Mock-Control': 'reset' } })
  assert.equal(reset.status, 204)
  assert.equal((await fetch(origin + '/api/news/')).status, 503)
}))
test('a new HTTP instance starts fresh', async () => {
  await withServer('normal', async ({ origin }) => {
    await fetch(origin + '/api/me/news/910001/read-state/', { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: '{"is_read":true,"expected_version":0}' })
  })
  await withServer('normal', async ({ origin }) => {
    assert.deepEqual(await (await fetch(origin + '/api/me/news/910001/read-state/')).json(), { is_read: false, version: 0 })
  })
})
