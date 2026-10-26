import type { ExtensionAPI } from '@earendil-works/pi-coding-agent';
import { Agent } from '@earendil-works/pi-agent-core';
import { clampThinkingLevel } from '@earendil-works/pi-ai';
import { Type } from 'typebox';
import { realpath } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { BuildJobs, PROVIDER, MODEL, THINKING, validateTarget } from './core.mjs';
import { createBuild, blocked } from './build.mjs';
import { createImageBuildWorker } from './worker.mjs';

export default function (pi: ExtensionAPI) {
  const root = fileURLToPath(new URL('../../../', import.meta.url));
  let registry;
  const worker = createImageBuildWorker({
    AgentClass: Agent,
    clampThinkingLevel,
    toolParameters: Type.Object({}, { additionalProperties: false }),
    getRegistry: () => registry,
    createBuild,
    root,
  });
  const jobs = new BuildJobs(worker);

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
