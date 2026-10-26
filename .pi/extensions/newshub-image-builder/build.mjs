import { execFile, spawn } from 'node:child_process';
import { promisify } from 'node:util';
import { mkdir, mkdtemp, writeFile, readFile, unlink, chmod } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { randomUUID } from 'node:crypto';
import { validateTarget } from './core.mjs';

const exec = promisify(execFile);
export const SOCKET = '/ci-docker/docker.sock'; // Inside the disposable client only.
export const CI_PROJECT = 'newshub-ci';
export const CI_NETWORK = 'newshub-ci_default';
export const SOCKET_VOLUME = 'newshub-ci_runner-socket';
export const CLIENT_IMAGE = 'docker:29-dind';
export const CLIENT_USER = '1001:121';
export const RULES = ['AGENTS.md', 'ops/ci/AGENTS.md', 'scripts/deploy/AGENTS.md',
  'ops/ci/build-release-policy.md', 'Dockerfile', '.dockerignore'];

export function blocked(message) {
  const error = new Error(message);
  error.code = 'NEWSHUB_BLOCKED';
  error.safeMessage = message;
  return error;
}

export function safeRuntimePath(path) {
  if (!path || path.startsWith('/') || /[\\\x00-\x1f]/.test(path)) return false;
  const parts = path.split('/');
  if (parts.some(p => !p || p === '.' || p === '..' || p.startsWith('.env') ||
      ['.git', '.pi', '.omp', '.agents', '.worktrees', '.runtime', '.cache',
        'node_modules', 'venv', '__pycache__', 'logs', 'media', 'chroma_data', 'secrets', 'credentials'].includes(p))) return false;
  if (/\.(?:sqlite3?(?:-wal|-shm|-journal)?|db(?:-wal|-shm|-journal)?|pem|key|p12|pfx|crt|cer|log)$/i.test(path) ||
      /(?:^|\/)(?:auth|credentials)\.json$/i.test(path)) return false;
  return ['Dockerfile', '.dockerignore', 'start_waitress.py', 'scripts/docker-migrate.py',
    'scripts/docker-entrypoint.sh'].includes(path) || /^(backend|frontend)\//.test(path);
}

function labelsOf(container) { return container?.Config?.Labels ?? {}; }
function hasMount(container, volume, destination) {
  return container?.Mounts?.some(mount => mount.Type === 'volume' &&
    mount.Name === volume && mount.Destination === destination) ?? false;
}
function assertService(container, name, service) {
  const labels = labelsOf(container);
  if (container?.Name !== `/${name}` ||
      labels['com.docker.compose.project'] !== CI_PROJECT ||
      labels['com.docker.compose.service'] !== service ||
      container?.State?.Status !== 'running' || container?.State?.Running !== true ||
      container?.State?.Health?.Status !== 'healthy') {
    throw blocked(`Expected healthy ${CI_PROJECT}/${service} Compose service ${name}`);
  }
}

// Pure validation of only the metadata needed to safely reach the existing DinD.
export function discoverClientTransport({ dind, runner, frontend, network, socketVolume, clientImage }) {
  assertService(dind, 'newshub-ci-docker-1', 'docker');
  assertService(runner, 'newshub-ci-runner-1', 'runner');
  assertService(frontend, 'newshub-ci-runner-frontend-1', 'runner-frontend');
  if (!hasMount(dind, SOCKET_VOLUME, '/ci-docker') ||
      !hasMount(runner, SOCKET_VOLUME, '/ci-docker') ||
      frontend?.Mounts?.some(mount => mount.Destination === '/ci-docker')) {
    throw blocked('The expected private runner-socket volume mapping is absent or exposed to the frontend runner');
  }
  const volumeLabels = socketVolume?.Labels ?? {};
  if (socketVolume?.Name !== SOCKET_VOLUME ||
      volumeLabels['com.docker.compose.project'] !== CI_PROJECT ||
      volumeLabels['com.docker.compose.volume'] !== 'runner-socket') {
    throw blocked('The expected private Compose socket volume is unavailable');
  }
  const networkContainers = Object.values(network?.Containers ?? {}).map(item => item.Name);
  if (network?.Name !== CI_NETWORK || network?.Driver !== 'bridge' ||
      network?.Labels?.['com.docker.compose.project'] !== CI_PROJECT ||
      !['newshub-ci-docker-1', 'newshub-ci-runner-1', 'newshub-ci-runner-frontend-1']
        .every(name => networkContainers.includes(name))) {
    throw blocked('The existing healthy CI bridge network is unavailable or mismatched');
  }
  if (!clientImage?.Id?.match(/^sha256:[0-9a-f]{64}$/) ||
      clientImage.Os !== 'linux' || !clientImage.Architecture || clientImage.Id !== dind.Image) {
    throw blocked('The matching local Docker CLI client image is unavailable; pulling is forbidden');
  }
  return { network: CI_NETWORK, socketVolume: SOCKET_VOLUME,
    clientImage: CLIENT_IMAGE, clientImageId: clientImage.Id };
}

// Arguments for one task-owned client. No host socket, state/work volume or credentials.
export function clientArgs({ name, taskId, context, command, transport }) {
  if (!/^newshub-image-builder-[0-9a-f-]{36}$/.test(name ?? '') ||
      !/^[0-9a-f-]{36}$/.test(taskId ?? '') || name !== `newshub-image-builder-${taskId}` ||
      !resolve(context ?? '').startsWith('/') || !Array.isArray(command) ||
      command.some(arg => typeof arg !== 'string' || /[\x00\r\n]/.test(arg)) ||
      transport?.network !== CI_NETWORK || transport?.socketVolume !== SOCKET_VOLUME ||
      transport?.clientImage !== CLIENT_IMAGE ||
      !/^sha256:[0-9a-f]{64}$/.test(transport?.clientImageId ?? '')) {
    throw blocked('Disposable client arguments do not match the isolated CI transport');
  }
  return ['run', '--pull=never', '--rm', '--name', name,
    '--label', `com.newshub.pi-image-builder.task=${taskId}`,
    '--network', transport.network, '--user', CLIENT_USER,
    '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
    '--env', 'HOME=/tmp', '--env', 'DOCKER_CONFIG=/tmp/.docker',
    '--env', `DOCKER_HOST=unix://${SOCKET}`, '--tmpfs', '/tmp:rw,nosuid,nodev,mode=1777',
    '--mount', `type=volume,source=${transport.socketVolume},target=/ci-docker,readonly`,
    '--mount', `type=bind,source=${resolve(context)},target=/context,readonly`,
    '--workdir', '/context', '--entrypoint', 'docker', transport.clientImageId, ...command];
}

// Existing services are not evidence that a CI job is active. Runner.Worker
// checks above and the cross-session lock guard build ownership; leave existing
// daemon services running and record their names instead of replacing them.
export function preservedContainerNames(stdout, clientName) {
  const names = String(stdout).split(/\r?\n/).map(name => name.trim()).filter(Boolean);
  if (names.some(name => !/^[A-Za-z0-9][A-Za-z0-9_.-]*$/.test(name))) {
    throw blocked('Isolated builder returned malformed container metadata');
  }
  return names.filter(name => name !== clientName);
}

export function buildArgs(sha) {
  validateTarget(sha);
  // This is the existing local development contract, not a production release.
  // A late metadata label preserves exact source identity without changing
  // dependency layers, the accepted runtime user, data ownership or cache path.
  return ['build', '--progress=plain', '--target', 'development', '--label',
    `org.opencontainers.image.revision=${sha}`, '--tag', `newshub:dev-${sha}`, '/context'];
}

export function verifyImage(items, sha) {
  const image = items?.[0];
  if (!image?.Id?.match(/^sha256:[0-9a-f]{64}$/) ||
      image.Config?.Labels?.['org.opencontainers.image.revision'] !== sha ||
      image.Config?.User !== 'root' ||
      JSON.stringify(image.Config?.Cmd) !== JSON.stringify(['/app/docker-entrypoint.sh']) ||
      image.Os !== 'linux' || !image.Architecture) {
    throw blocked('Private builder image metadata does not match the exact source/local-development runtime contract');
  }
  return {
    builderImage: { location: 'isolated-ci-dind', reference: `newshub:dev-${sha}`,
      id: image.Id, digests: image.RepoDigests ?? [],
      platform: `${image.Os}/${image.Architecture}`, revision: sha, user: image.Config.User },
    hostRuntime: { status: 'transfer-required', ready: false, imageId: null },
    revision: sha,
  };
}

export async function acquireLock(path) {
  const token = randomUUID();
  try {
    await writeFile(path, JSON.stringify({ pid: process.pid, token }), { flag: 'wx', mode: 0o600 });
  } catch (error) {
    if (error.code === 'EEXIST') throw blocked('Another or interrupted build owns the lock; do not start a duplicate');
    throw error;
  }
  return async () => {
    const owner = JSON.parse(await readFile(path, 'utf8'));
    if (owner.token !== token) throw blocked('Build lock ownership changed; lock preserved');
    await unlink(path);
  };
}

export function createBuild(root, signal) {
  // Docker overrides/config/auth are intentionally not inherited by host orchestration.
  const env = { PATH: process.env.PATH, HOME: '/nonexistent', DOCKER_CONFIG: '/nonexistent/.docker',
    LANG: 'C.UTF-8', GIT_CONFIG_NOSYSTEM: '1', GIT_CONFIG_GLOBAL: '/dev/null', GIT_TERMINAL_PROMPT: '0' };
  const run = (bin, args, cwd = root, extra = {}) => exec(bin, args, {
    cwd, env: { ...env, ...extra }, timeout: 30_000, maxBuffer: 32 * 1024 * 1024, signal,
  });
  const git = async (...args) => (await run('git', args)).stdout;
  let used = false;
  let evidence;
  return {
    rules: async sha => {
      validateTarget(sha);
      const documents = [];
      for (const path of RULES) documents.push(`# ${path}\n${await git('show', `${sha}:${path}`)}`);
      return documents.join('\n\n');
    },
    evidence: () => evidence,
    build: async sha => {
      validateTarget(sha);
      if (used) throw blocked('One build attempt per job; retries require a new explicit request');
      used = true;
      try {
        await run('git', ['merge-base', '--is-ancestor', sha, 'refs/heads/main']);
      } catch {
        throw blocked('The accepted source SHA is not present in local main history');
      }
      const common = resolve(root, (await git('rev-parse', '--git-common-dir')).trim());
      const release = await acquireLock(join(common, 'newshub-pi-image-builder.lock'));
      let safeToReleaseLock = true;
      try {
        // No process arguments are returned to the model or logs.
        const processes = (await run('ps', ['-eo', 'comm=,args='])).stdout;
        if (processes.split('\n').some(line => /^(?:omp|docker|buildctl|buildkitd|buildx)\s/.test(line.trim()) ||
            /^(?:node|bun)\s+\S*\/(?:omp|oh-my-pi)(?:\/|\s|$)/.test(line.trim()))) {
          throw blocked('A prior OMP/build process may still be active; resolve it before building');
        }

        const fields = async (args, count) => {
          const output = (await run('docker', args)).stdout.replace(/\r?\n$/, '').split('\t');
          if (output.length !== count) throw blocked('Docker returned incomplete metadata for isolated-builder discovery');
          return output;
        };
        const inspectContainer = async name => {
          const format = '{{json .Name}}\t{{json .Image}}\t{{json (index .Config.Labels "com.docker.compose.project")}}\t{{json (index .Config.Labels "com.docker.compose.service")}}\t{{json .State.Status}}\t{{json .State.Running}}\t{{if .State.Health}}{{json .State.Health.Status}}{{else}}null{{end}}\t{{range .Mounts}}{{.Type}}|{{.Name}}|{{.Destination}},{{end}}\t{{range $name, $network := .NetworkSettings.Networks}}{{$name}},{{end}}';
          const [containerName, image, project, service, status, running, health, mounts, networks] = await fields(['inspect', '--format', format, name], 9);
          return { Name: JSON.parse(containerName), Image: JSON.parse(image),
            Config: { Labels: { 'com.docker.compose.project': JSON.parse(project), 'com.docker.compose.service': JSON.parse(service) } },
            State: { Status: JSON.parse(status), Running: JSON.parse(running), Health: { Status: JSON.parse(health) } },
            Mounts: mounts.split(',').filter(Boolean).map(item => {
              const [Type, Name, Destination] = item.split('|'); return { Type, Name: Name || null, Destination };
            }), NetworkSettings: { Networks: Object.fromEntries(networks.split(',').filter(Boolean).map(key => [key, {}])) } };
        };
        const [dind, runner, frontend] = await Promise.all([
          inspectContainer('newshub-ci-docker-1'), inspectContainer('newshub-ci-runner-1'),
          inspectContainer('newshub-ci-runner-frontend-1'),
        ]);
        const [networkName, networkDriver, networkProject, networkMembers] = await fields([
          'network', 'inspect', '--format', '{{.Name}}\t{{.Driver}}\t{{index .Labels "com.docker.compose.project"}}\t{{range $id, $container := .Containers}}{{$container.Name}},{{end}}', CI_NETWORK,
        ], 4);
        const network = { Name: networkName, Driver: networkDriver,
          Labels: { 'com.docker.compose.project': networkProject },
          Containers: Object.fromEntries(networkMembers.split(',').filter(Boolean).map((name, i) => [i, { Name: name }])) };
        const [volumeName, volumeProject, volumeLabel] = await fields([
          'volume', 'inspect', '--format', '{{.Name}}\t{{index .Labels "com.docker.compose.project"}}\t{{index .Labels "com.docker.compose.volume"}}', SOCKET_VOLUME,
        ], 3);
        const socketVolume = { Name: volumeName, Labels: {
          'com.docker.compose.project': volumeProject, 'com.docker.compose.volume': volumeLabel,
        } };
        const [imageId, repoDigests, clientOs, clientArchitecture] = await fields([
          'image', 'inspect', '--format', '{{json .Id}}\t{{json .RepoDigests}}\t{{json .Os}}\t{{json .Architecture}}', CLIENT_IMAGE,
        ], 4);
        const clientImage = { Id: JSON.parse(imageId), RepoDigests: JSON.parse(repoDigests),
          Os: JSON.parse(clientOs), Architecture: JSON.parse(clientArchitecture) };
        const transport = discoverClientTransport({ dind, runner, frontend, network, socketVolume, clientImage });

        for (const name of ['newshub-ci-runner-1', 'newshub-ci-runner-frontend-1']) {
          const { stdout } = await run('docker', ['top', name, '-eo', 'pid,comm']);
          const lines = stdout.trim().split(/\r?\n/);
          if (!/^PID\s+COMMAND$/i.test(lines[0] ?? '') || lines.length < 2 ||
              lines.slice(1).some(line => !/^\s*\d+\s+\S/.test(line))) {
            throw blocked(`Cannot confirm ${name} is idle; Docker top metadata was incomplete`);
          }
          if (lines.slice(1).some(line => /\bRunner\.Worker(?:\.dll)?\b/i.test(line))) {
            throw blocked(`A Runner.Worker is active in ${name}; refusing to use the CI builder`);
          }
        }

        const scratch = await mkdtemp(join(tmpdir(), 'newshub-pi-build-'));
        const context = join(scratch, 'context');
        await mkdir(context, { mode: 0o700 });
        // Export only safe immutable Git blobs. No live worktree file, user DB,
        // symlink target or .env is opened, hashed, archived or copied.
        const tree = await git('ls-tree', '-rz', '-r', sha);
        for (const entry of tree.split('\0').filter(Boolean)) {
          const match = /^(\d+) blob ([0-9a-f]{40})\t(.+)$/.exec(entry);
          if (!match || !safeRuntimePath(match[3])) continue;
          const [, mode, oid, path] = match;
          if (!['100644', '100755'].includes(mode)) throw blocked('Symlink or special runtime input rejected');
          const size = Number((await git('cat-file', '-s', oid)).trim());
          if (!Number.isSafeInteger(size) || size > 16 * 1024 * 1024) throw blocked('Oversized runtime input rejected');
          const { stdout } = await exec('git', ['cat-file', 'blob', oid], {
            cwd: root, env, signal, encoding: 'buffer', maxBuffer: 16 * 1024 * 1024, timeout: 30_000,
          });
          const dest = join(context, path);
          await mkdir(dirname(dest), { recursive: true });
          await writeFile(dest, stdout, { mode: mode === '100755' ? 0o755 : 0o644 });
        }
        const ignore = await readFile(join(context, '.dockerignore'), 'utf8');
        if (!['**/.env', '**/*.sqlite3', '**/*.sqlite3-wal', '**/*.sqlite3-shm', '.pi/']
          .every(pattern => ignore.split('\n').includes(pattern)) || /^\s*!/m.test(ignore)) {
          throw blocked('Committed Docker context exclusions are unsafe');
        }
        // The client is UID 1001/GID 121; expose only this sanitized root, not its parent.
        await chmod(context, 0o755);

        const taskId = randomUUID();
        const clientName = `newshub-image-builder-${taskId}`;
        const cleanupRun = (args) => exec('docker', args, {
          cwd: root, env, timeout: 5_000, maxBuffer: 1024 * 1024,
          signal: AbortSignal.timeout(5_000),
        });
        const client = async (command, stream = false) => {
          // Refuse collisions, and cleanup only a container carrying this task's label.
          try {
            await run('docker', ['container', 'inspect', '--format', '{{.Id}}', clientName]);
            throw blocked('Task-unique Docker client name already exists; it was left untouched');
          } catch (error) {
            if (error?.code === 'NEWSHUB_BLOCKED') throw error;
            if (error?.code !== 1 || !/No such object|No such container/i.test(error?.stderr ?? '')) throw error;
          }
          const args = clientArgs({ name: clientName, taskId, context,
            command: Array.isArray(command) ? command : buildArgs(sha), transport });
          try {
            if (!stream) return await run('docker', args, context);
            return await new Promise(resolveCode => {
              const child = spawn('docker', args, { cwd: context, env, signal,
                stdio: ['ignore', 'pipe', 'pipe'] });
              let pending = '';
              const feed = chunk => {
                pending = (pending + chunk.toString()).slice(-65536);
                const lines = pending.split('\n');
                pending = lines.pop();
                for (const line of lines) {
                  if (/^#\d+ CACHED\s*$/.test(line)) cache.cachedMarkers++;
                  if (/^#\d+ DONE [\d.]+s\s*$/.test(line)) cache.executedMarkers++;
                }
              };
              child.stdout.on('data', feed);
              child.stderr.on('data', feed);
              let processError = false;
              child.once('error', () => { processError = true; });
              // Always wait for close after abort/error before releasing the cross-session lock.
              child.once('close', (code, sig) => resolveCode({ code: processError || sig ? 128 : code, signal: sig }));
            });
          } finally {
            try {
              const { stdout } = await cleanupRun(['container', 'inspect', '--format', '{{json (index .Config.Labels "com.newshub.pi-image-builder.task")}}', clientName]);
              if (JSON.parse(stdout.trim()) === taskId) {
                await cleanupRun(['container', 'rm', '--force', clientName]);
              } else {
                throw blocked('Disposable client ownership changed; resource was left untouched');
              }
            } catch (error) {
              const missing = error?.code === 1 && /No such object|No such container|not found/i.test(error?.stderr ?? '');
              if (!missing) {
                safeToReleaseLock = false;
                throw blocked('Could not verify/clean only the task-owned disposable client; its lock is preserved and no successful result is reported');
              }
            }
          }
        };

        const preservedBuilderContainers = preservedContainerNames(
          (await client(['ps', '--format', '{{.Names}}'])).stdout, clientName);
        const tag = `newshub:dev-${sha}`;
        if ((await client(['image', 'ls', '-q', tag])).stdout.trim()) {
          throw blocked('Exact target tag already exists; inspect it rather than overwrite it');
        }

        const cache = { cachedMarkers: 0, executedMarkers: 0 };
        const buildResult = await client(buildArgs(sha), true);
        if (buildResult.code !== 0) throw blocked(`Docker build failed (exit ${buildResult.code}); no retry performed`);
        const imageFormat = '{{json .Id}}\t{{json .RepoDigests}}\t{{json .Os}}\t{{json .Architecture}}\t{{json .Config.User}}\t{{json .Config.Cmd}}\t{{json (index .Config.Labels "org.opencontainers.image.revision")}}';
        const inspected = await client(['image', 'inspect', '--format', imageFormat, tag]);
        const imageFields = inspected.stdout.replace(/\r?\n$/, '').split('\t');
        if (imageFields.length !== 7) throw blocked('Docker returned incomplete private-image verification metadata');
        const [id, digests, targetOs, targetArchitecture, user, cmd, revision] = imageFields.map(value => JSON.parse(value));
        const image = { Id: id, RepoDigests: digests, Os: targetOs, Architecture: targetArchitecture,
          Config: { User: user, Cmd: cmd, Labels: { 'org.opencontainers.image.revision': revision } } };
        evidence = { ...verifyImage([image], sha), exitCode: buildResult.code,
          command: ['docker', 'run', '--pull=never', '--entrypoint', 'docker', transport.clientImageId, ...buildArgs(sha)],
          cache, context, preservedBuilderContainers, note: 'Private builder image verified in isolated DinD. Disposable client containers were run; no application containers were started. Host runtime transfer is required and has not occurred.' };
        return evidence;
      } finally {
        if (safeToReleaseLock) await release();
      }
    },
  };
}
