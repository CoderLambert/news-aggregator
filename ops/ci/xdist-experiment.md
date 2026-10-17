# CI-P01 — isolated pytest-xdist feasibility gate

Initial **full** `-n 2 --dist=loadfile` experiment ran 2424 tests in
125.48 seconds, but failed 16 seed-dependent Django tests. That configuration
is **not safe** to enable as the normal release gate.

The current benchmark tests a fail-closed hybrid:
- Seven state/seed-sensitive Django modules always run **serial**, retaining
  their migration and database fixture behavior.
- The remaining files execute on `-n 2 --dist=loadfile`, using normal
  per-worker database isolation. Both parts run three times.
- Each repetition checks the authoritative pytest terminal totals:
  **2410 passed / 16 explicitly skipped** across serial and parallel roots. The two additional passing cases are the G1 paint regressions merged in PR #86; the 16 skips and all other failure checks are unchanged.
  JUnit XML is independently inspected for failures/errors. We avoid counting
  JUnit test-suite summary attributes that disagreed with pytest's actual
  terminal outcomes during the first hybrid experiment.
- Failures are never reclassified as skipped; normal CI still runs serially.
- Tooling versions are frozen (`pytest-xdist==3.8.0`,
  `execnet==2.1.1`) and installed into a separate private cache, not the
  backend venv or production dependencies.
- CI-P01 remains opt-in and keeps the required serial backend/G1 CI intact.
  Default parallel adoption requires all three hybrid runs to pass, and an
  independently green default CI run after switching.

No live RSS opt-in, external ports, secrets or production data are used.
