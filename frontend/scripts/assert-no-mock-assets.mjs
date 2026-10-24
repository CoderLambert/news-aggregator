import { readdir, readFile } from 'node:fs/promises'
import path from 'node:path'
import { pathToFileURL } from 'node:url'

export async function assertNoMockAssets(directory) {
  const violations = []
  let files = 0
  async function visit(dir) {
    for (const entry of await readdir(dir, { withFileTypes: true })) {
      const file = path.join(dir, entry.name)
      if (entry.isDirectory()) { await visit(file); continue }
      if (!entry.isFile()) continue
      files++
      const relative = path.relative(directory, file)
      if (/mockserviceworker|msw(?:[-.])/i.test(entry.name)) { violations.push(relative); continue }
      if (/\.(?:js|mjs|html|map)$/i.test(entry.name)) {
        const text = await readFile(file, 'utf8')
        if (/__NEWSHUB_MOCK__|newshub-mock-status|mock_worker_not_ready|synthetic-request|scenario-v1/.test(text)) violations.push(relative)
      }
    }
  }
  await visit(directory)
  if (!files) throw new Error('Production output is empty; build before scanning')
  if (violations.length) throw new Error(`Mock assets leaked into production output: ${violations.join(', ')}`)
  return files
}
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const count = await assertNoMockAssets(path.resolve(process.argv[2] ?? 'dist'))
  console.log(`Scanned ${count} production files: no reserved mock markers or worker assets found`)
}
