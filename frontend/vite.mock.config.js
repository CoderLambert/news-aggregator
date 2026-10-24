import { defineConfig, mergeConfig } from 'vite'
import { msw } from 'msw/vite'
import original from './vite.config.js'

export default defineConfig(({ command, mode, isPreview }) => {
  if (command !== 'serve' || mode !== 'mock' || isPreview) {
    throw new Error('Mock config is dev-only. Build production with the original vite.config.js.')
  }
  const config = mergeConfig(original, {
    // Do not load the real project's .env files for this synthetic environment.
    envDir: false,
    plugins: [
      msw({ mode: 'worker-only' }),
      {
        name: 'newshub-scenario-entry',
        enforce: 'pre',
        transformIndexHtml: {
          order: 'pre',
          handler(html) {
            if (!html.includes('/src/main.jsx')) throw new Error('NewsHub HTML entry changed; review mock bootstrap')
            return html.replace('/src/main.jsx', '/src/mocks/entry.ts')
          },
        },
        configResolved(resolved) {
          if (resolved.server.host !== '127.0.0.1' || Object.keys(resolved.server.proxy ?? {}).length > 0) {
            throw new Error('Mock dev server must remain loopback-only with no upstream proxy')
          }
        },
        configureServer(server) {
          server.middlewares.use((req, res, next) => {
            const path = (req.url ?? '').split('?')[0]
            if (path !== '/api' && !path.startsWith('/api/')) return next()
            // If a request escapes MSW, NEVER forward it to Django/production.
            res.writeHead(503, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' })
            res.end(JSON.stringify({ error: { code: 'mock_worker_not_ready',
              message: 'MSW did not intercept this API request. No upstream was contacted.', retryable: false } }))
          })
        },
      },
    ],
    server: { host: '127.0.0.1', port: 9530, strictPort: true, cors: false,
      headers: { 'Content-Security-Policy': "connect-src 'self' ws://127.0.0.1:*" } },
  })
  // mergeConfig merges proxy maps, so explicitly remove the inherited real backend target.
  config.server.proxy = {}
  return config
})
