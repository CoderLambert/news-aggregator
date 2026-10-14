# A09 remaining implementation status

Baseline: `0dc445a77b12ec45b8a97d42f75e0df62e1b72d9`.

This integration branch groups related changes and uses small, isolated test batches. The complete repository CI remains the final integration gate. A code commit, successful unit test, image build and production acceptance are different states.

## Batch A (in progress)

- NH-16: owner application history, administrator approval/rejection and safe URL admission. Approval never registers/enables a crawler. Migration 0047 is additive.
- NH-17: bounded article-title/metadata evidence, checked before inference, before result commit and before applying a private AI preview. Stale evidence requires explicit new authorization rather than an automatic paid retry.
- NH-19: promote a verified publisher's metadata over an HN discovery pointer without changing article identity or full-body revision.
- NH-32: keep ETag/checkpoints on display-description changes; identity, body, date and admission changes still invalidate.

Status at this commit: source staged for isolated integration; tests have not yet been run. Do not deploy this commit.

## Remaining work

NH-18, NH-20–NH-31 (including unfinished NH-22) and NH-33 still require their remaining source changes and tests. Prior implementations NH-01–NH-15 are not being rebuilt.

## External acceptance

Production DNS/TLS, real provider billing/authorization, licensed source sampling, off-host backups/key recovery and capacity measurements on the actual 2C/4GB VPS remain NOT_RUN. No production environment, actual model key or real source crawl is authorized by this development batch.

The temporary `.a09-workbench` and its write-scoped integration workflow are removed before the final PR. The permanent CI has read-only permissions and retains all existing tests, image builds and G1 checks.
