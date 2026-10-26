import {
  MODEL, PROVIDER, THINKING, normalizeDiagnostics, safeDiagnosticCode, safeExitCode,
  sanitizeDiagnosticMessage, validateTarget,
} from './core.mjs';

function workerError(message, diagnostics, code = 'NEWSHUB_BLOCKED') {
  const error = new Error(message);
  error.code = code;
  error.safeMessage = message;
  error.diagnostics = normalizeDiagnostics(diagnostics);
  return error;
}

function safeBuildFailure(error) {
  const safeMessage = sanitizeDiagnosticMessage(error?.safeMessage);
  const dockerFailure = /^Docker build failed \(exit (\d{1,3})\); no retry performed$/.exec(safeMessage ?? '');
  const exitCode = safeExitCode(error?.exitCode) ?? safeExitCode(typeof error?.code === 'number' ? error.code : null) ??
    (dockerFailure ? safeExitCode(Number(dockerFailure[1])) : null);
  const errorCode = dockerFailure ? 'DOCKER_BUILD_FAILED' :
    safeDiagnosticCode(error?.code) ?? (exitCode === null ? null : 'DOCKER_BUILD_FAILED');
  const trustedMessage = error?.code === 'NEWSHUB_BLOCKED' || error?.code === 'NEWSHUB_BUILD_FAILURE' || dockerFailure;
  return {
    code: errorCode,
    exitCode,
    message: trustedMessage && safeMessage ? safeMessage : 'build_image failed (details redacted)',
  };
}

function classifyChildError(message, causeCode, stopReason) {
  const text = typeof message === 'string' ? message : '';
  const code = typeof causeCode === 'string' ? causeCode.toUpperCase() : '';
  const networkErrors = new Map([
    ['ETIMEDOUT', 'Inference timed out'], ['ECONNRESET', 'Connection closed before response completed'],
    ['ECONNREFUSED', 'Provider connection was refused'], ['ECONNABORTED', 'Provider connection was aborted'],
    ['EHOSTUNREACH', 'Provider network was unreachable'], ['ENETUNREACH', 'Provider network was unreachable'],
    ['EAI_AGAIN', 'Provider name lookup temporarily failed'], ['ENOTFOUND', 'Provider host was not found'],
    ['EPIPE', 'Connection closed before response completed'],
  ]);
  if (!text && !code && stopReason !== 'error') return null;
  const codedFailures = new Map([
    ['HTTP_401', 'Provider authentication rejected (HTTP 401)'],
    ['HTTP_403', 'Provider authorization rejected (HTTP 403)'],
    ['HTTP_429', 'Provider rate limited (HTTP 429)'],
    ['HTTP_400', 'Provider rejected request parameters (HTTP 400)'],
    ['HTTP_422', 'Provider rejected request parameters (HTTP 422)'],
    ['HTTP_404', 'Provider resource was not found (HTTP 404)'],
    ['UNSUPPORTED_PARAMETER', 'Provider rejected an unsupported request parameter'],
    ['MODEL_NOT_FOUND', 'Requested model was not found'],
    ['PROXY_EOF', 'Connection closed before response completed'],
  ]);
  if (codedFailures.has(code)) return { code, message: codedFailures.get(code) };
  if (/\b(?:abort(?:ed)?|cancel(?:led|ed))\b/i.test(text) || code === 'ABORT_ERR') {
    return { code: 'ABORT_ERR', message: 'Inference aborted' };
  }
  if (/\b(?:timeout|timed out|deadline)\b/i.test(text) || code === 'ETIMEDOUT') {
    return { code: 'ETIMEDOUT', message: 'Inference timed out' };
  }
  if (networkErrors.has(code)) return { code, message: networkErrors.get(code) };
  if (/build_image tool execution failed/i.test(text)) {
    return { code: 'NEWSHUB_BUILD_FAILURE', message: 'build_image tool execution failed (details redacted)' };
  }
  if (/\bunsupported (?:request )?parameter\b/i.test(text)) {
    return { code: 'UNSUPPORTED_PARAMETER', message: 'Provider rejected an unsupported request parameter' };
  }
  if (/\bmodel\b.{0,50}\b(?:not found|does not exist|unknown)\b|\b(?:not found|unknown)\b.{0,50}\bmodel\b/i.test(text)) {
    return { code: 'MODEL_NOT_FOUND', message: 'Requested model was not found' };
  }
  const status = /\b(?:HTTP(?:\s+status)?\s*[:=]?\s*|status(?:\s+code)?\s*[:=]?\s*)(400|401|403|404|422|429)\b/i.exec(text)?.[1] ??
    /\b(400|401|403|404|422|429)\s+(?:bad request|unauthorized|forbidden|not found|unprocessable|too many requests)\b/i.exec(text)?.[1];
  if (status === '401') return { code: 'HTTP_401', message: 'Provider authentication rejected (HTTP 401)' };
  if (status === '403') return { code: 'HTTP_403', message: 'Provider authorization rejected (HTTP 403)' };
  if (status === '429') return { code: 'HTTP_429', message: 'Provider rate limited (HTTP 429)' };
  if (status === '400') return { code: 'HTTP_400', message: 'Provider rejected request parameters (HTTP 400)' };
  if (status === '422') return { code: 'HTTP_422', message: 'Provider rejected request parameters (HTTP 422)' };
  if (status === '404') return { code: 'HTTP_404', message: 'Provider resource was not found (HTTP 404)' };
  if (/Connection closed by proxy server before the response completed|\b(?:EOF|socket hang up|connection closed)\b/i.test(text)) {
    return { code: 'PROXY_EOF', message: 'Connection closed before response completed' };
  }
  return { code: 'PROVIDER_ERROR', message: 'Provider inference failed (details redacted)' };
}

function blankDiagnostics() {
  return normalizeDiagnostics({ imageEvidence: { verified: false } });
}

export function createImageBuildWorker({
  AgentClass, clampThinkingLevel, toolParameters, getRegistry, createBuild,
  root, deadlineMs = 30 * 60 * 1000, maxTurns = 4,
}) {
  if (typeof AgentClass !== 'function' || typeof getRegistry !== 'function' ||
      typeof createBuild !== 'function' || typeof clampThinkingLevel !== 'function') {
    throw new TypeError('Image build worker dependencies are incomplete');
  }

  return async (sha, signal, publish = () => {}) => {
    validateTarget(sha);
    let diagnostics = blankDiagnostics();
    const usage = { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0,
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } };
    const fail = (message, current = diagnostics, code = 'NEWSHUB_BLOCKED') => {
      const error = workerError(message, current, code);
      error.usage = usage;
      return error;
    };
    const report = patch => {
      diagnostics = normalizeDiagnostics({ ...diagnostics, ...patch });
      publish(diagnostics);
    };
    const preparationFailure = (stage, error) => {
      const classified = classifyChildError(error?.message, error?.code);
      report({ preparationStage: stage,
        preparationErrorCode: safeDiagnosticCode(error?.code) ?? classified?.code ?? 'NEWSHUB_PREPARATION_FAILURE',
        preparationExitCode: safeExitCode(error?.exitCode) ?? safeExitCode(typeof error?.code === 'number' ? error.code : null),
        preparationErrorMessage: 'Worker preparation failed (details redacted)' });
      return fail('Image build worker preparation failed (details redacted)', diagnostics, 'NEWSHUB_PREPARATION_FAILURE');
    };

    let registry;
    let model;
    try {
      registry = getRegistry();
      model = registry?.find(PROVIDER, MODEL);
      if (model && (model.provider !== PROVIDER || model.id !== MODEL ||
          clampThinkingLevel(model, THINKING) !== THINKING || !registry.hasConfiguredAuth(model))) model = undefined;
    } catch (error) {
      throw preparationFailure('model-registry', error);
    }
    if (!model) {
      throw fail('Exact openai-codex/gpt-6-luna with xhigh and configured Pi auth is required; no fallback');
    }

    const operation = new AbortController();
    let buildSignal;
    let build;
    try {
      buildSignal = AbortSignal.any([signal, operation.signal]);
      build = createBuild(root, buildSignal);
    } catch (error) {
      throw preparationFailure('build-adapter', error);
    }
    let documents;
    try { documents = await build.rules(sha); }
    catch (error) { throw preparationFailure('rules', error); }
    let agent;
    const createAgent = () => new AgentClass({
      initialState: {
        model, thinkingLevel: THINKING, messages: [],
        systemPrompt: 'You are the NewsHub local-image-builder-luna, a Pi-native build-only agent. ' +
          'Use the repository development target for the accepted local root-user/data/cache contract; this is not a production release. ' +
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
          parameters: toolParameters,
          execute: async () => {
            if (diagnostics.buildCalled) {
              throw fail('build_image may be called only once', diagnostics);
            }
            report({ buildCalled: true });
            try {
              const result = await build.build(sha);
              const evidence = build.evidence();
              report({ imageEvidence: { verified: Boolean(evidence) } });
              return { content: [{ type: 'text', text: JSON.stringify(result) }], details: result };
            } catch (error) {
              const failure = safeBuildFailure(error);
              report({ buildErrorCode: failure.code, buildExitCode: failure.exitCode,
                buildErrorMessage: failure.message, imageEvidence: { verified: Boolean(build.evidence()) } });
              throw fail(failure.message, diagnostics, 'NEWSHUB_BUILD_FAILURE');
            }
          },
        }],
      },
      toolExecution: 'sequential',
      streamFn: (selected, context, options) => {
        if (selected.provider !== PROVIDER || selected.id !== MODEL) {
          throw fail('Model identity changed', diagnostics);
        }
        return registry.streamSimple(model, context, { ...options, reasoning: THINKING });
      },
    });
    try { agent = createAgent(); }
    catch (error) { throw preparationFailure('agent-construction', error); }

    let timedOut = false;
    let turnLimitReached = false;
    let toolExecutionFailed = false;
    let turns = 0;
    const abortForCaller = () => {
      report({ cancelled: true });
      operation.abort();
      agent.abort();
    };
    if (signal.aborted) abortForCaller();
    else signal.addEventListener('abort', abortForCaller, { once: true });
    const deadline = setTimeout(() => {
      timedOut = true;
      report({ timedOut: true });
      operation.abort();
      agent.abort();
    }, deadlineMs);
    const unsubscribe = agent.subscribe(event => {
      if (event.type === 'message_end' && event.message.role === 'assistant') {
        const failure = classifyChildError(event.message.errorMessage, null, event.message.stopReason);
        report({ childStopReason: event.message.stopReason ?? null,
          childErrorCode: failure?.code ?? null, childErrorMessage: failure?.message ?? null });
        if (event.message.usage) {
          for (const key of ['input', 'output', 'cacheRead', 'cacheWrite', 'totalTokens']) {
            usage[key] += event.message.usage[key] ?? 0;
          }
          for (const key of Object.keys(usage.cost)) usage.cost[key] += event.message.usage.cost?.[key] ?? 0;
        }
      }
      if (event.type === 'tool_execution_end' && event.toolName === 'build_image' && event.isError) {
        toolExecutionFailed = true;
        if (!diagnostics.buildErrorCode) {
          report({ buildErrorCode: 'NEWSHUB_BUILD_FAILURE',
            buildErrorMessage: 'build_image tool execution failed (details redacted)' });
        }
      }
      if (event.type === 'turn_end' && ++turns >= maxTurns && event.message.stopReason !== 'stop') {
        turnLimitReached = true;
        report({ cancelled: true });
        operation.abort();
        agent.abort();
      }
    });

    let promptError = null;
    try {
      if (signal.aborted) {
        report({ cancelled: true });
      } else {
        await agent.prompt(`Build only main@${validateTarget(sha)}. Report verified metadata; never deploy.`);
      }
    } catch (error) {
      promptError = error;
    }

    try {
      const last = [...(agent.state?.messages ?? [])].reverse().find(message => message.role === 'assistant');
      const childStopReason = last?.stopReason ?? diagnostics.childStopReason;
      const failure = classifyChildError(agent.state?.errorMessage ?? last?.errorMessage,
        promptError?.code, childStopReason) ?? classifyChildError(promptError?.message, promptError?.code, childStopReason);
      const childErrorMessage = failure?.message ?? diagnostics.childErrorMessage;
      const childErrorCode = failure?.code ?? diagnostics.childErrorCode;
      const evidence = build.evidence();
      report({ childStopReason, childErrorCode, childErrorMessage,
        childExitCode: safeExitCode(promptError?.exitCode) ?? safeExitCode(typeof promptError?.code === 'number' ? promptError.code : null),
        cancelled: diagnostics.cancelled || signal.aborted || turnLimitReached,
        timedOut: timedOut || diagnostics.timedOut,
        imageEvidence: { verified: Boolean(evidence) } });

      if (diagnostics.buildErrorCode || toolExecutionFailed) {
        throw fail(diagnostics.buildErrorMessage ?? 'build_image tool execution failed (details redacted)',
          diagnostics, 'NEWSHUB_BUILD_FAILURE');
      }
      if (signal.aborted || diagnostics.cancelled) {
        throw fail('Child inference was cancelled; no successful image verification was obtained', diagnostics, 'NEWSHUB_CHILD_FAILURE');
      }
      if (timedOut) {
        throw fail('Child inference timed out; no successful image verification was obtained', diagnostics, 'NEWSHUB_CHILD_FAILURE');
      }
      if (promptError || childStopReason === 'error' || agent.state?.errorMessage) {
        throw fail('Child inference failed (details redacted)', diagnostics, 'NEWSHUB_CHILD_FAILURE');
      }
      if (!last) {
        report({ childErrorMessage: 'Agent returned no assistant completion' });
        throw fail('Agent returned no assistant completion; no image verification was obtained', diagnostics, 'NEWSHUB_CHILD_FAILURE');
      }
      if (childStopReason !== 'stop') {
        throw fail('Child inference did not stop normally; no successful image verification was obtained', diagnostics, 'NEWSHUB_CHILD_FAILURE');
      }
      if (!diagnostics.buildCalled) {
        throw fail('Agent completed without calling build_image; no image verification was obtained', diagnostics, 'NEWSHUB_CHILD_FAILURE');
      }
      if (!evidence) {
        throw fail('Agent completed without verified image evidence', diagnostics, 'NEWSHUB_CHILD_FAILURE');
      }
      return { ...evidence, usage, diagnostics };
    } finally {
      clearTimeout(deadline);
      signal.removeEventListener('abort', abortForCaller);
      unsubscribe();
      try {
        agent.abort();
        await agent.waitForIdle();
      } catch { /* Keep the original child/tool failure as the terminal result. */ }
    }
  };
}

export { classifyChildError, safeBuildFailure };
