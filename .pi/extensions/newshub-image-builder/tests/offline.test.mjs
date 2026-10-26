import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { BuildJobs, TARGET, PROVIDER, MODEL, THINKING, validateTarget, normalizeDiagnostics,
  sanitizeDiagnosticMessage } from '../core.mjs';
import { createImageBuildWorker, classifyChildError } from '../worker.mjs';
import * as buildModule from '../build.mjs';
import { safeRuntimePath, buildArgs, verifyImage, acquireLock, blocked, SOCKET,
  CI_NETWORK, SOCKET_VOLUME, CLIENT_IMAGE, CLIENT_USER, discoverClientTransport, clientArgs } from '../build.mjs';

test('existing builder services are preserved, not mistaken for busy workers', () => {
  assert.equal(typeof buildModule.preservedContainerNames, 'function');
  assert.deepEqual(buildModule.preservedContainerNames('adoring_goldberg\nquizzical_kalam\n', 'own-client'),
    ['adoring_goldberg', 'quizzical_kalam']);
  assert.deepEqual(buildModule.preservedContainerNames('own-client\n', 'own-client'), []);
  assert.throws(() => buildModule.preservedContainerNames('invalid;command\n', 'own-client'));
});

test('local image follows the accepted development user and cache contract', () => {
  assert.deepEqual(buildArgs(TARGET), ['build', '--progress=plain', '--target', 'development',
    '--label', `org.opencontainers.image.revision=${TARGET}`, '--tag', `newshub:dev-${TARGET}`, '/context']);
  const image = { Id: `sha256:${'a'.repeat(64)}`, Os: 'linux', Architecture: 'amd64',
    Config: { User: 'root', Cmd: ['/app/docker-entrypoint.sh'],
      Labels: { 'org.opencontainers.image.revision': TARGET } } };
  assert.equal(verifyImage([image], TARGET).builderImage.user, 'root');
});

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

const verifiedResult = {
  revision: TARGET,
  builderImage: { id: `sha256:${'a'.repeat(64)}`, revision: TARGET },
  hostRuntime: { status: 'transfer-required', ready: false, imageId: null },
  diagnostics: { imageEvidence: { verified: true } },
};

const deferred = () => {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
};

function fakeAgent(behavior) {
  return class FakeAgent {
    constructor(options) {
      this.options = options;
      this.state = { messages: [], errorMessage: undefined };
      this.listeners = new Set();
    }
    subscribe(listener) { this.listeners.add(listener); return () => this.listeners.delete(listener); }
    async emit(event) { for (const listener of this.listeners) await listener(event); }
    abort() { this.onAbort?.(); }
    async waitForIdle() {}
    async prompt() {
      if (behavior === 'hang') await new Promise(resolve => { this.onAbort = resolve; });
      if (behavior === 'tool-success' || behavior === 'tool-failure') {
        const tool = this.options.initialState.tools[0];
        await this.emit({ type: 'tool_execution_start', toolCallId: 'fake-call', toolName: tool.name });
        let isError = false;
        let result;
        try { result = await tool.execute({}); }
        catch (error) { isError = true; result = { content: [{ type: 'text', text: error.message }] }; }
        await this.emit({ type: 'tool_execution_end', toolCallId: 'fake-call', toolName: tool.name,
          result, isError });
      }
      if (behavior === 'eof' || behavior === 'hang') return;
      const assistant = behavior === 'provider-error'
        ? { role: 'assistant', stopReason: 'error', errorMessage: 'prompt: private words https://private.invalid api_key=secret' }
        : { role: 'assistant', stopReason: 'stop' };
      assistant.usage = { input: 12, output: 3, cacheRead: 1, cacheWrite: 2, totalTokens: 18,
        cost: { input: 0.1, output: 0.2, cacheRead: 0.01, cacheWrite: 0.02, total: 0.33 } };
      if (behavior === 'provider-error') this.state.errorMessage = assistant.errorMessage;
      this.state.messages.push(assistant);
      await this.emit({ type: 'message_end', message: assistant });
      await this.emit({ type: 'turn_end', message: assistant, toolResults: [] });
    }
  };
}

function workerFixture(behavior, failBuild = false, deadlineMs = 1000, missingEvidence = false, prepareFailure = null) {
  let buildCalls = 0;
  let evidence;
  const model = { provider: PROVIDER, id: MODEL };
  const registry = {
    find: () => model,
    hasConfiguredAuth: () => true,
    streamSimple: () => { throw new Error('Fake Agent must not call streamSimple'); },
  };
  const worker = createImageBuildWorker({
    AgentClass: prepareFailure === 'agent-construction' ? class {
      constructor() { throw Object.assign(new Error('private constructor payload'), { code: 'EACCES', exitCode: 13 }); }
    } : fakeAgent(behavior),
    clampThinkingLevel: () => THINKING,
    toolParameters: { type: 'object' },
    getRegistry: () => registry,
    createBuild: () => {
      if (prepareFailure === 'build-adapter') {
        throw Object.assign(new Error('private adapter payload'), { code: 'EACCES', exitCode: 13 });
      }
      return {
      rules: async () => {
        if (prepareFailure === 'rules') {
          throw Object.assign(new Error('private rules payload'), { code: 'EACCES', exitCode: 13 });
        }
        return 'public committed rules only';
      },
      build: async () => {
        buildCalls++;
        if (failBuild) throw Object.assign(new Error('provider prompt secret https://private.invalid'), {
          code: 'NEWSHUB_BLOCKED', safeMessage: 'Docker build failed (exit 17); no retry performed',
        });
        if (!missingEvidence) evidence = verifiedResult;
        return verifiedResult;
      },
      evidence: () => evidence,
    };
    },
    root: '/repo', deadlineMs,
  });
  return { worker, buildCalls: () => buildCalls };
}

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
  gate.resolve(verifiedResult);
  const result = await jobs.wait(job.id, 1);
  assert.equal(result.status, 'succeeded');
  assert.equal(result.result.revision, TARGET);
  assert.throws(() => jobs.status('missing'), /Unknown job/);
});

test('build and child failure diagnostics survive query/wait without leaking unsafe text', async () => {
  const failure = Object.assign(new Error('Docker build failed (exit 17)'), {
    code: 'NEWSHUB_BUILD_FAILURE', safeMessage: 'Docker build failed (exit 17)',
    diagnostics: { buildCalled: true, buildErrorCode: 'DOCKER_BUILD_FAILED', buildExitCode: 17,
      buildErrorMessage: 'Docker build failed (exit 17)', childStopReason: 'stop', childErrorMessage: null,
      cancelled: false, timedOut: false,
      imageEvidence: { verified: false } },
  });
  const jobs = new BuildJobs(async () => { throw failure; });
  const started = jobs.start(TARGET, true);
  const waited = await jobs.wait(started.id, 1);
  assert.deepEqual(waited.diagnostics, normalizeDiagnostics(failure.diagnostics));
  assert.deepEqual(jobs.status(started.id).diagnostics, normalizeDiagnostics(failure.diagnostics));
  assert.equal(waited.error, 'Docker build failed (exit 17)');
});

test('real worker reports its concrete build-tool failure instead of the generic completion failure', async () => {
  const fixture = workerFixture('tool-failure', true);
  const jobs = new BuildJobs(fixture.worker);
  const started = jobs.start(TARGET, true);
  const waited = await jobs.wait(started.id, 1);
  assert.equal(fixture.buildCalls(), 1);
  assert.equal(waited.status, 'failed');
  assert.equal(waited.error, 'Docker build failed (exit 17); no retry performed');
  assert.equal(waited.diagnostics.buildCalled, true);
  assert.equal(waited.diagnostics.buildErrorCode, 'DOCKER_BUILD_FAILED');
  assert.equal(waited.diagnostics.buildExitCode, 17);
  assert.equal(waited.diagnostics.childStopReason, 'stop');
  assert.equal(waited.diagnostics.imageEvidence.verified, false);
  assert.deepEqual(jobs.get(started.id).usage, {
    input: 12, output: 3, cacheRead: 1, cacheWrite: 2, totalTokens: 18,
    cost: { input: 0.1, output: 0.2, cacheRead: 0.01, cacheWrite: 0.02, total: 0.33 },
  });
  assert.equal(jobs.status(started.id).error, waited.error);
});

test('worker rejects provider errors, EOF, and unverified tool results without false success or leaks', async () => {
  for (const behavior of ['provider-error', 'eof']) {
    const fixture = workerFixture(behavior);
    const jobs = new BuildJobs(fixture.worker);
    const started = jobs.start(TARGET, true);
    const waited = await jobs.wait(started.id, 1);
    assert.equal(waited.status, 'failed');
    assert.equal(waited.diagnostics.buildCalled, false);
    assert.equal(waited.diagnostics.imageEvidence.verified, false);
    assert.equal(fixture.buildCalls(), 0);
    assert.doesNotMatch(JSON.stringify(waited), /private words|private\.invalid|api_key=secret/);
    if (behavior === 'provider-error') {
      assert.equal(waited.diagnostics.childStopReason, 'error');
      assert.equal(waited.diagnostics.childErrorMessage, 'Provider inference failed (details redacted)');
    } else {
      assert.equal(waited.diagnostics.childErrorMessage, 'Agent returned no assistant completion');
    }
  }
  const missing = workerFixture('tool-success', false, 1000, true);
  await assert.rejects(missing.worker(TARGET, new AbortController().signal), /without verified image evidence/);
  assert.equal(missing.buildCalls(), 1);
});

test('worker exposes timeout state and bounds child error text', async () => {
  const fixture = workerFixture('hang', false, 5);
  const jobs = new BuildJobs(fixture.worker);
  const started = jobs.start(TARGET, true);
  const waited = await jobs.wait(started.id, 1);
  assert.equal(waited.status, 'failed');
  assert.equal(waited.diagnostics.timedOut, true);
  assert.equal(waited.diagnostics.imageEvidence.verified, false);
  assert.equal(fixture.buildCalls(), 0);
  const diagnostics = normalizeDiagnostics({
    buildErrorCode: 'https://private.invalid/token', buildExitCode: 999,
    buildErrorMessage: 'prompt=private text; api_key=secret https://secret.invalid Bearer secretvalue',
    childErrorMessage: 'provider returned prompt and credentials',
  });
  assert.equal(diagnostics.buildErrorCode, null);
  assert.equal(diagnostics.buildExitCode, null);
  assert.equal(diagnostics.childErrorMessage, 'Child inference failed (details redacted)');
  assert.doesNotMatch(JSON.stringify(diagnostics), /private text|secretvalue|secret\.invalid|api_key=secret/);
});

test('preparation failures retain safe stage, code, exit status, and failure usage', async () => {
  for (const stage of ['build-adapter', 'rules', 'agent-construction']) {
    const fixture = workerFixture('eof', false, 1000, false, stage);
    let failure;
    try { await fixture.worker(TARGET, new AbortController().signal); }
    catch (error) { failure = error; }
    assert.ok(failure, stage);
    assert.equal(failure.diagnostics.preparationStage, stage);
    assert.equal(failure.diagnostics.preparationErrorCode, 'EACCES');
    assert.equal(failure.diagnostics.preparationExitCode, 13);
    assert.equal(failure.diagnostics.preparationErrorMessage, 'Worker preparation failed (details redacted)');
    assert.equal(failure.usage.totalTokens, 0);
    assert.doesNotMatch(JSON.stringify(failure.diagnostics), /private .* payload/);
  }
});

test('child failures retain safe cause categories without arbitrary provider text', () => {
  const cases = [
    ['Connection closed by proxy server before the response completed', undefined, 'PROXY_EOF', 'Connection closed before response completed'],
    ['request failed with status code 401: {"api_key":"private"}', undefined, 'HTTP_401', 'Provider authentication rejected (HTTP 401)'],
    ['HTTP 403: secret body', undefined, 'HTTP_403', 'Provider authorization rejected (HTTP 403)'],
    ['status code 429: provider payload', undefined, 'HTTP_429', 'Provider rate limited (HTTP 429)'],
    ['400 unsupported parameter `reasoning` with private payload', undefined, 'UNSUPPORTED_PARAMETER', 'Provider rejected an unsupported request parameter'],
    ['model gpt-6-luna not found: private response', undefined, 'MODEL_NOT_FOUND', 'Requested model was not found'],
    [undefined, 'ECONNRESET', 'ECONNRESET', 'Connection closed before response completed'],
    [undefined, 'HTTP_401', 'HTTP_401', 'Provider authentication rejected (HTTP 401)'],
    ['unexpected EOF: private payload', undefined, 'PROXY_EOF', 'Connection closed before response completed'],
  ];
  for (const [message, code, expectedCode, expectedMessage] of cases) {
    const result = classifyChildError(message, code, 'error');
    assert.equal(result.code, expectedCode);
    assert.equal(result.message, expectedMessage);
    assert.doesNotMatch(JSON.stringify(result), /private|secret|payload|reasoning/);
  }
});

test('quoted JSON credentials, multiword values, prompts, and malformed payloads are redacted', () => {
  const examples = [
    '{"password":"multi word private phrase","api_key":"sk-verysecretcredentialvalue"}',
    '{"access_token": "unterminated multi word credential',
    'prompt: "private multi word instruction"; password="quoted secret value"',
    'bad provider payload {"refresh_token":"malformed secret with spaces',
  ];
  for (const example of examples) {
    const safe = sanitizeDiagnosticMessage(example);
    assert.ok(safe.length <= 240);
    assert.doesNotMatch(safe, /private phrase|verysecretcredentialvalue|unterminated multi word credential|private multi word instruction|quoted secret value|malformed secret with spaces/);
  }
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
  assert.equal(jobs.status(id).diagnostics.cancelled, true);
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
  assert.deepEqual(buildArgs(TARGET), ['build', '--progress=plain', '--target', 'development',
    '--label', `org.opencontainers.image.revision=${TARGET}`, '--tag', `newshub:dev-${TARGET}`, '/context']);
});

test('tag alone, wrong revision, mismatched local user and wrong entrypoint are not success', () => {
  const image = { Id: `sha256:${'a'.repeat(64)}`, Os: 'linux', Architecture: 'amd64',
    Config: { User: 'root', Cmd: ['/app/docker-entrypoint.sh'],
      Labels: { 'org.opencontainers.image.revision': TARGET } } };
  const result = verifyImage([image], TARGET);
  assert.equal(result.revision, TARGET);
  assert.equal(result.builderImage.location, 'isolated-ci-dind');
  assert.equal(result.builderImage.id, image.Id);
  assert.deepEqual(result.hostRuntime, { status: 'transfer-required', ready: false, imageId: null });
  for (const change of [undefined, { ...image, Id: 'tag-only' },
    { ...image, Config: { ...image.Config, User: '10001:10001' } },
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
