# Channel worker least-privilege profile (NH-24)

The optional `channel-worker` is no longer an `extends: app` clone. The
[Compose overlay](../../compose.workspace.prod.yaml) deliberately grants only
SQLite, logs/heartbeat, and the specific gateway project secret. The container
starts from the same immutable image and preserves the existing app/migrate
release gates. No new task broker or external platform is introduced.

## Required configuration
Use the same production Compose project, pinned NEWSHUB_IMAGE, and explicit
`--env-file` as the existing deployment scripts. The worker needs
DJANGO_SECRET_KEY, WAITRESS_TRUSTED_PROXY, database path, site mode and AI
enablement, the provider credential encryption key, and the configured
loopback-only LiteLLM gateway URL/project secret. It must not receive the
web server's generic env_file or Chroma/TTS/runtime/model-cache volumes.

The gateway adapter **requires a loopback IP URL** by design. Therefore
`network_mode: host` remains explicitly necessary until an approved
gateway transport change is designed, tested, and deployed. Do not silently
swap it to bridge networking: BYOK classification would fail. This is a
documented remaining network isolation limitation, not a claim that network
egress is restricted.

## Safe release verification

- Validate with `docker compose --env-file <env> -f compose.prod.yaml -f
  compose.workspace.prod.yaml config`, without printing secrets in logs.
- Verify `docker inspect` container mounts, caps, user, read-only rootfs,
  pids/memory limits, and that no web-only environment variables are present.
- Run the existing `channel_worker_healthcheck` and a sandboxed
  classification with synthetic user credentials and mocked gateway.
- Verify no regressions in channel profile refresh, pending subscription
  recovery, lease/CAS fencing, and cancellation.
- Do not reload production Compose, rotate credentials or trigger paid model
  calls as part of this code change.

Rollback: redeploy a previously approved immutable image+Compose overlay via
the existing release manifest and rollback scripts. Preserve SQLite and logs.
