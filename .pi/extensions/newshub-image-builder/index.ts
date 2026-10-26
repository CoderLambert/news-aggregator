import type { ExtensionAPI } from '@earendil-works/pi-coding-agent';
import { Agent } from '@earendil-works/pi-agent-core';
import { clampThinkingLevel } from '@earendil-works/pi-ai';
import { Type } from 'typebox';
import { realpath } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { BuildJobs, PROVIDER, MODEL, THINKING, validateTarget } from './core.mjs';
import { createBuild, blocked } from './build.mjs';

export default function (pi: ExtensionAPI) {
  const root = fileURLToPath(new URL('../../../', import.meta.url));
  let registry;
  const jobs = new BuildJobs(async (sha, signal) => {
    const model = registry?.find(PROVIDER, MODEL);
    if (!model || model.provider !== PROVIDER || model.id !== MODEL ||
        clampThinkingLevel(model, THINKING) !== THINKING || !registry.hasConfiguredAuth(model)) {
      throw blocked('Exact openai-codex/gpt-6-luna with xhigh and configured Pi auth is required; no fallback');
    }
    const operation = new AbortController();
    const buildSignal = AbortSignal.any([signal, operation.signal]);
    const build = createBuild(root, buildSignal);
    const documents = await build.rules(sha);
    const agent = new Agent({
      initialState: {
        model, thinkingLevel: THINKING, messages: [],
        systemPrompt: 'You are the NewsHub local-image-builder-luna, a Pi-native build-only agent. ' +
          'Read the supplied rules and build exactly the authorized SHA using build_image once. ' +
          'No delegation, shell, source edits, credentials, business data, deployment, migrations, ' +
          'runtime probes, service changes, cache cleaning, Git/image pushes or CI. ' +
          'newshub-local-main and 127.0.0.1:19527 are protected and must remain untouched. ' +
          'The only tool exports safe immutable Git blobs to an isolated builder and verifies private-image metadata. ' +
          'The result hostRuntime.status=transfer-required means the image is not available on the host; never claim runtime readiness or perform a transfer. ' +
          'A blocked or failed tool is not success; never retry it.\n\n' + documents,
        tools: [{
          name: 'build_image', label: 'Build exact NewsHub image',
          description: 'One build-only attempt for the already-authorized SHA. No shell or arbitrary arguments.',
          parameters: Type.Object({}, { additionalProperties: false }),
          execute: async () => {
            const result = await build.build(sha);
            return { content: [{ type: 'text', text: JSON.stringify(result) }], details: result };
          },
        }],
      },
      toolExecution: 'sequential',
      streamFn: (selected, context, options) => {
        if (selected.provider !== PROVIDER || selected.id !== MODEL) throw blocked('Model identity changed');
        return registry.streamSimple(model, context, { ...options, reasoning: THINKING });
      },
    });
    const abort = () => { operation.abort(); agent.abort(); };
    signal.addEventListener('abort', abort, { once: true });
    // A hung provider or repeated model tool requests cannot retain the job forever.
    const deadline = setTimeout(abort, 30 * 60 * 1000);
    let turns = 0;
    const usage = { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0,
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } };
    const unsubscribe = agent.subscribe(event => {
      if (event.type === 'message_end' && event.message.role === 'assistant' && event.message.usage) {
        for (const key of ['input', 'output', 'cacheRead', 'cacheWrite', 'totalTokens']) usage[key] += event.message.usage[key] ?? 0;
        for (const key of Object.keys(usage.cost)) usage.cost[key] += event.message.usage.cost?.[key] ?? 0;
      }
      if (event.type === 'turn_end' && ++turns >= 4) abort();
    });
    try {
      if (signal.aborted) throw blocked('Job cancelled before inference');
      await agent.prompt(`Build only main@${validateTarget(sha)}. Report verified metadata; never deploy.`);
      const last = [...agent.state.messages].reverse().find(message => message.role === 'assistant');
      if (!build.evidence() || last?.stopReason !== 'stop' || agent.state.errorMessage) {
        throw blocked('Agent did not complete with verified image evidence');
      }
      return { ...build.evidence(), usage };
    } catch (error) {
      error.usage = usage;
      throw error;
    } finally {
      clearTimeout(deadline);
      signal.removeEventListener('abort', abort);
      unsubscribe();
      agent.abort();
      await agent.waitForIdle();
    }
  });

  pi.registerTool({
    name: 'newshub_image_builder', label: 'NewsHub Luna image builder',
    description: 'Pi-native isolated Luna xhigh build-only agent. start requires explicit user build authorization; ' +
      'status and wait never start a job. No OMP, deployments or restarts. IDs are scoped to this Pi session.',
    parameters: Type.Object({
      action: Type.Union([Type.Literal('start'), Type.Literal('status'), Type.Literal('wait')]),
      sha: Type.Optional(Type.String()),
      authorized: Type.Optional(Type.Boolean({ description: 'True only after explicit user authorization to build now' })),
      jobId: Type.Optional(Type.String()),
      waitSeconds: Type.Optional(Type.Integer({ minimum: 1, maximum: 60 })),
    }, { additionalProperties: false }),
    async execute(_id, params, signal, _onUpdate, ctx) {
      if (await realpath(ctx.cwd) !== await realpath(root)) throw blocked('Run this project extension from the repository root');
      registry = ctx.modelRegistry;
      let result;
      if (params.action === 'start') result = jobs.start(params.sha, params.authorized);
      else if (params.action === 'status') result = jobs.status(params.jobId);
      else {
        if (!params.jobId) throw new Error('wait requires jobId');
        result = await jobs.wait(params.jobId, params.waitSeconds, signal);
      }
      // Report nested usage once, on first terminal observation, not on every poll.
      let usage;
      if (params.jobId) {
        const job = jobs.get(params.jobId);
        if (job.status !== 'running' && !job.usageReported && job.usage) {
          usage = job.usage;
          job.usageReported = true;
        }
      }
      return { content: [{ type: 'text', text: JSON.stringify(result) }], details: result, usage };
    },
  });
  pi.on('session_shutdown', async () => { await jobs.close(); });
}
