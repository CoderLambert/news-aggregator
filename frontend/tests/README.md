# Frontend tests

Frontend tests live outside application source in this directory. The directory tree mirrors src so test filenames remain easy to map back to the code they cover.

Relative imports to application modules use the @/ alias; @tests/ is available for shared test helpers and fixtures. Vitest discovery is configured for this directory.

Run the suite with npm run test:run. Run npm run typecheck and npm run build to verify TypeScript and the production bundle.

During the test move, Vitest discovery reported 45 files and 264 cases both before and after relocation.
