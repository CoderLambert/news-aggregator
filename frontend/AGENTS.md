# NewsHub Frontend Rules

Read [root rules](../AGENTS.md). Keep the existing React/TypeScript/Vite architecture; do not introduce a parallel client or state framework.

## UI implementation
- Prefer existing shadcn/ui components under `src/components/ui` and shared project wrappers for buttons, inputs, selects, dialogs, popovers, tables and other interactive UI. Add a missing shadcn component to that shared directory before building a custom replacement.
- Avoid raw native interactive controls or hand-built equivalents unless existing components cannot reasonably satisfy the requirement; document the specific reason locally when an exception is needed. Semantic HTML for layout, headings, labels and article content remains appropriate.
- Reuse the current searchable Popover + Command selection UI for long provider, endpoint or model lists. Support name/ID filtering, bounded scrolling, empty states, keyboard selection and focus restoration. Inside dialogs, keep the popup in the dialog layer and let Escape close the popup before the dialog.
- Use the existing design tokens, spacing and component variants; do not create parallel styling or selection implementations for the same interaction.

- Article reading, chat, translation and research views consume saved task/default model bindings. Keep model configuration controls and links in AI settings; do not reintroduce model pickers or configuration links into these reading flows. Distinguish unavailable configuration from a failed metadata read; preserve explicit send consent and existing task recovery.

## State and transport
- `src/App.tsx` owns route composition and feature gates. URL/Router owns navigable filters; TanStack Query owns server state; Zustand in `stores/preferences.ts` owns client preferences. Do not duplicate fetched server data in another global store.
- Reuse `services/api.ts`, `workspaceApi.ts`, existing query-key factories and DTO parsers. Preserve Session/CSRF, AbortSignal and viewer-scoped keys. Account switch/logout/unmount must block stale responses and clear private state.
- FeatureRoute/Capabilities are UI gates, not substitutes for server authorization; unknown capabilities remain fail-closed. Never store or echo API/OAuth credentials in client persistence or errors.
- Keep list summaries distinct from detail bodies. Preserve reading position, error/retry states, cancellation and real SSE terminal semantics; EOF or a closed browser connection does not mean server success/cancellation.
- Reuse components and CSS variables. Verify loading/empty/error states, keyboard/focus restoration and narrow-screen behavior when affected; component tests are not a claim of manual mobile/browser UAT.

## Verification
- Use the existing `frontend/package-lock.json` and npm scripts; do not switch to pnpm or regenerate lockfiles for unrelated changes. CI's Node version is declared in the workflow, not the host's newest Node.
- From `frontend/`: `npm run typecheck`, `npm run lint`, then `npm run test:run -- tests/pages/AIModelSettingsPage.test.tsx tests/services/aiConnectionsApi.test.ts` for AI settings; choose existing tests matching other changes. Use `test:run`, not watch mode, in automation.
- Build with `npm run build` for shipping UI/bundle changes. Tests live under `frontend/tests/`, mirror `src/`, and use `@/` / `@tests/` aliases; read [test rules](../tests/AGENTS.md).
- Changes to responses, permissions, content identity or streaming require checking the backend contract even when only the frontend CI job is selected.

## Code Review Rules
Flag cross-viewer cache leakage, response parser drift, CSRF bypass, stale async writes and fabricated stream completion. Require a focused regression for changed behavior; avoid unrelated visual rewrites or formatting churn.
