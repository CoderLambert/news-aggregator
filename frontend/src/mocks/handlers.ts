import { http, HttpResponse } from 'msw/http'
import type { ScenarioBackend } from './backend.ts'

/** Only a transport adapter: browser and Node tests share the same synthetic contracts. */
export function scenarioHandlers(backend: ScenarioBackend, origin: string) {
  return [http.all(`${new URL(origin).origin}/api/*`, async ({ request }) => {
    const result = await backend.handle(request)
    return result.type === 'error' ? HttpResponse.error() : result
  })]
}
