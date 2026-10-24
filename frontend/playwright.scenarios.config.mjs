import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './e2e/scenarios',
  testMatch: '**/*.spec.ts',
  fullyParallel: true,
  workers: 2,
  forbidOnly: Boolean(process.env.CI),
  retries: 0,
  timeout: 30_000,
  expect: { timeout: 10_000 },
  reporter: [['list'], ['html', { outputFolder: 'e2e/scenarios/.artifacts/report', open: 'never' }]],
  outputDir: 'e2e/scenarios/.artifacts/results',
  use: { ...devices['Desktop Chrome'], baseURL: 'http://127.0.0.1:9530',
    serviceWorkers: 'allow', trace: 'retain-on-failure', screenshot: 'only-on-failure' },
  webServer: { command: 'npm run dev:mock', url: 'http://127.0.0.1:9530',
    reuseExistingServer: false, timeout: 120_000 },
})
