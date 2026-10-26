import { randomUUID } from 'node:crypto';

export const PROVIDER = 'openai-codex';
export const MODEL = 'gpt-6-luna';
export const THINKING = 'xhigh';
export const TARGET = 'bfe2a6ad9331af0fbc5c7f7a26411079c8608cc1';

export function validateTarget(sha) {
  if (sha !== TARGET) throw new Error(`Only the accepted main@${TARGET} build is authorized`);
  return sha;
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
    const job = { id, sha, status: 'running', controller, startedAt: new Date().toISOString() };
    this.jobs.set(id, job);
    job.done = Promise.resolve().then(() => this.run(sha, controller.signal)).then(result => {
      job.result = result;
      job.usage = result?.usage;
      job.status = controller.signal.aborted ? 'cancelled' : 'succeeded';
    }, error => {
      // Only our fixed blocker messages are safe to relay, never raw provider errors.
      job.usage = error?.usage;
      job.status = controller.signal.aborted ? 'cancelled' :
        error?.code === 'NEWSHUB_BLOCKED' ? 'blocked' : 'failed';
      job.error = error?.code === 'NEWSHUB_BLOCKED' ? error.safeMessage :
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
    const { sha, status, startedAt, finishedAt, result, error } = this.get(id);
    return { id, sha, provider: PROVIDER, model: MODEL, thinking: THINKING,
      status, startedAt, finishedAt, result, error };
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
