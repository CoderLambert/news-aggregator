import { setupWorker } from 'msw/browser'
import { createScenarioBackend } from './backend.ts'
import type { BackendSnapshot } from './backend.ts'
import { getScenario } from './catalog.ts'
import { scenarioHandlers } from './handlers.ts'

export interface MockDiagnostics {
  readonly scenario: string
  readonly transport: 'msw'
  inspect(): BackendSnapshot
}
declare global { interface Window { __NEWSHUB_MOCK__?: MockDiagnostics } }

export async function startMocking(): Promise<void> {
  if (!import.meta.env.DEV || import.meta.env.MODE !== 'mock' || location.hostname !== '127.0.0.1') {
    throw new Error('Scenario mode is available only on the dedicated 127.0.0.1 development server')
  }
  const scenario = getScenario(new URLSearchParams(location.search).get('scenario') ?? 'normal')
  const backend = createScenarioBackend(scenario.id, { origin: location.origin })
  const worker = setupWorker(...scenarioHandlers(backend, location.origin))
  let startupTimer: ReturnType<typeof setTimeout> | undefined
  try {
    await Promise.race([worker.start({
    quiet: true,
    serviceWorker: { url: '/mockServiceWorker.js', options: { scope: '/' } },
    onUnhandledRequest(request, print) {
      const url = new URL(request.url)
      if (url.origin !== location.origin || url.pathname === '/api' || url.pathname.startsWith('/api/')) {
        print.error()
      }
      // Vite modules, the app stylesheet and same-origin static assets still load normally.
    },
    }), new Promise<never>((_, reject) => {
      startupTimer = setTimeout(() => reject(new Error('MSW startup timed out')), 8_000)
    })])
  } catch (cause) {
    worker.stop()
    backend.reset()
    throw cause
  } finally { clearTimeout(startupTimer) }
  Object.defineProperty(window, '__NEWSHUB_MOCK__', {
    configurable: false,
    value: Object.freeze({ scenario: scenario.id, transport: 'msw' as const, inspect: () => backend.inspect() }),
  })
}
