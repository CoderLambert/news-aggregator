import { execFileSync } from 'node:child_process';
import { EventEmitter } from 'node:events';
import { PassThrough } from 'node:stream';
import assert from 'node:assert/strict';
import { CLIENT_IMAGE, CI_NETWORK, SOCKET_VOLUME } from '../build.mjs';

const TAB = String.fromCharCode(9);
const LF = String.fromCharCode(10);
export const DIND_ID = `sha256:${'b'.repeat(64)}`;

export function imageOutput({ revision, architecture = 'amd64', os = 'linux', user = 'root',
  cmd = ['/app/docker-entrypoint.sh'], env = ['HOME=/root', 'HF_HOME=/root/.cache/huggingface'],
  id = `sha256:${'d'.repeat(64)}` } = {}) {
  return [JSON.stringify(id), JSON.stringify([]), JSON.stringify(os), JSON.stringify(architecture),
    JSON.stringify(user), JSON.stringify(cmd), JSON.stringify(revision), env.join(LF)].join(TAB) + LF;
}

export function dockerHarness(repo, { privateImage = 'verified', activeWorker = false } = {}) {
  const calls = [];
  const gitCalls = [];
  let built = false;
  const tag = `newshub:dev-${repo.featureSha}`;
  const absent = message => Object.assign(new Error(message), { code: 1, stderr: message });
  const runCommand = async (bin, args, cwd) => {
    if (bin === 'git') {
      gitCalls.push(args);
      return { stdout: execFileSync(bin, args, { cwd, encoding: 'utf8',
        env: { ...process.env, GIT_CONFIG_GLOBAL: '/dev/null' } }) };
    }
    if (bin === 'ps') return { stdout: '' };
    assert.equal(bin, 'docker', `unexpected executable ${bin}`);
    calls.push(args);
    if (args[0] === 'image' && args[1] === 'inspect' && args.at(-1) === tag) {
      throw absent(`Error: No such image: ${tag}`);
    }
    if (args[0] === 'inspect') {
      const name = args.at(-1);
      const serviceName = name === 'newshub-ci-docker-1' ? 'docker' :
        name === 'newshub-ci-runner-1' ? 'runner' : 'runner-frontend';
      const mounts = serviceName === 'runner-frontend' ? '' : `volume|${SOCKET_VOLUME}|/ci-docker,`;
      const values = [JSON.stringify(`/${name}`), JSON.stringify(DIND_ID), JSON.stringify('newshub-ci'),
        JSON.stringify(serviceName), JSON.stringify('running'), JSON.stringify(true), JSON.stringify('healthy'),
        mounts, `${CI_NETWORK},`];
      return { stdout: values.join(TAB) };
    }
    if (args[0] === 'network' && args[1] === 'inspect') {
      return { stdout: [CI_NETWORK, 'bridge', 'newshub-ci',
        ['newshub-ci-docker-1', 'newshub-ci-runner-1', 'newshub-ci-runner-frontend-1'].join(',')].join(TAB) };
    }
    if (args[0] === 'volume' && args[1] === 'inspect') {
      return { stdout: [SOCKET_VOLUME, 'newshub-ci', 'runner-socket'].join(TAB) };
    }
    if (args[0] === 'image' && args[1] === 'inspect' && args.at(-1) === CLIENT_IMAGE) {
      return { stdout: [JSON.stringify(DIND_ID), JSON.stringify([]), JSON.stringify('linux'),
        JSON.stringify('amd64')].join(TAB) };
    }
    if (args[0] === 'container' && args[1] === 'inspect') {
      if (args[2]?.includes('com.newshub.pi-image-builder.task')) {
        return { stdout: JSON.stringify(args.at(-1).replace('newshub-image-builder-', '')) };
      }
      throw absent(`No such object: ${args.at(-1)}`);
    }
    if (args[0] === 'container' && args[1] === 'rm') return { stdout: '' };
    if (args[0] === 'top') return { stdout: `PID COMMAND${LF}17 ${activeWorker ? 'Runner.Worker' : 'runner'}${LF}` };
    if (args[0] === 'run') {
      const entrypoint = args.indexOf('--entrypoint');
      const dockerArgs = args.slice(entrypoint + 3);
      if (dockerArgs[0] === 'image' && dockerArgs[1] === 'inspect' && dockerArgs.at(-1) === tag) {
        if (privateImage === 'missing' && !built) throw absent(`Error response from daemon: No such image: ${tag}`);
        if (privateImage === 'daemon') throw absent('Cannot connect to the Docker daemon');
        return { stdout: imageOutput({ revision: repo.featureSha,
          ...(privateImage === 'verified' ? {} : privateImage) }) };
      }
      if (dockerArgs[0] === 'ps') return { stdout: `redis-container${LF}` };
      if (dockerArgs[0] === 'image' && dockerArgs[1] === 'ls') return { stdout: '' };
    }
    throw new Error(`Unexpected synthetic Docker command: ${args.slice(0, 3).join(' ')}`);
  };
  const spawnCommand = (_bin, args) => {
    const child = new EventEmitter();
    child.stdout = new PassThrough();
    child.stderr = new PassThrough();
    const entrypoint = args.indexOf('--entrypoint');
    assert.equal(args[entrypoint + 3], 'build');
    built = true;
    setImmediate(() => {
      child.stdout.write(`#1 CACHED${LF}#2 DONE 1.0s${LF}`);
      child.stdout.end();
      child.stderr.end();
      child.emit('close', 0, null);
    });
    calls.push(args);
    return child;
  };
  return { calls, gitCalls, runCommand, spawnCommand };
}
