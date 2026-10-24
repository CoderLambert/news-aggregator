import http from 'node:http'
import { pathToFileURL } from 'node:url'
import { createScenarioBackend } from '../src/mocks/backend.ts'
import { getScenario } from '../src/mocks/catalog.ts'

const MAX_BODY = 64 * 1024
function json(res, status, code) {
  res.writeHead(status, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' })
  res.end(JSON.stringify({ error: { code, message: 'Synthetic mock server request rejected', retryable: false } }))
}

/** One process/instance owns one scenario. Loopback only; never an upstream proxy. */
export async function startMockServer({ port = 9531, scenario = 'normal' } = {}) {
  if (!Number.isSafeInteger(port) || port < 0 || port > 65535) throw new Error('Invalid mock port')
  getScenario(scenario)
  let backend
  let origin
  const activeControllers = new Set()
  const server = http.createServer(async (req, res) => {
    const controller = new AbortController()
    activeControllers.add(controller)
    const abort = () => { if (!res.writableEnded) controller.abort(new DOMException('Client disconnected', 'AbortError')) }
    req.once('aborted', abort)
    res.once('close', abort)
    try {
      if (!origin || !backend) return json(res, 503, 'mock_not_ready')
      if (req.headers.host !== new URL(origin).host || (req.headers.origin && req.headers.origin !== origin)) {
        return json(res, 403, 'mock_origin_denied')
      }
      if (!req.url?.startsWith('/') || req.url.startsWith('//')) return json(res, 400, 'invalid_path')
      const url = new URL(req.url, origin)
      if (req.method === 'GET' && url.pathname === '/__mock__/health') {
        res.writeHead(200, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' })
        res.end(JSON.stringify({ mock: true, scenario, upstream: false }))
        return
      }
      if (url.pathname === '/__mock__/reset' && req.method === 'POST') {
        if (req.headers['x-newshub-mock-control'] !== 'reset') return json(res, 403, 'mock_control_required')
        backend.reset()
        res.writeHead(204, { 'Cache-Control': 'no-store' }); res.end(); return
      }
      if (url.pathname !== '/api' && !url.pathname.startsWith('/api/')) return json(res, 404, 'not_found')
      if (Number(req.headers['content-length'] ?? 0) > MAX_BODY) return json(res, 413, 'too_large')
      let length = 0
      const chunks = []
      for await (const chunk of req) {
        length += chunk.length
        if (length > MAX_BODY) { json(res, 413, 'too_large'); return }
        chunks.push(chunk)
      }
      const method = req.method ?? 'GET'
      const headers = new Headers()
      for (const [name, value] of Object.entries(req.headers)) {
        if (value !== undefined) headers.set(name, Array.isArray(value) ? value.join(', ') : value)
      }
      const body = Buffer.concat(chunks)
      const request = new Request(url, { method, headers, signal: controller.signal,
        ...(!['GET', 'HEAD'].includes(method) && body.length ? { body } : {}) })
      const result = await backend.handle(request)
      if (controller.signal.aborted || res.destroyed) return
      if (result.type === 'error') { res.destroy(); return }
      res.writeHead(result.status, Object.fromEntries(result.headers))
      res.end(Buffer.from(await result.arrayBuffer()))
    } catch {
      if (!controller.signal.aborted && !res.destroyed && !res.headersSent) json(res, 500, 'mock_internal_error')
      else if (!res.writableEnded) res.destroy()
    } finally {
      activeControllers.delete(controller)
      req.removeListener('aborted', abort); res.removeListener('close', abort)
    }
  })
  server.requestTimeout = 10_000
  server.headersTimeout = 10_000
  server.keepAliveTimeout = 1000
  await new Promise((resolve, reject) => {
    server.once('error', reject)
    server.listen(port, '127.0.0.1', () => { server.removeListener('error', reject); resolve() })
  })
  const address = server.address()
  origin = `http://127.0.0.1:${address.port}`
  backend = createScenarioBackend(scenario, { origin })
  return {
    origin, inspect: () => backend.inspect(),
    async close() {
      backend.reset()
      for (const controller of activeControllers) controller.abort(new DOMException('Server closed', 'AbortError'))
      await new Promise((resolve, reject) => {
        server.close(error => error ? reject(error) : resolve())
        server.closeAllConnections()
      })
    },
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const args = process.argv.slice(2)
  if (args.length > 2) throw new Error('Usage: npm run mock:backend -- [scenario] [port]')
  const app = await startMockServer({ scenario: args[0] ?? 'normal', port: args[1] === undefined ? 9531 : Number(args[1]) })
  console.log(`NewsHub synthetic backend: ${app.origin}; scenario=${args[0] ?? 'normal'}; no upstream`)
  let closing = false
  const close = async () => { if (!closing) { closing = true; await app.close() } }
  process.once('SIGINT', () => void close())
  process.once('SIGTERM', () => void close())
}
