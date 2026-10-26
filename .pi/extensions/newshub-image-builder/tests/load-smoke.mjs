// Exercise the real installed Pi extension loader without prompting any model.
// Usage: node load-smoke.mjs /absolute/path/to/@earendil-works/pi-coding-agent
import assert from 'node:assert/strict';
import { pathToFileURL, fileURLToPath } from 'node:url';
import { resolve } from 'node:path';

const sdk = process.argv[2];
assert.ok(sdk, 'Pass the installed Pi SDK package directory');
const { loadExtensions } = await import(pathToFileURL(resolve(sdk, 'dist/core/extensions/loader.js')).href);
const root = fileURLToPath(new URL('../../../../', import.meta.url));
const entry = fileURLToPath(new URL('../index.ts', import.meta.url));
const loaded = await loadExtensions([entry], root);
assert.deepEqual(loaded.errors, []);
assert.equal(loaded.extensions.length, 1);
const extension = loaded.extensions[0];
const tool = extension.tools.get('newshub_image_builder')?.definition;
assert.ok(tool);
assert.equal(extension.tools.size, 1);
let modelCalls = 0;
const ctx = { cwd: root, modelRegistry: {
  find: () => undefined,
  streamSimple: () => { modelCalls++; throw new Error('Model calls forbidden in offline smoke'); },
} };
const invoke = params => tool.execute('offline-smoke', params, undefined, undefined, ctx);
assert.deepEqual(JSON.parse((await invoke({ action: 'status' })).content[0].text), []);
await assert.rejects(invoke({ action: 'start', sha: 'main', authorized: true }));
const { TARGET } = await import('../core.mjs');
const started = JSON.parse((await invoke({ action: 'start', sha: TARGET, authorized: true })).content[0].text);
const waited = JSON.parse((await invoke({ action: 'wait', jobId: started.id, waitSeconds: 1 })).content[0].text);
assert.equal(waited.status, 'blocked');
assert.match(waited.error, /no fallback/);
assert.equal(modelCalls, 0);
for (const handler of extension.handlers.get('session_shutdown') ?? []) await handler({}, ctx);
console.log('Pi loader/register/status/wait/no-model-fallback smoke PASS (zero inference/build calls)');
