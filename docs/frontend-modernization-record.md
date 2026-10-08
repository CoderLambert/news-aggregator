# Frontend modernization record

- Date: 2026-10-08
- Branch: `codex/frontend-list-query-slice`
- Delivery scope: document the audited modernization path and move the existing frontend test suite out of application source; no runtime feature or API behavior change in this slice.

## Change objective

The frontend modernization request is to simplify and type-check the existing React app in feature slices while retaining URL-owned route state, TanStack Query server-state ownership, client-only Zustand state, Django session/CSRF behavior, and the existing JSON/SSE contracts. This push contains the test-layout/configuration slice; the broader migration plan below remains follow-up work.

## Actual changes

| File or area | Module | What changed |
| --- | --- | --- |
| `frontend/src/**/*.test.{js,jsx}` → `frontend/tests/**` | Frontend tests | Relocated the existing 45 test files to a directory parallel to `src`; updated application imports to the `@/` alias where needed. |
| `frontend/tests/README.md` | Test documentation | Documented the new test location, aliases, and commands. |
| `frontend/tsconfig.json` | TypeScript/test config | Added `@tests/*`, Vitest globals, and included the external test tree in type checking. |
| `frontend/vite.config.js` | Vite/Vitest config | Added the `@tests` alias and pointed Vitest discovery at `tests/**`. |
| `docs/frontend-modernization-record.md` | Project record | Recorded the baseline, current architecture, validation, and phased follow-up plan. |

## Key implementation

Test files now live outside the application source tree while mirroring its directory layout, so implementation files remain easy to locate. The `@/` alias resolves application imports from tests; `@tests/` is reserved for shared test helpers. Vitest still discovers JavaScript and TypeScript tests from the test tree.

## Behavior and compatibility

No runtime React component, backend endpoint, data model, authentication flow, or API/SSE contract changed in this slice. Test discovery and import resolution changed; the same 45 files and 264 cases remain in the suite.

## Baseline and current architecture

- Branch base during audit: `b616790945d98cd30b85e267f3f89c93a38f05da`.
- Runtime: Node 24.21.0 and npm 11.19.0. Existing dependencies already include React 19, TypeScript 6, TanStack Query 5, Zustand 5, Tailwind 4, and shadcn/Radix primitives; no package upgrade is included.
- `frontend/src` had 85 production files: 58 TS/TSX and 27 JS/JSX. TypeScript is strict, but `allowJs: true` and `checkJs: false` leave JavaScript unchecked. The Vite entry is `main.jsx`, which imports the TSX app.
- TanStack Query already owns news list/detail, filters, favorites/blocked lists, research, and provider comparisons. List/search filters are URL parameters; retain the language/viewer query-key partitioning and request cancellation.
- Zustand currently stores language/display preferences. The audio player separates state, actions, and capabilities into contexts; retain that render boundary unless profiling says otherwise. Routes are already lazy-loaded and Mermaid is loaded on demand.
- Existing routes: `/`, `/search`, `/news/:id`, `/favorites`, `/provider-comparisons`, and design-only `/__mascot__`. There is no settings route; language and display controls live in the header.
- Existing article fetch/translation, chat, suggested questions, TTS, favorites/blocks, local research, and session authentication use established API and SSE behavior. Preserve those contracts.
- The read-only browser check showed the live Vite news list at `127.0.0.1:5173/?source=10`. Its “翻译失败” badges reflect persisted translation status; the parent task separately traced old records to a missing `deep_translator` dependency and fixed that runtime dependency.

## Validation

| Command or check | Result |
| --- | --- |
| `npm run typecheck` | Passed after test relocation. |
| `npm run lint` | Passed after test relocation. |
| `npm run test:run` | Passed: 45 files, 264 tests. jsdom printed its existing `window.scrollTo()` not-implemented warning. |
| `npm run build` | Passed: Vite transformed 4,317 modules and built the production bundle. |
| Chrome read-only page check | Passed: current list, filters, pagination, and cards rendered. |

## Risks, limitations, and follow-up

1. **Shared UI and TypeScript boundary:** Switch the shadcn generator to TSX and migrate shared/high-traffic JS/JSX incrementally; keep strict types and validate API data at service boundaries. Acceptance: focused tests, typecheck, lint, keyboard/focus, and small-screen checks pass.
2. **Feed and search:** Retain URL-owned filters and TanStack Query as the only server-data cache; consolidate list/search duplication only where it exists. Acceptance: deep links, back/forward, search modes, filters, and pagination preserve current API parameters and behavior.
3. **Article detail:** Preserve detail query ownership and SSE protocol; keep progress/cancel transient and update query cache only after authoritative events. Acceptance: navigation, cancellation/re-entry, success/error streams, and user-scoped controls pass.
4. **Remaining feature slices:** Cover auth transitions, favorites/blocks, provider comparison, and research mutation/stream behavior with focused tests. Keep shared UI state in Zustand and one-component interaction state local.
5. **Final verification:** Run build, typecheck, lint, and full tests; inspect desktop/mobile rendering and keyboard flows in the existing browser; check for route/API regressions.

Pre-existing changes excluded from this delivery: `backend/db.sqlite3`, `docs/startup.md`, `.dockerignore`, `Dockerfile`, and `compose.yaml`. None were staged or edited for this push.
