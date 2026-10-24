import assert from 'node:assert/strict'
import { test } from 'node:test'
import { mkdtemp, mkdir, writeFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { assertNoMockAssets } from '../../scripts/assert-no-mock-assets.mjs'
async function fixture(fn) {
  const root = await mkdtemp(path.join(tmpdir(), 'newshub-mock-scan-'))
  try { await fn(root) } finally { await rm(root, { recursive: true, force: true }) }
}
test('scanner rejects missing or empty production outputs', () => fixture(async root => {
  await assert.rejects(assertNoMockAssets(root), /empty/)
}))
test('scanner accepts a clean synthetic asset tree (not a real build claim)', () => fixture(async root => {
  await writeFile(path.join(root, 'index.html'), '<html></html>')
  await assertNoMockAssets(root)
}))
test('scanner rejects copied MSW worker files', () => fixture(async root => {
  await writeFile(path.join(root, 'mockServiceWorker.js'), '/* worker */')
  await assert.rejects(assertNoMockAssets(root), /Mock assets/)
}))
test('scanner rejects mock diagnostics inside a hashed bundle', () => fixture(async root => {
  await mkdir(path.join(root, 'assets'))
  await writeFile(path.join(root, 'assets/app-a1.js'), 'window.__NEWSHUB_MOCK__ = {}')
  await assert.rejects(assertNoMockAssets(root), /Mock assets/)
}))
