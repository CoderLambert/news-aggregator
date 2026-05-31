#!/usr/bin/env node
/**
 * Tiny static server with SPA fallback.
 * Workaround for PRoot's broken `os.networkInterfaces()` which kills `vite preview`.
 * Serves /dist on 0.0.0.0:5180 — unknown routes fall back to index.html so React Router works.
 */
import http from 'node:http'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.join(__dirname, 'dist')
const PORT = Number(process.env.PORT || 5180)

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'application/javascript; charset=utf-8',
  '.mjs': 'application/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.ico': 'image/x-icon',
  '.woff': 'font/woff',
  '.woff2': 'font/woff2',
  '.map': 'application/json; charset=utf-8',
}

const server = http.createServer((req, res) => {
  let pathname = decodeURI(req.url.split('?')[0])
  if (pathname === '/') pathname = '/index.html'
  let filePath = path.join(ROOT, pathname)
  // Block path traversal
  if (!filePath.startsWith(ROOT)) {
    res.statusCode = 403
    return res.end('Forbidden')
  }
  fs.stat(filePath, (err, stat) => {
    if (err || !stat.isFile()) {
      // SPA fallback
      filePath = path.join(ROOT, 'index.html')
    }
    const ext = path.extname(filePath)
    const ctype = MIME[ext] || 'application/octet-stream'
    res.setHeader('Content-Type', ctype)
    res.setHeader('Cache-Control', ext === '.html' ? 'no-cache' : 'public, max-age=3600')
    fs.createReadStream(filePath).pipe(res)
  })
})

server.listen(PORT, '0.0.0.0', () => {
  console.log(`[preview] http://0.0.0.0:${PORT} — try /__mascot__`)
})
