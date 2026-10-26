import { randomUUID } from 'node:crypto';

export const PROVIDER = 'openai-codex';
export const MODEL = 'gpt-6-luna';
export const THINKING = 'xhigh';
export const TARGET = 'bfe2a6ad9331af0fbc5c7f7a26411079c8608cc1';

export function validateTarget(sha) {
  if (sha !== TARGET) throw new Error(`Only the accepted main@${TARGET} build is authorized`);
  return sha;
}

const STOP_REASONS = new Set(['stop', 'toolUse', 'length', 'error', 'aborted']);
const PREPARATION_STAGES = new Set(['model-registry', 'build-adapter', 'rules', 'agent-construction']);
const SAFE_CHILD_ERRORS = new Set([
  'Inference aborted', 'Inference timed out', 'Connection closed before response completed',
  'Provider authentication rejected (HTTP 401)', 'Provider authorization rejected (HTTP 403)',
  'Provider rate limited (HTTP 429)', 'Provider rejected request parameters (HTTP 400)',
  'Provider rejected request parameters (HTTP 422)', 'Provider rejected an unsupported request parameter',
  'Requested model was not found', 'Provider resource was not found (HTTP 404)',
  'Provider connection was refused', 'Provider connection was aborted', 'Provider network was unreachable',
  'Provider name lookup temporarily failed', 'Provider host was not found',
  'Provider inference failed (details redacted)',
  'Child inference failed (details redacted)', 'Agent returned no assistant completion',
  'build_image tool execution failed (details redacted)',
]);
const SAFE_ERROR_CODES = new Set([
  'NEWSHUB_BLOCKED', 'NEWSHUB_BUILD_FAILURE', 'NEWSHUB_CHILD_FAILURE', 'NEWSHUB_PREPARATION_FAILURE',
  'DOCKER_BUILD_FAILED', 'PROXY_EOF', 'PROVIDER_ERROR', 'MODEL_NOT_FOUND', 'UNSUPPORTED_PARAMETER',
  'HTTP_400', 'HTTP_401', 'HTTP_403', 'HTTP_404', 'HTTP_422', 'HTTP_429',
  'ETIMEDOUT', 'ECONNRESET', 'ECONNREFUSED', 'ECONNABORTED', 'EHOSTUNREACH', 'ENETUNREACH',
  'EAI_AGAIN', 'ENOTFOUND', 'EPIPE', 'ENOENT', 'EACCES', 'EISDIR', 'ABORT_ERR', 'SIGTERM', 'SIGKILL',
  'ERR_CHILD_PROCESS_STDIO_MAXBUFFER', 'ERR_INVALID_ARG_TYPE', 'ERR_MODULE_NOT_FOUND',
  'ERR_PACKAGE_PATH_NOT_EXPORTED', 'ERR_UNKNOWN_FILE_EXTENSION', 'ERR_INVALID_URL',
]);

export function safeDiagnosticCode(value) {
  return typeof value === 'string' && SAFE_ERROR_CODES.has(value) ? value : null;
}

export function safeExitCode(value) {
  return Number.isInteger(value) && value >= 0 && value <= 255 ? value : null;
}

export function sanitizeDiagnosticMessage(value) {
  if (typeof value !== 'string') return null;
  return value.replace(/[\x00-\x1f\x7f]/g, ' ').replace(/\s+/g, ' ').trim()
    .replace(/\b(?:system\s+)?prompt\b\s*[:=]\s*(?:"(?:\\.|[^"\\])*"?|\'(?:\\.|[^'\\])*\'?|[^;,]{0,240})/gi, '[redacted prompt]')
    .replace(/(["']?(?:authorization|api[_-]?key|access[_-]?token|refresh[_-]?token|password|secret)["']?)\s*:\s*(?:"(?:\\.|[^"\\])*"?|\'(?:\\.|[^'\\])*\'?|[^,}\s]+)/gi, '$1:[redacted]')
    .replace(/\b(authorization|api[_-]?key|access[_-]?token|refresh[_-]?token|password|secret)\b\s*=\s*(?:"(?:\\.|[^"\\])*"?|\'(?:\\.|[^'\\])*\'?|[^\s,;]+)/gi, '$1=[redacted]')
    .replace(/\b(?:Bearer|Basic)\s+[^\s,;"']+/gi, '[redacted credential]')
    .replace(/https?:\/\/[^\s"'<>]+/gi, '[redacted URL]')
    .replace(/\b(?:sk-[A-Za-z0-9_-]{8,}|gh[pousr]_[A-Za-z0-9_]{8,})\b/g, '[redacted token]')
    .slice(0, 240);
}

export function normalizeDiagnostics(input = {}) {
  const rawStop = input?.childStopReason;
  const rawChildError = input?.childErrorMessage;
  const rawPreparationStage = input?.preparationStage;
  return {
    buildCalled: input?.buildCalled === true,
    buildErrorCode: safeDiagnosticCode(input?.buildErrorCode),
    buildExitCode: safeExitCode(input?.buildExitCode),
    buildErrorMessage: sanitizeDiagnosticMessage(input?.buildErrorMessage),
    preparationStage: typeof rawPreparationStage === 'string' && PREPARATION_STAGES.has(rawPreparationStage) ? rawPreparationStage : null,
    preparationErrorCode: safeDiagnosticCode(input?.preparationErrorCode),
    preparationExitCode: safeExitCode(input?.preparationExitCode),
    preparationErrorMessage: input?.preparationErrorMessage === 'Worker preparation failed (details redacted)' ?
      input.preparationErrorMessage : null,
    childStopReason: typeof rawStop === 'string' && STOP_REASONS.has(rawStop) ? rawStop : null,
    childErrorCode: safeDiagnosticCode(input?.childErrorCode),
    childExitCode: safeExitCode(input?.childExitCode),
    childErrorMessage: SAFE_CHILD_ERRORS.has(rawChildError) ? rawChildError :
      (typeof rawChildError === 'string' && rawChildError ? 'Child inference failed (details redacted)' : null),
    cancelled: input?.cancelled === true,
    timedOut: input?.timedOut === true,
    imageEvidence: { verified: input?.imageEvidence?.verified === true },
  };
}

function verifiedBuildResult(result, sha) {
  return result?.revision === sha && result?.builderImage?.revision === sha &&
    /^sha256:[0-9a-f]{64}$/.test(result?.builderImage?.id ?? '') &&
    result?.hostRuntime?.status === 'transfer-required' && result?.hostRuntime?.ready === false &&
    result?.diagnostics?.imageEvidence?.verified === true;
}

// The agent has its own transcript, model and tools. No parent messages or tools
// are inherited. State is session-scoped; an external lock fences other sessions.
export class BuildJobs {
  constructor(run) {
    this.run = run;
    this.jobs = new Map();
    this.closing = false;
  }

  start(sha, authorized) {
    validateTarget(sha);
    if (authorized !== true) throw new Error('Explicit build-only authorization is required');
    if (this.closing) throw new Error('Extension is shutting down');
    if ([...this.jobs.values()].some(j => j.status === 'running')) {
      throw new Error('A build agent is already running; query/wait for it');
    }
    if (this.jobs.size >= 20) throw new Error('Session job limit reached');
    const id = randomUUID();
    const controller = new AbortController();
    const job = { id, sha, status: 'running', controller, diagnostics: normalizeDiagnostics(),
      startedAt: new Date().toISOString() };
    this.jobs.set(id, job);
    const publishDiagnostics = value => { job.diagnostics = normalizeDiagnostics(value); };
    job.done = Promise.resolve().then(() => this.run(sha, controller.signal, publishDiagnostics)).then(result => {
      job.diagnostics = normalizeDiagnostics(result?.diagnostics ?? job.diagnostics);
      if (!verifiedBuildResult(result, sha) || !job.diagnostics.imageEvidence.verified) {
        const error = new Error('Worker returned no verified image evidence');
        error.code = 'NEWSHUB_BLOCKED';
        error.safeMessage = 'Worker returned no verified image evidence';
        error.diagnostics = { ...job.diagnostics, imageEvidence: { verified: false } };
        throw error;
      }
      if (controller.signal.aborted) {
        const error = new Error('Build job was cancelled before completion');
        error.code = 'NEWSHUB_CHILD_FAILURE';
        error.safeMessage = 'Build job was cancelled before completion';
        error.diagnostics = { ...job.diagnostics, cancelled: true, imageEvidence: { verified: false } };
        throw error;
      }
      job.result = result;
      job.usage = result?.usage;
      job.diagnostics = normalizeDiagnostics({ ...job.diagnostics, imageEvidence: { verified: true } });
      job.status = controller.signal.aborted ? 'cancelled' : 'succeeded';
    }).catch(error => {
      job.usage = error?.usage;
      job.diagnostics = normalizeDiagnostics(error?.diagnostics ?? job.diagnostics);
      if (controller.signal.aborted) job.diagnostics = normalizeDiagnostics({ ...job.diagnostics, cancelled: true });
      job.status = controller.signal.aborted ? 'cancelled' :
        error?.code === 'NEWSHUB_BLOCKED' ? 'blocked' : 'failed';
      job.error = error?.code === 'NEWSHUB_BLOCKED' || error?.code === 'NEWSHUB_BUILD_FAILURE' ||
        error?.code === 'NEWSHUB_CHILD_FAILURE' || error?.code === 'NEWSHUB_PREPARATION_FAILURE' ? sanitizeDiagnosticMessage(error.safeMessage) :
        'Agent/build failed; no successful image verification was obtained';
    }).finally(() => { job.finishedAt = new Date().toISOString(); });
    return this.status(id);
  }

  get(id) {
    const job = this.jobs.get(id);
    if (!job) throw new Error('Unknown job ID in this Pi session');
    return job;
  }

  status(id) {
    if (!id) return [...this.jobs.keys()].map(key => this.status(key));
    const { sha, status, startedAt, finishedAt, result, error, diagnostics } = this.get(id);
    return { id, sha, provider: PROVIDER, model: MODEL, thinking: THINKING,
      status, startedAt, finishedAt, result, error, diagnostics: normalizeDiagnostics(diagnostics) };
  }

  async wait(id, seconds = 30, signal) {
    if (!Number.isInteger(seconds) || seconds < 1 || seconds > 60) {
      throw new Error('waitSeconds must be an integer from 1 to 60');
    }
    const job = this.get(id);
    if (signal?.aborted) throw new Error('Wait cancelled; the build job is unchanged');
    let timer;
    let listener;
    try {
      await Promise.race([
        job.done,
        new Promise(resolve => { timer = setTimeout(resolve, seconds * 1000); }),
        new Promise((_, reject) => {
          listener = () => reject(new Error('Wait cancelled; the build job is unchanged'));
          signal?.addEventListener('abort', listener, { once: true });
        }),
      ]);
      return this.status(id);
    } finally {
      clearTimeout(timer);
      if (listener) signal?.removeEventListener('abort', listener);
    }
  }

  async close() {
    this.closing = true;
    const jobs = [...this.jobs.values()];
    for (const job of jobs) if (job.status === 'running') job.controller.abort();
    await Promise.all(jobs.map(job => job.done));
  }
}
