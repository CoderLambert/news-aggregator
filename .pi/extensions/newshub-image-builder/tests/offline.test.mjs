import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm, writeFile, mkdir, chmod } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { execFileSync, spawnSync, spawn } from 'node:child_process';
import { BuildJobs, PROVIDER, MODEL, THINKING, validateTarget, normalizeDiagnostics,
  sanitizeDiagnosticMessage } from '../core.mjs';
import { createImageBuildWorker, classifyChildError } from '../worker.mjs';
import * as buildModule from '../build.mjs';
import { safeRuntimePath, buildArgs, verifyImage, acquireLock, blocked, SOCKET,
  CI_NETWORK, SOCKET_VOLUME, CLIENT_IMAGE, CLIENT_USER, discoverClientTransport, clientArgs,
  validateCommit, createBuild, normalizePlatform, parseImageInspect,
  createCommandRunner, imageInspectArgs, IMAGE_INSPECT_FORMAT } from '../build.mjs';
import { dockerHarness, imageOutput } from './fakes.mjs';
import { resolvePiExecutable } from '../cli.mjs';

const ROOT = new URL('../../../../', import.meta.url).pathname;
const WRAPPER = `${ROOT}/scripts/local-image-build`;
const NODE22_PATH = '/home/lambert/.local/share/mise/installs/node/22.23.3/bin';

async function fakePi(t) {
  const dir = await mkdtemp(join(tmpdir(), 'newshub-fake-pi-'));
  t.after(() => rm(dir, { recursive: true, force: true }));
  const executable = join(dir, 'pi');
  const source = `#!/usr/bin/env node
const fs = require('node:fs');
fs.writeFileSync(process.env.FAKE_ARGS_FILE, JSON.stringify({ args: process.argv.slice(2),
  inheritedPiDir: process.env.PI_CODING_AGENT_DIR, boundSha: process.env.NEWSHUB_LOCAL_IMAGE_BUILD_SHA }));
const mode = process.env.FAKE_MODE || 'success';
if (mode === 'signal') {
  fs.writeFileSync(process.env.FAKE_STARTED_FILE, 'started');
  process.on('SIGTERM', () => { fs.writeFileSync(process.env.FAKE_SIGNAL_FILE, 'SIGTERM'); process.exit(0); });
  setInterval(() => {}, 1000);
} else if (mode === 'malformed') {
  process.stdout.write('{bad json\\n');
} else if (mode === 'unauthorized-hang') {
  process.stdout.write(JSON.stringify({ type: 'session', version: 3 }) + '\\n' +
    JSON.stringify({ type: 'tool_execution_start', toolCallId: 'bad', toolName: 'newshub_image_builder',
      args: { action: 'start', sha: 'b'.repeat(40), authorized: true } }) + '\\n');
  setInterval(() => {}, 1000);
} else {
  const sha = process.env.FAKE_SHA;
  const jobId = 'job-fixed-1';
  const identity = { provider: 'openai-codex', model: 'gpt-6-luna', thinking: 'xhigh' };
  const startSha = mode === 'sha-mismatch' ? 'b'.repeat(40) : sha;
  const receiptSha = mode === 'receipt-sha-mismatch' ? 'b'.repeat(40) : sha;
  const receiptModel = mode === 'receipt-model-mismatch' ? 'gpt-6-wrong' : identity.model;
  const receipt = (status, id = jobId) => ({ id, sha: receiptSha, provider: identity.provider,
    model: receiptModel, thinking: identity.thinking, status,
    ...(status === 'succeeded' ? { result: { revision: sha,
      builderImage: { id: 'sha256:' + 'c'.repeat(64), revision: sha, location: 'host-daemon', platform: 'linux/amd64', user: 'root' },
      hostRuntime: { status: 'ready', ready: true, imageId: 'sha256:' + 'c'.repeat(64) },
      reused: true, buildPerformed: false, buildExitCode: null },
      diagnostics: { imageEvidence: { verified: mode !== 'evidence-missing' } } } : {
      error: 'provider payload api_key=raw-secret', diagnostics: mode === 'build-failed' ? {
        buildErrorCode: 'DOCKER_BUILD_FAILED', buildExitCode: 17,
        buildErrorMessage: 'Docker build failed (exit 17); no retry performed',
      } : { childErrorMessage: 'provider payload api_key=raw-secret' } }) });
  const events = [{ type: 'session', version: 3 },
    { type: 'message_end', message: { role: 'assistant', provider: identity.provider,
      model: mode === 'model-mismatch' ? 'gpt-6-wrong' : identity.model,
      thinkingLevel: 'xhigh', stopReason: 'stop', content: [{ type: 'text', text: 'Finished.' }] } }];
  if (mode !== 'missing' && mode !== 'assistant-text') {
    events.push({ type: 'tool_execution_start', toolCallId: 'start-1', toolName: 'newshub_image_builder',
      args: { action: 'start', sha: startSha, authorized: true } });
    events.push({ type: 'tool_execution_end', toolCallId: 'start-1', toolName: 'newshub_image_builder', isError: false,
      result: { details: receipt('running') } });
    events.push({ type: 'tool_execution_start', toolCallId: 'wait-1', toolName: 'newshub_image_builder',
      args: { action: 'wait', jobId: mode === 'job-mismatch' ? 'job-other' : jobId, waitSeconds: 30 } });
    const terminalReceipt = receipt(['failed', 'build-failed'].includes(mode) ? 'failed' : 'succeeded',
      mode === 'receipt-job-mismatch' ? 'job-other' : jobId);
    if (mode === 'content-receipt') {
      events.push({ type: 'turn_end', toolResults: [{ toolCallId: 'wait-1', toolName: 'newshub_image_builder',
        content: [{ type: 'text', text: JSON.stringify(terminalReceipt) }] }] });
    } else {
      events.push({ type: 'tool_execution_end', toolCallId: 'wait-1', toolName: 'newshub_image_builder', isError: false,
        result: { details: terminalReceipt } });
    }
  }
  if (mode !== 'unsettled') events.push({ type: 'agent_settled', aborted: false });
  process.stdout.write(events.map(event => JSON.stringify(event)).join('\\n') + '\\n');
  if (mode === 'nonzero') process.exitCode = 7;
}
`;
  await writeFile(executable, source);
  await chmod(executable, 0o755);
  return executable;
}

function invokeLocalCli(sha, executable, mode = 'success', extra = {}) {
  const argsFile = extra.argsFile ?? `${executable}.args.json`;
  const env = { ...process.env, PATH: `${NODE22_PATH}:${process.env.PATH}`,
    NEWSHUB_PI_BIN: executable, FAKE_SHA: sha, FAKE_MODE: mode, FAKE_ARGS_FILE: argsFile,
    ...(extra.env ?? {}) };
  const result = spawnSync(WRAPPER, ['--sha', sha, '--execute'], { cwd: ROOT, env,
    encoding: 'utf8', timeout: 10_000, maxBuffer: 2 * 1024 * 1024 });
  return { ...result, argsFile };
}

const TARGET = 'a'.repeat(40); // Synthetic SHA fixture; production requires a real repository commit.

async function syntheticRepo(t) {
  const root = await mkdtemp(join(tmpdir(), 'newshub-builder-git-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  const git = (...args) => execFileSync('git', args, { cwd: root, encoding: 'utf8',
    env: { ...process.env, GIT_CONFIG_GLOBAL: '/dev/null', GIT_TERMINAL_PROMPT: '0' } }).trim();
  git('init', '-q', '-b', 'main');
  git('config', 'user.name', 'Offline Test');
  git('config', 'user.email', 'offline@example.invalid');
  await mkdir(join(root, 'backend'), { recursive: true });
  await writeFile(join(root, 'Dockerfile'), 'FROM scratch\n');
  await writeFile(join(root, '.dockerignore'), '**/.env\n**/*.sqlite3\n**/*.sqlite3-wal\n**/*.sqlite3-shm\n.pi/\n');
  await writeFile(join(root, 'backend/app.py'), 'SOURCE=committed\n');
  git('add', 'Dockerfile', '.dockerignore', 'backend/app.py');
  git('commit', '-qm', 'synthetic base');
  const baseSha = git('rev-parse', 'HEAD');
  git('switch', '-qc', 'feature');
  await writeFile(join(root, 'backend/app.py'), 'SOURCE=feature\n');
  git('add', 'backend/app.py');
  git('commit', '-qm', 'synthetic feature');
  const featureSha = git('rev-parse', 'HEAD');
  return { root, baseSha, featureSha, git };
}

test('existing builder services are preserved, not mistaken for busy workers', () => {
  assert.equal(typeof buildModule.preservedContainerNames, 'function');
  assert.deepEqual(buildModule.preservedContainerNames('adoring_goldberg\nquizzical_kalam\n', 'own-client'),
    ['adoring_goldberg', 'quizzical_kalam']);
  assert.deepEqual(buildModule.preservedContainerNames('own-client\n', 'own-client'), []);
  assert.throws(() => buildModule.preservedContainerNames('invalid;command\n', 'own-client'));
});

test('Docker inspect argument projects only allowlisted HOME/HF_HOME metadata', () => {
  const args = imageInspectArgs(`newshub:dev-${TARGET}`);
  assert.deepEqual(args.slice(0, 3), ['image', 'inspect', '--format']);
  assert.ok(args[3].includes('split . "="'));
  assert.ok(args[3].includes('"HOME"'));
  assert.ok(args[3].includes('"HF_HOME"'));
  assert.equal(args[3].includes('hasPrefix'), false);
  assert.equal(args[3].includes('{{json .Config.Env}}'), false);
  assert.ok(IMAGE_INSPECT_FORMAT.includes('org.opencontainers.image.revision'));
  assert.throws(() => imageInspectArgs('newshub:latest'));
});

test('cleanup command options use their own bounded signal, never the aborted job signal', async () => {
  const job = new AbortController();
  job.abort();
  const cleanup = new AbortController();
  const captured = {};
  const run = createCommandRunner({ root: '/synthetic', signal: job.signal, env: { PATH: '/safe' },
    execFileImpl: async (_bin, _args, options) => { Object.assign(captured, options); return { stdout: '' }; } });
  await run('docker', ['container', 'inspect'], '/synthetic', {
    timeout: 5_000, maxBuffer: 1024, signal: cleanup.signal,
  });
  assert.equal(captured.signal, cleanup.signal);
  assert.equal(captured.signal.aborted, false);
  assert.equal(captured.timeout, 5_000);
  assert.equal(captured.maxBuffer, 1024);
  assert.deepEqual(captured.env, { PATH: '/safe' });
});

test('local image follows the accepted development user and cache contract', () => {
  assert.deepEqual(buildArgs(TARGET), ['build', '--progress=plain', '--target', 'development',
    '--label', `org.opencontainers.image.revision=${TARGET}`, '--tag', `newshub:dev-${TARGET}`, '/context']);
  const image = { Id: `sha256:${'a'.repeat(64)}`, Os: 'linux', Architecture: 'amd64',
    Config: { User: 'root', Cmd: ['/app/docker-entrypoint.sh'], Env: [
      'HOME=/root', 'HF_HOME=/root/.cache/huggingface',
    ], Labels: { 'org.opencontainers.image.revision': TARGET } } };
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
  builderImage: { id: `sha256:${'a'.repeat(64)}`, revision: TARGET, location: 'isolated-ci-dind' },
  hostRuntime: { status: 'transfer-required', ready: false, imageId: null },
  reused: true, buildPerformed: false, buildExitCode: null,
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
      validateSource: async () => {},
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

test('accepts another explicit exact lowercase SHA without pinning it to main', () => {
  const otherSha = 'c'.repeat(40);
  assert.equal(validateTarget(otherSha), otherSha);
});

test('image reuse rejects mismatched native platform and HOME/HF_HOME cache contract', () => {
  const image = { Id: `sha256:${'a'.repeat(64)}`, Os: 'linux', Architecture: 'amd64',
    Config: { User: 'root', Cmd: ['/app/docker-entrypoint.sh'], Env: [
      'HOME=/root', 'HF_HOME=/root/.cache/huggingface', 'API_KEY=must-not-be-inspected',
    ], Labels: { 'org.opencontainers.image.revision': TARGET } } };
  assert.doesNotThrow(() => verifyImage([image], TARGET, 'linux/x86_64'));
  for (const mutate of [
    value => { value.Architecture = 'arm64'; },
    value => { value.Config.Env[0] = 'HOME=/tmp'; },
    value => { value.Config.Env[1] = 'HF_HOME=/cache'; },
  ]) {
    const mismatched = structuredClone(image);
    mutate(mismatched);
    assert.throws(() => verifyImage([mismatched], TARGET, 'linux/amd64'));
  }
});

test('exact SHA syntax rejects omitted, abbreviated, ref, uppercase, and expression inputs', () => {
  for (const sha of [undefined, '', 'main', TARGET.slice(0, 8), 'A'.repeat(40), `${TARGET}; docker push x`]) {
    assert.throws(() => validateTarget(sha));
  }
});

test('repository proof accepts a feature commit and rejects tag, blob, unknown, and ref inputs', async t => {
  const repo = await syntheticRepo(t);
  const build = createBuild(repo.root, new AbortController().signal);
  assert.equal(await build.validateSource(repo.featureSha), repo.featureSha);
  repo.git('tag', '-a', 'feature-tag', '-m', 'annotated');
  const tagObject = repo.git('rev-parse', 'refs/tags/feature-tag');
  const blob = repo.git('rev-parse', `${repo.featureSha}:backend/app.py`);
  await assert.rejects(build.validateSource(tagObject), /not a commit object/);
  await assert.rejects(build.validateSource(blob), /not a commit object/);
  await assert.rejects(build.validateSource('f'.repeat(40)), /not a commit object/);
  await assert.rejects(build.validateSource('feature'), /lowercase 40-hex/);
});

test('verified host image reuse needs only a fake host inspect and returns matching ready image ID', async t => {
  const repo = await syntheticRepo(t);
  const commands = [];
  const runner = async (bin, args, cwd) => {
    commands.push([bin, args]);
    if (bin === 'git') return { stdout: execFileSync(bin, args, { cwd, encoding: 'utf8' }) };
    assert.deepEqual(args.slice(0, 3), ['image', 'inspect', '--format']);
    return { stdout: imageOutput({ revision: repo.featureSha, architecture: 'x86_64' }) };
  };
  const build = createBuild(repo.root, new AbortController().signal, {
    runCommand: runner, requestedPlatform: 'linux/x86_64',
  });
  const result = await build.build(repo.featureSha);
  assert.equal(result.reused, true);
  assert.equal(result.buildPerformed, false);
  assert.equal(result.buildExitCode, null);
  assert.equal(result.hostRuntime.status, 'ready');
  assert.equal(result.hostRuntime.imageId, result.builderImage.id);
  assert.equal(result.builderImage.location, 'host-daemon');
  assert.equal(result.builderImage.platform, 'linux/amd64');
  assert.deepEqual(commands.filter(([bin]) => bin === 'docker').map(([, args]) => args.slice(0, 2)), [['image', 'inspect']]);
  assert.equal(commands.some(([bin, args]) => bin === 'ps' || args.includes('ls-tree')), false);
});

test('conflicting host metadata and daemon access failures fail closed without DinD fallback', async t => {
  const repo = await syntheticRepo(t);
  for (const [name, failure] of [
    ['revision', imageOutput({ revision: repo.baseSha })],
    ['platform', imageOutput({ revision: repo.featureSha, architecture: 'arm64' })],
    ['user', imageOutput({ revision: repo.featureSha, user: '10001:10001' })],
    ['command', imageOutput({ revision: repo.featureSha, cmd: ['sh'] })],
    ['cache', imageOutput({ revision: repo.featureSha, env: ['HOME=/root', 'HF_HOME=/cache'] })],
    ['daemon', Object.assign(new Error('private daemon diagnostic'), { code: 1, stderr: 'Cannot connect to the Docker daemon' })],
  ]) {
    const calls = [];
    const runner = async (bin, args, cwd) => {
      calls.push([bin, args]);
      if (bin === 'git') return { stdout: execFileSync(bin, args, { cwd, encoding: 'utf8' }) };
      if (name === 'daemon') throw failure;
      return { stdout: failure };
    };
    const build = createBuild(repo.root, new AbortController().signal, { runCommand: runner,
      requestedPlatform: 'linux/amd64' });
    await assert.rejects(build.build(repo.featureSha), /Image metadata|daemon access/);
    assert.equal(calls.filter(([bin]) => bin === 'docker').length, 1, name);
  }
});

test('private DinD image reuse skips source export/build and does not require idle Runner.Worker', async t => {
  const repo = await syntheticRepo(t);
  const fake = dockerHarness(repo, { privateImage: 'verified', activeWorker: true });
  const build = createBuild(repo.root, new AbortController().signal, { ...fake, requestedPlatform: 'linux/amd64' });
  const result = await build.build(repo.featureSha);
  assert.equal(result.reused, true);
  assert.equal(result.buildPerformed, false);
  assert.equal(result.buildExitCode, null);
  assert.equal(result.hostRuntime.status, 'transfer-required');
  assert.equal(result.builderImage.location, 'isolated-ci-dind');
  assert.equal(fake.calls.some(args => args[0] === 'top'), false);
  assert.equal(fake.calls.some(args => args[0] === 'build'), false);
  assert.equal(fake.gitCalls.some(args => args.includes('ls-tree')), false);
});

test('private cache conflicts and daemon failures never fall through to a fresh build', async t => {
  const repo = await syntheticRepo(t);
  for (const privateImage of [
    { revision: repo.baseSha }, { architecture: 'arm64' }, { user: '10001:10001' },
    { cmd: ['sh'] }, { env: ['HOME=/root', 'HF_HOME=/cache'] }, 'daemon',
  ]) {
    const fake = dockerHarness(repo, { privateImage });
    const build = createBuild(repo.root, new AbortController().signal, { ...fake, requestedPlatform: 'linux/amd64' });
    await assert.rejects(build.build(repo.featureSha), /Image metadata|daemon/);
    assert.equal(fake.calls.some(args => args.includes('build')), false);
  }
});

test('missing host/private tags choose one isolated development build after Runner.Worker checks', async t => {
  const repo = await syntheticRepo(t);
  const fake = dockerHarness(repo, { privateImage: 'missing' });
  const build = createBuild(repo.root, new AbortController().signal, { ...fake, requestedPlatform: 'linux/amd64' });
  const result = await build.build(repo.featureSha);
  assert.equal(result.reused, false);
  assert.equal(result.buildPerformed, true);
  assert.equal(result.buildExitCode, 0);
  assert.deepEqual(result.preservedBuilderContainers, ['redis-container']);
  assert.equal(fake.calls.some(args => args[0] === 'top'), true);
  assert.equal(fake.gitCalls.some(args => args.includes('ls-tree')), true);
  assert.equal(result.command.includes('--target'), true);
  assert.equal(result.command[result.command.indexOf('--target') + 1], 'development');
  assert.equal(result.note.includes('transfer is required'), true);
});

test('busy Runner.Worker blocks fresh build before immutable source export or build', async t => {
  const repo = await syntheticRepo(t);
  const fake = dockerHarness(repo, { privateImage: 'missing', activeWorker: true });
  const build = createBuild(repo.root, new AbortController().signal, { ...fake, requestedPlatform: 'linux/amd64' });
  await assert.rejects(build.build(repo.featureSha), /Runner.Worker is active/);
  assert.equal(fake.calls.some(args => args[0] === 'top'), true);
  assert.equal(fake.calls.some(args => args.includes('build')), false);
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

test('BuildJobs accepts only verified host-ready reuse, private-transfer reuse, or real completed build states', async () => {
  const hostId = `sha256:${'e'.repeat(64)}`;
  const hostResult = { ...verifiedResult, builderImage: { ...verifiedResult.builderImage,
    id: hostId, location: 'host-daemon' }, hostRuntime: { status: 'ready', ready: true, imageId: hostId } };
  const builtResult = { ...verifiedResult, reused: false, buildPerformed: true, buildExitCode: 0 };
  for (const result of [hostResult, verifiedResult, builtResult]) {
    const jobs = new BuildJobs(async () => result);
    const started = jobs.start(TARGET, true);
    assert.equal((await jobs.wait(started.id, 1)).status, 'succeeded');
  }
  for (const result of [
    { ...verifiedResult, buildPerformed: false, buildExitCode: 0 },
    { ...verifiedResult, reused: false, buildPerformed: true, buildExitCode: null },
    { ...hostResult, hostRuntime: { status: 'ready', ready: true, imageId: 'sha256:wrong' } },
  ]) {
    const jobs = new BuildJobs(async () => result);
    const started = jobs.start(TARGET, true);
    const refused = await jobs.wait(started.id, 1);
    assert.equal(refused.status, 'blocked');
    assert.equal(refused.result, undefined);
    assert.equal(refused.diagnostics.imageEvidence.verified, false);
  }
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
      Env: ['HOME=/root', 'HF_HOME=/root/.cache/huggingface'],
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

test('Pi executable resolution supports read-only PATH fallback without installers', async t => {
  const fake = await fakePi(t);
  assert.equal(await resolvePiExecutable({ PATH: join(fake, '..'), HOME: join(fake, '..') }), fake);
  assert.equal(await resolvePiExecutable({ NEWSHUB_PI_BIN: fake, PATH: '', HOME: join(fake, '..') }), fake);
});

test('common CLI launches only fixed Luna argv and accepts a verified JSONL terminal receipt', async t => {
  const sha = execFileSync('git', ['rev-parse', 'HEAD'], { cwd: ROOT, encoding: 'utf8' }).trim();
  const fake = await fakePi(t);
  const result = invokeLocalCli(sha, fake, 'success', { env: { PI_CODING_AGENT_DIR: '/tmp/custom-pi-auth' } });
  assert.equal(result.status, 0, result.stderr);
  const terminal = JSON.parse(result.stdout);
  assert.equal(terminal.ok, true);
  assert.equal(terminal.sha, sha);
  assert.equal(terminal.provider, 'openai-codex');
  assert.equal(terminal.model, 'gpt-6-luna');
  assert.equal(terminal.thinking, 'xhigh');
  assert.equal(terminal.status, 'succeeded');
  const contentResult = invokeLocalCli(sha, fake, 'content-receipt', { argsFile: `${fake}.content.args` });
  assert.equal(contentResult.status, 0, contentResult.stderr);
  assert.equal(JSON.parse(contentResult.stdout).jobId, 'job-fixed-1');
  const captured = JSON.parse(await readFile(result.argsFile, 'utf8'));
  const argv = captured.args;
  assert.equal(captured.boundSha, sha);
  assert.equal(captured.inheritedPiDir, '/tmp/custom-pi-auth');
  for (const pair of [
    ['--model', 'openai-codex/gpt-6-luna'], ['--thinking', 'xhigh'],
    ['--tools', 'newshub_image_builder'], ['--name', 'newshub-local-image-builder-luna'],
    ['--mode', 'json'],
  ]) assert.deepEqual(argv.slice(argv.indexOf(pair[0]), argv.indexOf(pair[0]) + 2), pair);
  for (const flag of ['--no-extensions', '--no-mcp', '--no-skills', '--no-prompt-templates',
    '--no-context-files', '--no-approve', '--no-session']) assert.ok(argv.includes(flag), flag);
  assert.equal(argv[argv.indexOf('--extension') + 1], join(ROOT, '.pi/extensions/newshub-image-builder/index.ts'));
  assert.match(argv.at(-1), new RegExp(sha));
  assert.equal(argv.includes('--api-key'), false);
});

test('common CLI rejects missing, failed, malformed, unsettled, mismatched, and text-only receipts', async t => {
  const sha = execFileSync('git', ['rev-parse', 'HEAD'], { cwd: ROOT, encoding: 'utf8' }).trim();
  const fake = await fakePi(t);
  const cases = [
    ['missing', 5], ['assistant-text', 5], ['failed', 6], ['build-failed', 6],
    ['malformed', 5], ['unsettled', 5], ['unauthorized-hang', 5],
    ['nonzero', 4], ['model-mismatch', 5], ['sha-mismatch', 5], ['receipt-sha-mismatch', 5],
    ['job-mismatch', 5], ['receipt-job-mismatch', 5], ['receipt-model-mismatch', 5],
    ['evidence-missing', 6],
  ];
  for (const [mode, expectedExit] of cases) {
    const result = invokeLocalCli(sha, fake, mode);
    assert.equal(result.status, expectedExit, `${mode}: ${result.stderr}`);
    assert.equal(result.stdout, '', mode);
    assert.doesNotMatch(result.stderr, /api_key|secret|private prompt|provider payload/);
    const error = JSON.parse(result.stderr);
    assert.equal(error.ok, false, mode);
  }
  const failed = invokeLocalCli(sha, fake, 'failed');
  const failedOutput = JSON.parse(failed.stderr);
  assert.equal(failedOutput.job.id, 'job-fixed-1');
  assert.equal(failedOutput.job.sha, sha);
  assert.equal(failedOutput.job.status, 'failed');
  assert.equal(failedOutput.job.diagnostics.childErrorMessage, 'Child inference failed (details redacted)');
  assert.doesNotMatch(JSON.stringify(failedOutput), /raw-secret|provider payload/);
  const buildFailed = JSON.parse(invokeLocalCli(sha, fake, 'build-failed').stderr);
  assert.equal(buildFailed.job.diagnostics.buildErrorCode, 'DOCKER_BUILD_FAILED');
  assert.equal(buildFailed.job.diagnostics.buildExitCode, 17);
  assert.equal(buildFailed.job.error, 'Docker build failed (exit 17); no retry performed');
  const injectionArgs = `${fake}.injection.args`;
  const injected = spawnSync(WRAPPER, ['--sha', sha, '--execute', '--model', 'gpt-6-wrong'], {
    cwd: ROOT, encoding: 'utf8', env: { ...process.env, PATH: `${NODE22_PATH}:${process.env.PATH}`,
      NEWSHUB_PI_BIN: fake, FAKE_ARGS_FILE: injectionArgs },
  });
  assert.equal(injected.status, 2);
  assert.equal(injected.stdout, '');
  await assert.rejects(readFile(injectionArgs));
});

test('common CLI cancellation signals only its native Pi child and never reports success', async t => {
  const sha = execFileSync('git', ['rev-parse', 'HEAD'], { cwd: ROOT, encoding: 'utf8' }).trim();
  const fake = await fakePi(t);
  const dir = join(fake, '..');
  const started = join(dir, 'started');
  const signalled = join(dir, 'signalled');
  const child = spawn(WRAPPER, ['--sha', sha, '--execute'], { cwd: ROOT, env: {
    ...process.env, PATH: `${NODE22_PATH}:${process.env.PATH}`, NEWSHUB_PI_BIN: fake,
    FAKE_SHA: sha, FAKE_MODE: 'signal', FAKE_ARGS_FILE: `${fake}.signal-args`,
    FAKE_STARTED_FILE: started, FAKE_SIGNAL_FILE: signalled,
  }, stdio: ['ignore', 'pipe', 'pipe'] });
  let stdout = '';
  let stderr = '';
  child.stdout.setEncoding('utf8').on('data', chunk => { stdout += chunk; });
  child.stderr.setEncoding('utf8').on('data', chunk => { stderr += chunk; });
  const closed = new Promise(resolve => child.once('close', (code, signal) => resolve({ code, signal })));
  const deadline = Date.now() + 5000;
  while (Date.now() < deadline) {
    try { await readFile(started); break; }
    catch { await new Promise(resolve => setTimeout(resolve, 20)); }
  }
  await readFile(started);
  child.kill('SIGTERM');
  const result = await closed;
  assert.equal(result.code, 130);
  assert.equal(stdout, '');
  assert.equal(JSON.parse(stderr).error.code, 'CANCELLED');
  assert.equal(await readFile(signalled, 'utf8'), 'SIGTERM');
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
