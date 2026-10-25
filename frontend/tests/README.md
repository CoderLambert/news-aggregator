# Frontend tests

Tests live outside application source and mirror `src/`. Use `@/` for application modules and `@tests/` for shared helpers. Vitest discovery is configured in `frontend/vite.config.js`; the only npm test entrypoints are in `frontend/package.json`.

During development, select tests for the changed behavior instead of repeatedly running the full suite. For example, from `frontend/`:

```sh
npm run test:run -- tests/pages/AIModelSettingsPage.test.tsx tests/services/aiConnectionsApi.test.ts
```

Use `npm run typecheck` and `npm run lint` for static checks, and `npm run build` for shipping bundle changes. Run `npm run test:run` for the full frontend suite at the approved acceptance stage. Do not use watch mode in automation.

The current Vitest suite uses jsdom. Passing these tests does not prove browser layout, CSS, or complete user journeys. Browser scenario tests and real-backend contract checks must report their own scope and evidence; a separate Scenario Lab is not NewsHub acceptance.

Use the current test report for counts and timings, not historical relocation totals. A targeted run, a skipped job, and a full passing suite are different results.
