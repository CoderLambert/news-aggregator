import { execFileSync } from 'node:child_process'
import { readFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
const manifest = JSON.parse(await readFile(path.join(root, 'docs/testing/scenario-source.json'), 'utf8'))
let changed = false
for (const item of manifest.contracts) {
  // Read source bytes only. Never execute backend, load .env or contact a service.
  const actual = execFileSync('git', ['hash-object', '--', item.path], { cwd: root, encoding: 'utf8' }).trim()
  if (actual !== item.blob) { console.error(`REVIEW_REQUIRED ${item.path}`); changed = true }
}
if (changed) {
  console.error('Contract sources changed since the recorded base. Review fixtures/tests before updating this manifest.')
  process.exitCode = 1
} else console.log('Pinned contract sources unchanged. This is a drift alarm, not backend runtime validation.')
