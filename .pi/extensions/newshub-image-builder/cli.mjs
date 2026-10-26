#!/usr/bin/env node
import { execFile, spawn } from 'node:child_process';
import { promisify } from 'node:util';
import { access, stat } from 'node:fs/promises';
import { constants as fsConstants } from 'node:fs';
import { delimiter, isAbsolute, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { validateTarget, normalizeDiagnostics, sanitizeDiagnosticMessage } from './core.mjs';
import { validateCommit, nativePlatform, normalizePlatform } from './build.mjs';

const exec = promisify(execFile);
export const MODEL = 'openai-codex/gpt-6-luna';
export const THINKING = 'xhigh';
export const TOOL = 'newshub_image_builder';
export const MAX_STDOUT_BYTES = 4 * 1024 * 1024;
export const MAX_LINE_BYTES = 256 * 1024;
const ROOT = fileURLToPath(new URL('../../../', import.meta.url));
const EXTENSION = fileURLToPath(new URL('./index.ts', import.meta.url));
const HELP = `Usage: scripts/local-image-build --sha <lowercase-40-hex-commit> [--execute]

Default: validate the repository commit and print a no-side-effect preview.
--execute: run exactly one fixed Pi-native local-image-builder-luna task.
--help: show this help. No arbitrary prompt, model, thinking, or target options are accepted.
`;
const PROMPT = sha => `Fixed task: NewsHub local-image-builder-luna. Build only the exact commit ${sha} after this explicit invocation. Call ${TOOL} start exactly once with sha=${sha} and authorized=true, then wait on that returned job ID until it is terminal. Do not start another job, change the SHA, or claim success from assistant text; report only the tool's verified terminal result.`;

function cliError(code, message, exitCode = 5) {
  const error = new Error(message);
  error.cliCode = code;
  error.exitCode = exitCode;
  return error;
}

export function parseArguments(argv) {
  if (argv.length === 1 && argv[0] === '--help') return { help: true };
  let sha;
  let execute = false;
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === '--sha' && sha === undefined && argv[i + 1]) {
      sha = argv[++i];
    } else if (argv[i] === '--execute' && !execute) {
      execute = true;
    } else {
      throw cliError('INVALID_ARGUMENTS', 'Use --sha <commit> and optional --execute; no other options are supported.', 2);
    }
  }
  try { validateTarget(sha); }
  catch { throw cliError('INVALID_SHA', 'An exact lowercase 40-hex commit SHA is required.', 2); }
  return { sha, execute };
}

export function buildPiArgs(sha) {
  validateTarget(sha);
  return [
    '--model', MODEL, '--thinking', THINKING,
    '--no-extensions', '--extension', EXTENSION,
    '--tools', TOOL,
    '--no-mcp', '--no-skills', '--no-prompt-templates', '--no-context-files',
    '--no-approve', '--no-session', '--name', 'newshub-local-image-builder-luna', '--mode', 'json',
    PROMPT(sha),
  ];
}

async function ensureExecutable(path) {
  if (!isAbsolute(path)) throw cliError('PI_PATH_INVALID', 'NEWSHUB_PI_BIN must be an absolute executable path.', 3);
  try {
    const info = await stat(path);
    await access(path, fsConstants.X_OK);
    if (!info.isFile()) throw new Error('not a file');
  } catch {
    throw cliError('PI_NOT_FOUND', 'The configured Pi executable is unavailable or not executable.', 3);
  }
  return path;
}

export async function resolvePiExecutable(env = process.env) {
  if (env.NEWSHUB_PI_BIN) return ensureExecutable(env.NEWSHUB_PI_BIN);
  try {
    const { stdout } = await exec('mise', ['which', 'pi'], {
      cwd: ROOT, env: { PATH: env.PATH, HOME: env.HOME, MISE_NO_WRITE: '1' },
      timeout: 5_000, maxBuffer: 16 * 1024,
    });
    return await ensureExecutable(stdout.trim());
  } catch { /* A regular installed PATH executable is also supported. */ }
  for (const directory of String(env.PATH ?? '').split(delimiter).filter(Boolean)) {
    const candidate = resolve(directory, 'pi');
    try { return await ensureExecutable(candidate); }
    catch { /* Continue through PATH without invoking a shell or installer. */ }
  }
  throw cliError('PI_NOT_FOUND', 'Pi was not found via read-only `mise which pi` or PATH; set NEWSHUB_PI_BIN to an absolute installed Pi executable.', 3);
}

function receiptFromContent(content) {
  if (!Array.isArray(content)) return null;
  for (const item of content) {
    if (item?.type !== 'text' || typeof item.text !== 'string') continue;
    try {
      const parsed = JSON.parse(item.text);
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) return parsed;
    } catch { /* Try another text block; malformed-only content is rejected by the caller. */ }
  }
  return null;
}

export function receiptFromEventResult(event) {
  const candidates = [event?.result?.details, event?.toolResult?.details,
    receiptFromContent(event?.result?.content), receiptFromContent(event?.toolResult?.content)];
  return candidates.find(value => value && typeof value === 'object' && !Array.isArray(value)) ?? null;
}

function imageEvidence(receipt, sha) {
  const result = receipt?.result;
  const id = result?.builderImage?.id;
  if (receipt?.status !== 'succeeded' || result?.revision !== sha ||
      result?.builderImage?.revision !== sha || !/^sha256:[0-9a-f]{64}$/.test(id ?? '') ||
      result?.builderImage?.user !== 'root' || receipt?.diagnostics?.imageEvidence?.verified !== true) {
    throw cliError('UNVERIFIED_IMAGE', 'The terminal job did not contain verified image evidence.', 6);
  }
  let actualPlatform;
  try { actualPlatform = normalizePlatform(result.builderImage.platform); }
  catch { actualPlatform = null; }
  if (actualPlatform !== nativePlatform()) {
    throw cliError('UNVERIFIED_IMAGE', 'The terminal image platform did not match this native host.', 6);
  }
  const host = result.hostRuntime?.status === 'ready' && result.hostRuntime?.ready === true &&
    result.hostRuntime.imageId === id && result.builderImage.location === 'host-daemon';
  const privateImage = result.hostRuntime?.status === 'transfer-required' && result.hostRuntime?.ready === false &&
    result.hostRuntime.imageId === null && result.builderImage.location === 'isolated-ci-dind';
  const reused = result.reused === true && result.buildPerformed === false && result.buildExitCode === null;
  const built = result.reused === false && result.buildPerformed === true && result.buildExitCode === 0;
  if (!(host || privateImage) || !(reused || built)) {
    throw cliError('UNVERIFIED_IMAGE', 'The terminal job metadata is inconsistent with a verified reuse or build.', 6);
  }
  return { revision: sha, imageId: id, location: result.builderImage.location,
    platform: result.builderImage.platform, user: result.builderImage.user,
    hostRuntime: result.hostRuntime, reused: result.reused,
    buildPerformed: result.buildPerformed, buildExitCode: result.buildExitCode };
}

function failedJobDetails(receipt) {
  const diagnostics = normalizeDiagnostics(receipt?.diagnostics ?? {});
  const safeError = diagnostics.buildErrorMessage || diagnostics.preparationErrorMessage ||
    diagnostics.childErrorMessage || `Image-builder job ended with status ${receipt?.status ?? 'unknown'}.`;
  return { id: receipt.id, sha: receipt.sha, status: receipt.status,
    provider: receipt.provider, model: receipt.model, thinking: receipt.thinking,
    error: sanitizeDiagnosticMessage(safeError), diagnostics };
}

export function createTranscriptVerifier(sha) {
  validateTarget(sha);
  const calls = new Map();
  let jobId;
  let terminal;
  let settled = false;
  let settledNormally = false;
  let sessionSeen = false;
  let eventCount = 0;
  let assistantStopped = false;
  let aborted = false;
  let started = false;
  let protocolError;

  const fail = (code, message, exitCode = 5, safeJob = null) => {
    if (protocolError) return;
    protocolError = cliError(code, message, exitCode);
    if (safeJob) protocolError.safeJob = safeJob;
  };
  const verifyIdentity = message => {
    if (message?.provider !== 'openai-codex' || message?.model !== 'gpt-6-luna' || message?.thinkingLevel !== THINKING) {
      fail('MODEL_IDENTITY_MISMATCH', 'Pi did not report the required Luna model and xhigh reasoning identity.');
    }
    if (message?.stopReason === 'error' || message?.stopReason === 'aborted' || message?.stopReason === 'length') {
      fail('ASSISTANT_FAILED', 'The Pi assistant did not complete normally.', 6);
    }
    if (message?.stopReason === 'stop') assistantStopped = true;
  };
  const recordReceipt = (event, toolResult = null) => {
    const callId = event?.toolCallId;
    const toolName = event?.toolName;
    const call = calls.get(callId);
    if (toolName !== TOOL || !call || call.toolName !== TOOL) {
      fail('TOOL_RECEIPT_MISMATCH', 'The Pi stream contained an uncorrelated image-builder tool result.');
      return;
    }
    if (event?.isError === true || toolResult?.isError === true) {
      fail('TOOL_EXECUTION_FAILED', 'The image-builder tool reported an execution failure.', 6);
      return;
    }
    const receipt = receiptFromEventResult({ result: event?.result ?? toolResult,
      toolResult: event?.toolResult ?? toolResult });
    if (!receipt) {
      fail('TOOL_RECEIPT_MISSING', 'The image-builder tool result had no parseable structured receipt.');
      return;
    }
    if (receipt.sha !== sha || receipt.provider !== 'openai-codex' || receipt.model !== 'gpt-6-luna' ||
        receipt.thinking !== THINKING || typeof receipt.id !== 'string' || !receipt.id) {
      fail('TOOL_IDENTITY_MISMATCH', 'The tool receipt SHA, job, model, or reasoning identity did not match.');
      return;
    }
    if (call.action === 'start') {
      if (jobId && jobId !== receipt.id) fail('JOB_ID_MISMATCH', 'The started job ID changed.');
      jobId = receipt.id;
      if (receipt.status !== 'running' && receipt.status !== 'succeeded') {
        fail('JOB_FAILED', 'The image-builder job did not start successfully.', 6, failedJobDetails(receipt));
      }
      if (receipt.status === 'succeeded') terminal = imageEvidence(receipt, sha);
    } else {
      if (receipt.id !== jobId) fail('JOB_ID_MISMATCH', 'The wait receipt did not match the started job.');
      if (receipt.status === 'succeeded') terminal = imageEvidence(receipt, sha);
      else if (receipt.status !== 'running') fail('JOB_FAILED', 'The image-builder job ended without success.', 6, failedJobDetails(receipt));
    }
  };

  return {
    feed(event) {
      if (!event || typeof event !== 'object' || Array.isArray(event) || typeof event.type !== 'string') {
        fail('JSON_EVENT_INVALID', 'Pi emitted an invalid JSONL event.');
        return;
      }
      if (eventCount++ === 0 && event.type !== 'session') {
        fail('JSON_EVENT_INVALID', 'Pi JSONL was missing its session header.');
      }
      if (event.type === 'session') sessionSeen = true;
      if (event.type === 'message_end' && event.message?.role === 'assistant') verifyIdentity(event.message);
      if (event.type === 'agent_settled') {
        settled = true;
        settledNormally = event.aborted === false;
        aborted = event.aborted === true;
      }
      if (event.type === 'tool_execution_start') {
        if (event.toolName !== TOOL || typeof event.toolCallId !== 'string') {
          fail('UNAUTHORIZED_TOOL', 'Pi attempted a tool outside the fixed image-builder task.');
          return;
        }
        const args = event.args;
        if (args?.action === 'start') {
          if (started || args.sha !== sha || args.authorized !== true) {
            fail('UNAUTHORIZED_START', 'Pi did not issue exactly one authorized start for the requested SHA.');
            return;
          }
          started = true;
          calls.set(event.toolCallId, { toolName: TOOL, action: 'start' });
        } else if (args?.action === 'wait') {
          if (!started || !jobId || args.jobId !== jobId) {
            fail('JOB_ID_MISMATCH', 'Pi waited on a job other than the one it started.');
            return;
          }
          calls.set(event.toolCallId, { toolName: TOOL, action: 'wait' });
        } else {
          fail('UNAUTHORIZED_ACTION', 'Pi used an action outside the fixed start-and-wait task.');
        }
      }
      if (event.type === 'tool_execution_end' && event.toolName === TOOL) recordReceipt(event);
      if (event.type === 'turn_end' && Array.isArray(event.toolResults)) {
        for (const result of event.toolResults) {
          if (result?.toolName === TOOL) recordReceipt({
            toolCallId: result.toolCallId, toolName: result.toolName, result,
            isError: result.isError,
          }, result);
        }
      }
    },
    finish({ exitCode, signal, signalled, pending }) {
      if (protocolError) throw protocolError;
      if (signalled || signal) throw cliError('CANCELLED', 'The native Pi child was cancelled; no build success is reported.', 130);
      if (exitCode !== 0) throw cliError('PI_EXIT_NONZERO', 'The native Pi process exited unsuccessfully.', 4);
      if (pending) throw cliError('JSONL_INCOMPLETE', 'Pi ended with an incomplete JSONL record.');
      if (!sessionSeen || !settled || !settledNormally || aborted) throw cliError('AGENT_NOT_SETTLED', 'Pi did not settle normally; no terminal job success was received.', 5);
      if (!assistantStopped) throw cliError('ASSISTANT_NOT_NORMAL', 'Pi did not emit a normal assistant completion.', 6);
      if (!started || !jobId) throw cliError('TOOL_RECEIPT_MISSING', 'Pi settled without an image-builder start receipt.', 5);
      if (!terminal) throw cliError('TERMINAL_RECEIPT_MISSING', 'Pi settled without a verified terminal image-builder receipt.', 5);
      return { jobId, image: terminal };
    },
    failure: () => protocolError,
  };
}

export function runPiJson(executable, args, { sha, spawnImpl = spawn, cwd = ROOT, env = process.env } = {}) {
  return new Promise((resolvePromise, rejectPromise) => {
    let child;
    try {
      const childEnv = { ...env };
      if (sha) childEnv.NEWSHUB_LOCAL_IMAGE_BUILD_SHA = validateTarget(sha);
      child = spawnImpl(executable, args, { cwd, env: childEnv, stdio: ['ignore', 'pipe', 'pipe'] });
    } catch {
      rejectPromise(cliError('PI_SPAWN_FAILED', 'The installed Pi executable could not be started.', 3));
      return;
    }
    const requestedSha = sha ?? args.at(-1).match(/[0-9a-f]{40}/)?.[0];
    const verifier = createTranscriptVerifier(requestedSha);
    let totalBytes = 0;
    let pending = '';
    let stderrBytes = 0;
    let parserError;
    let spawnError = false;
    let receivedSignal = false;
    let childStopSent = false;
    let killTimer;
    const onSignal = signal => {
      receivedSignal = true;
      child.kill(signal);
      clearTimeout(killTimer);
      killTimer = setTimeout(() => { if (child.exitCode === null) child.kill('SIGKILL'); }, 1500);
      killTimer.unref?.();
    };
    const onSigint = () => onSignal('SIGINT');
    const onSigterm = () => onSignal('SIGTERM');
    process.once('SIGINT', onSigint);
    process.once('SIGTERM', onSigterm);
    const stopChild = () => {
      if (childStopSent || child.exitCode !== null) return;
      childStopSent = true;
      child.kill('SIGTERM');
      clearTimeout(killTimer);
      killTimer = setTimeout(() => { if (child.exitCode === null) child.kill('SIGKILL'); }, 1500);
      killTimer.unref?.();
    };
    child.once('error', () => { spawnError = true; });
    child.stdout.setEncoding('utf8');
    child.stdout.on('data', chunk => {
      totalBytes += Buffer.byteLength(chunk);
      if (totalBytes > MAX_STDOUT_BYTES) {
        parserError ??= cliError('OUTPUT_LIMIT', 'Pi JSONL output exceeded the fixed size limit.');
        stopChild();
        return;
      }
      pending += chunk;
      if (Buffer.byteLength(pending) > MAX_LINE_BYTES && !pending.includes('\n')) {
        parserError ??= cliError('LINE_LIMIT', 'Pi emitted an oversized JSONL event.');
        stopChild();
        return;
      }
      let newline;
      while ((newline = pending.indexOf('\n')) >= 0) {
        let line = pending.slice(0, newline);
        pending = pending.slice(newline + 1);
        if (line.endsWith('\r')) line = line.slice(0, -1);
        if (!line || Buffer.byteLength(line) > MAX_LINE_BYTES) {
          parserError ??= cliError('JSON_EVENT_INVALID', 'Pi emitted an empty or oversized JSONL event.');
          stopChild();
          return;
        }
        try { verifier.feed(JSON.parse(line)); }
        catch (error) {
          parserError ??= error?.cliCode ? error : cliError('JSON_EVENT_INVALID', 'Pi emitted malformed JSONL.');
          stopChild();
          return;
        }
        if (verifier.failure()) {
          parserError ??= verifier.failure();
          stopChild();
          return;
        }
      }
    });
    child.stderr.on('data', chunk => { stderrBytes = Math.min(64 * 1024, stderrBytes + Buffer.byteLength(chunk)); });
    child.once('close', (exitCode, signal) => {
      clearTimeout(killTimer);
      process.removeListener('SIGINT', onSigint);
      process.removeListener('SIGTERM', onSigterm);
      if (spawnError) {
        rejectPromise(cliError('PI_SPAWN_FAILED', 'The installed Pi executable could not be started.', 3));
        return;
      }
      if (parserError) { rejectPromise(parserError); return; }
      try {
        resolvePromise({ ...verifier.finish({ exitCode, signal, signalled: receivedSignal,
          pending: Boolean(pending) }), exitCode, stderrBytes });
      } catch (error) { rejectPromise(error); }
    });
  });
}

async function checkCommit(sha) {
  const env = { PATH: process.env.PATH, HOME: '/nonexistent', GIT_CONFIG_NOSYSTEM: '1',
    GIT_CONFIG_GLOBAL: '/dev/null', GIT_TERMINAL_PROMPT: '0' };
  try {
    await validateCommit(ROOT, sha, (bin, args, cwd) => exec(bin, args, {
      cwd, env, timeout: 10_000, maxBuffer: 16 * 1024,
    }));
  } catch {
    throw cliError('INVALID_SOURCE', 'The SHA is not a commit object available in this repository.', 2);
  }
}

export async function main(argv = process.argv.slice(2), io = {}) {
  const stdout = io.stdout ?? process.stdout;
  const stderr = io.stderr ?? process.stderr;
  try {
    const parsed = parseArguments(argv);
    if (parsed.help) { stdout.write(HELP); return 0; }
    await checkCommit(parsed.sha);
    const args = buildPiArgs(parsed.sha);
    if (!parsed.execute) {
      stdout.write(JSON.stringify({ ok: true, mode: 'preview', sha: parsed.sha,
        source: 'verified-commit-object', model: MODEL, thinking: THINKING,
        extension: EXTENSION, tools: [TOOL], executeFlag: '--execute',
        piExecutable: process.env.NEWSHUB_PI_BIN ? 'NEWSHUB_PI_BIN' : 'read-only mise which pi' }) + '\n');
      return 0;
    }
    const executable = await resolvePiExecutable();
    const outcome = await runPiJson(executable, args, { sha: parsed.sha });
    stdout.write(JSON.stringify({ ok: true, mode: 'execute', sha: parsed.sha,
      jobId: outcome.jobId, provider: 'openai-codex', model: 'gpt-6-luna', thinking: THINKING,
      status: 'succeeded', image: outcome.image }) + '\n');
    return 0;
  } catch (error) {
    const code = error?.cliCode ?? 'LOCAL_IMAGE_BUILD_FAILED';
    const message = error?.cliCode ? error.message : 'Local image build failed; no successful terminal evidence was verified.';
    const output = { ok: false, error: { code, message } };
    if (error?.safeJob) output.job = error.safeJob;
    stderr.write(JSON.stringify(output) + '\n');
    return Number.isInteger(error?.exitCode) ? error.exitCode : 1;
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  process.exitCode = await main();
}
