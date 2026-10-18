# NewsHub CI changed-file routing

The normal CI retains the existing isolated frontend and backend/DinD runners.
A lightweight \`changes\` job runs on the frontend runner to determine which
checks are necessary, then the existing jobs run only when selected.

| Changed paths | Frontend | Backend including Docker build/G1 |
|---|---|---|
| \`frontend/**\` | Yes | No |
| \`backend/**\`, \`crawler/**\`, \`tests/**\`, RSS/proxy/backend tests | No | Yes |
| API routing/serialization contracts, \`.github/**\`, \`ops/ci/**\`, compose, Dockerfile, unknown paths | Yes | Yes |
| \`docs/**\`, root README/TESTING/CHANGELOG/DEVLOG | No | No |
| Both frontend and backend paths | Yes | Yes |
| Any metadata/Git/diff error or empty unexpected diff | Yes | Yes |
| Manual \`workflow_dispatch\` | Yes | Yes |

The router compares PR head to its Git merge-base with PR base, or the *full*
\`github.event.before..github.sha\` range for main pushes. Renames are treated
as a delete plus add so both source and destination affect classification.
This avoids examining only the final commit. Detection uses no API token, third-
party path-filter action or external service. Unknown paths fail safe by running
both jobs rather than silently skipping a suite.

The \`changes\` job uses the dedicated frontend runner but neither installs
dependencies nor accesses Docker. It introduces a small ordering dependency,
not another full build. Fork/Draft PR behavior is unchanged.

Manual full recheck:

\`\`\`bash
gh workflow run ci.yml --repo CoderLambert/news-aggregator --ref main
\`\`\`

Offline regression tests:

\`\`\`bash
python3 -m unittest discover -s ops/ci/tests -p 'test_change_scope.py'
\`\`\`

**Limitations:** Path selection is conservative, not a complete dependency
graph. Backend API payload semantics can still change without a renamed route
or serializer file; backend checks include G1 smoke, but no selective test
strategy can replace release-time full verification. Before a production release,
manually run the full workflow. No skip may be interpreted as an executed test
PASS. The router does not weaken any tests inside the jobs it actually selects.

To extend classifications, change \`ops/ci/change_scope.py\` and extend
\`ops/ci/tests/test_change_scope.py\`. Editing either file routes both suites.
