# Pi-native local image builder

The shared local entry is `scripts/local-image-build`; the project extension and worker remain the single build implementation. The entry satisfies the fixed native `newshub-local-image-builder-luna` role for Pi and non-Pi Agents. It never invokes OMP, installs packages, or accepts an arbitrary prompt, model, reasoning level, or Docker target.

## Preview and execution

Pass an explicit lowercase 40-hex commit SHA. The default is a read-only preview; only `--execute` starts the task:

```sh
scripts/local-image-build --help
scripts/local-image-build --sha <commit-sha>          # preview; Git commit-object check only
scripts/local-image-build --sha <commit-sha> --execute
```

The SHA must identify an actual commit object available in this repository. Branch names, tags, abbreviated IDs, blobs, unknown commits and shell expressions are rejected. The commit need not equal HEAD or be an ancestor of `main`; feature commits are supported. There is no inferred default target. In execution mode, the CLI starts a one-shot Pi process pinned to `openai-codex/gpt-6-luna` and `xhigh`, loads only `.pi/extensions/newshub-image-builder/index.ts`, allows only `newshub_image_builder`, and disables MCP, discovered extensions, skills, prompt templates, context-file discovery, project approval and session persistence. The fixed prompt starts one authorized job and waits for that job to become terminal.

Execution prerequisites: use a supported installed Pi CLI with configured OpenAI Codex authentication and a trusted checkout of this project. The CLI resolves the actual executable with read-only `mise which pi`, then an installed `pi` on PATH; `NEWSHUB_PI_BIN` may explicitly name an absolute executable. It performs no global Pi configuration changes or package installation. The wrapper requires `node` on PATH. `--no-approve` prevents unrelated trust-gated project resources from being loaded; the explicit project extension is still loaded.

The CLI checks JSONL tool receipts, exact job/SHA/model/thinking identity, verified image metadata, a normal assistant stop, `agent_settled` with `aborted=false`, and child exit code zero. Assistant text alone, malformed or missing receipts, a failed/aborted job, EOF, identity mismatch or nonzero child exit is failure. Success is one machine-readable JSON object on stdout; errors are machine-readable JSON on stderr with nonzero exit status. Raw prompts, provider diagnostics, tokens and child stderr are not returned. Cancellation signals only the CLI's own Pi child.

## Source and image outcomes

Before model inference or Docker work, the worker validates the exact commit object in this repository. It reads rules and exports runtime input only from immutable Git blobs at that SHA, applying the existing filename/symlink/size filters; dirty worktree bytes are never used.

The builder inspects `newshub:dev-<sha>` on the host first. An existing image is reusable only when its revision label, Linux/native platform, root development user, expected entrypoint command, and `HOME=/root` plus `HF_HOME=/root/.cache/huggingface` cache contract match. Inspection projects only allowlisted image metadata, never the full environment. A host hit returns its immutable image ID with `hostRuntime.status=ready`; it needs no CI transport, source export, build client or idle Runner check. Daemon/access errors and conflicting or malformed metadata fail closed and never trigger an overwrite.

If the host tag is genuinely missing, the isolated private DinD image is inspected. A verified private hit skips source export and build, returns `hostRuntime.status=transfer-required`, and does not transfer, retag or deploy. If both tags are missing, one locked fresh build runs in isolated DinD with the existing private socket/client and `development` target. Fresh builds retain Runner.Worker idle checks; existing Redis or other containers are not busy signals and are never stopped. The private image remains private: transfer to the host runtime is not implemented.

Results distinguish `reused`, `buildPerformed`, and `buildExitCode`. Reuse has `buildPerformed=false` and a null build exit code; a fresh build reports its real exit status. The build target is local development only (root user and the existing data/cache paths), not the non-root production target. No production build, migration, service operation, deployment, image push or CI run is part of this entry.

## Offline verification

The existing unittest discovery entry covers the Node offline regressions without Docker or provider calls:

```sh
python3.12 -m unittest discover -s ops/ci/tests -p 'test_pi_image_builder.py'
node .pi/extensions/newshub-image-builder/tests/load-smoke.mjs /path/to/@earendil-works/pi-coding-agent
```

The loader smoke registers the real tool, checks bound-SHA/one-start enforcement, queries and waits with a stub registry, and makes zero inference/build calls. Offline evidence does not prove a live provider, real Docker daemon, image build, production behavior or CI result.
