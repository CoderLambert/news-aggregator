import assert from 'node:assert/strict'
import { test } from 'node:test'
import { readFile } from 'node:fs/promises'
import { scenarios } from '../../src/mocks/catalog.ts'
import { scenarioMatrix } from '../../e2e/scenarios/matrix.mjs'

test('scenario catalog and independent acceptance matrix have one-to-one coverage', () => {
  const ids = scenarioMatrix.map(row => row.id)
  assert.equal(new Set(ids).size, ids.length)
  assert.deepEqual(ids.toSorted(), scenarios.map(row => row.id).toSorted())
  assert.ok(scenarioMatrix.every(row => row.journey && row.path.startsWith('/')))
})
test('production bootstrap does not import mock runtime', async () => {
  const text = await readFile(new URL('../../src/main.jsx', import.meta.url), 'utf8')
  assert.doesNotMatch(text, /mocks|scenario|setupWorker/)
})
test('original Vite production config does not import the mock adapter', async () => {
  const text = await readFile(new URL('../../vite.config.js', import.meta.url), 'utf8')
  assert.doesNotMatch(text, /msw|mocks\/|scenario-entry/)
})
