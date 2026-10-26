import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { BuildJobs, TARGET, PROVIDER, MODEL, THINKING, validateTarget } from '../core.mjs';
import { safeRuntimePath, buildArgs, verifyImage, acquireLock, blocked, SOCKET,
  CI_NETWORK, SOCKET_VOLUME, CLIENT_IMAGE, CLIENT_USER, discoverClientTransport, clientArgs } from '../build.mjs';

const dindImageId = `sha256:${'b'.repeat(64)}`;
const service = (name, serviceName, mounts = []) => ({
  Name: `/${name}`, Image: dindImageId,
  Config: { Labels: { 'com.docker.compose.project': 'newshub-ci', 'com.docker.compose.service': serviceName } },
  State: { Status: 'running', Running: true, Health: { Status: 'healthy' } },
  Mounts: mounts, NetworkSettings: { Networks: { [CI_NETWORK]: {} } },
});
function transportFixture() {
  const socket = { Type: 'volume', Name: SOCKET_VOLUME, Destination: '/ci-docker' };
  return {
    dind: service('newshub-ci-docker-1', 'docker', [socket]),
    runner: service('newshub-ci-runner-1', 'runner', [socket]),
    frontend: service('newshub-ci-runner-frontend-1', 'runner-frontend'),
    network: { Name: CI_NETWORK, Driver: 'bridge', Labels: { 'com.docker.compose.project': 'newshub-ci' },
      Containers: Object.fromEntries(['newshub-ci-docker-1', 'newshub-ci-runner-1', 'newshub-ci-runner-frontend-1']
        .map((name, i) => [i, { Name: name }])) },
    socketVolume: { Name: SOCKET_VOLUME, Labels: {
      'com.docker.compose.project': 'newshub-ci', 'com.docker.compose.volume': 'runner-socket' } },
    clientImage: { Id: dindImageId, RepoTags: [CLIENT_IMAGE], Os: 'linux', Architecture: 'amd64' },
  };
}

const deferred = () => {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
};

test('exact model and accepted SHA only; malformed or moving targets rejected', () => {
  assert.equal(`${PROVIDER}/${MODEL}`, 'openai-codex/gpt-6-luna');
  assert.equal(THINKING, 'xhigh');
  assert.equal(validateTarget(TARGET), TARGET);
  for (const sha of [undefined, '', 'main', TARGET.slice(0, 8), 'f'.repeat(40), `${TARGET}; docker push x`]) {
    assert.throws(() => validateTarget(sha));
  }
});

test('factory and status are inert; authorization is explicit', () => {
  let calls = 0;
  const jobs = new BuildJobs(() => { calls++; });
  assert.deepEqual(jobs.status(), []);
  assert.throws(() => jobs.start(TARGET, false), /authorization/);
  assert.equal(calls, 0);
});

test('start, query and wait preserve identity and reject concurrent duplicate jobs', async () => {
  const gate = deferred();
  const jobs = new BuildJobs(() => gate.promise);
  const job = jobs.start(TARGET, true);
  assert.equal(job.status, 'running');
  assert.equal(job.thinking, 'xhigh');
  assert.throws(() => jobs.start(TARGET, true), /already running/);
  gate.resolve({ revision: TARGET });
  const result = await jobs.wait(job.id, 1);
  assert.equal(result.status, 'succeeded');
  assert.equal(result.result.revision, TARGET);
  assert.throws(() => jobs.status('missing'), /Unknown job/);
});

test('raw provider errors redacted; blockers never become success', async () => {
  const jobs = new BuildJobs(async () => { throw new Error('secret-token-from-provider'); });
  const job = jobs.start(TARGET, true);
  assert.equal((await jobs.wait(job.id, 1)).status, 'failed');
  assert.doesNotMatch(JSON.stringify(jobs.status()), /secret-token/);
  const gated = new BuildJobs(async () => { throw blocked('Isolated socket unavailable'); });
  const id = gated.start(TARGET, true).id;
  assert.equal((await gated.wait(id, 1)).status, 'blocked');
  assert.equal(gated.status(id).error, 'Isolated socket unavailable');
});

test('cancelled wait does not cancel job; shutdown aborts and settles its own job', async () => {
  const jobs = new BuildJobs((_, signal) => new Promise((resolve, reject) => {
    signal.addEventListener('abort', () => reject(new Error('cancelled')), { once: true });
  }));
  const id = jobs.start(TARGET, true).id;
  await Promise.resolve();
  const waiter = new AbortController();
  const waiting = jobs.wait(id, 1, waiter.signal);
  waiter.abort();
  await assert.rejects(waiting, /Wait cancelled/);
  assert.equal(jobs.status(id).status, 'running');
  await jobs.close();
  assert.equal(jobs.status(id).status, 'cancelled');
  assert.throws(() => jobs.start(TARGET, true), /shutting down/);
});

test('wait is bounded and does not report a running job as complete', async () => {
  const gate = deferred();
  const jobs = new BuildJobs(() => gate.promise);
  const id = jobs.start(TARGET, true).id;
  await assert.rejects(jobs.wait(id, 0), /1 to 60/);
  assert.equal((await jobs.wait(id, 1)).status, 'running');
  gate.resolve({});
  await jobs.wait(id, 1);
});

test('safe context excludes DB and credentials before reading any blob', () => {
  for (const path of ['backend/db.sqlite3', 'backend/x.sqlite3-wal', 'backend/x.sqlite3-shm',
    'backend/.env', 'frontend/.env.local', 'backend/auth.json', 'backend/certs/private.key',
    '../backend/code.py', '/backend/code.py', 'backend/../.env', 'backend/link\\escape',
    '.pi/extensions/index.ts', '.omp/agents/a.md', 'backend/.runtime/id', 'backend/media/private.mp3']) {
    assert.equal(safeRuntimePath(path), false, path);
  }
  for (const path of ['Dockerfile', '.dockerignore', 'backend/api/token_manager.py',
    'backend/api/migrations/0001.py', 'frontend/src/App.tsx', 'scripts/docker-entrypoint.sh']) {
    assert.equal(safeRuntimePath(path), true, path);
  }
});

test('isolated transport discovers only the expected healthy Compose services and local image', () => {
  const transport = discoverClientTransport(transportFixture());
  assert.deepEqual(transport, { network: CI_NETWORK, socketVolume: SOCKET_VOLUME,
    clientImage: CLIENT_IMAGE, clientImageId: dindImageId });
  for (const mutate of [
    m => { m.dind.Config.Labels['com.docker.compose.project'] = 'other'; },
    m => { m.runner.State.Health.Status = 'starting'; },
    m => { m.dind.Mounts[0].Name = 'wrong-volume'; },
    m => { m.frontend.Mounts.push({ Type: 'volume', Name: SOCKET_VOLUME, Destination: '/ci-docker' }); },
    m => { m.network.Labels['com.docker.compose.project'] = 'other'; },
    m => { m.clientImage.Id = `sha256:${'c'.repeat(64)}`; },
  ]) {
    const metadata = structuredClone(transportFixture());
    mutate(metadata);
    assert.throws(() => discoverClientTransport(metadata), /Expected|private|network|matching/);
  }
});

test('regression: private-volume client replaces the old host-socket assumption', () => {
  assert.equal(SOCKET, '/ci-docker/docker.sock'); // Client-side endpoint only, never a host bind.
  const transport = discoverClientTransport(transportFixture());
  const taskId = '12345678-1234-4234-8234-123456789abc';
  const args = clientArgs({ name: `newshub-image-builder-${taskId}`, taskId,
    context: '/tmp/sanitized-context', command: ['version'], transport });
  assert.ok(args.includes('--pull=never'));
  assert.equal(args[args.indexOf('--entrypoint') + 1], 'docker');
  assert.equal(args[args.indexOf('--user') + 1], CLIENT_USER);
  assert.ok(args.includes('--cap-drop') && args.includes('--security-opt'));
  assert.ok(args.includes('HOME=/tmp'));
  assert.ok(args.includes('DOCKER_CONFIG=/tmp/.docker'));
  assert.equal(args[args.indexOf('--tmpfs') + 1], '/tmp:rw,nosuid,nodev,mode=1777');
  assert.ok(args.includes(dindImageId));
  assert.ok(!args.includes(CLIENT_IMAGE));
  assert.deepEqual(args.filter(arg => arg.startsWith('type=')), [
    `type=volume,source=${SOCKET_VOLUME},target=/ci-docker,readonly`,
    'type=bind,source=/tmp/sanitized-context,target=/context,readonly',
  ]);
  assert.ok(args.includes(CI_NETWORK));
  assert.ok(!args.some(arg => arg.includes('/var/run/docker.sock') || arg.includes('runner-state') || arg.includes('runner-work')));
  assert.deepEqual(buildArgs(TARGET), ['build', '--progress=plain', '--target', 'production',
    '--build-arg', `RELEASE_SHA=${TARGET}`, '--tag', `newshub:dev-${TARGET}`, '/context']);
});

test('tag alone, wrong revision, root user and wrong entrypoint are not success', () => {
  const image = { Id: `sha256:${'a'.repeat(64)}`, Os: 'linux', Architecture: 'amd64',
    Config: { User: '10001:10001', Cmd: ['/app/docker-entrypoint.sh'],
      Labels: { 'org.opencontainers.image.revision': TARGET } } };
  const result = verifyImage([image], TARGET);
  assert.equal(result.revision, TARGET);
  assert.equal(result.builderImage.location, 'isolated-ci-dind');
  assert.equal(result.builderImage.id, image.Id);
  assert.deepEqual(result.hostRuntime, { status: 'transfer-required', ready: false, imageId: null });
  for (const change of [undefined, { ...image, Id: 'tag-only' },
    { ...image, Config: { ...image.Config, User: 'root' } },
    { ...image, Config: { ...image.Config, Labels: {} } },
    { ...image, Config: { ...image.Config, Cmd: ['sh'] } }]) {
    assert.throws(() => verifyImage([change], TARGET));
  }
});

test('cross-session lock is exclusive, never stolen, and released only by owner', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'newshub-pi-lock-test-'));
  const path = join(dir, 'lock');
  try {
    const release = await acquireLock(path);
    await assert.rejects(acquireLock(path), /interrupted build/);
    const owner = await readFile(path, 'utf8');
    await writeFile(path, '{"token":"different-owner"}');
    await assert.rejects(release(), /ownership changed/);
    assert.equal(await readFile(path, 'utf8'), '{"token":"different-owner"}');
    await writeFile(path, owner);
    await release();
    const again = await acquireLock(path);
    await again();
  } finally { await rm(dir, { recursive: true, force: true }); }
});
