import { describe, expect, it } from 'vitest'
import {
  parseRuntimeHealth,
  runtimeHealthCheckNames,
  runtimeHealthOptions,
} from '@/services/runtimeHealthAdminApi'

function response(overrides: Record<string, unknown> = {}) {
  return {
    schema_version: 1,
    status: 'ready',
    ready: true,
    checked_at: '2026-10-24T10:00:00Z',
    checks: Object.fromEntries(runtimeHealthCheckNames.map((name) => [
      name,
      { enabled: true, ready: true, status: 'ready', code: '' },
    ])),
    ...overrides,
  }
}

describe('runtime health administrator contract', () => {
  it('parses every fixed component and keeps query data viewer scoped', () => {
    const parsed = parseRuntimeHealth(response())
    expect(parsed.ready).toBe(true)
    expect(Object.keys(parsed.checks)).toEqual([...runtimeHealthCheckNames])
    expect(runtimeHealthOptions(17).queryKey).toEqual(['runtimeHealth', 17])
    expect(runtimeHealthOptions(18).queryKey).toEqual(['runtimeHealth', 18])
  })

  it('fails closed on missing or contradictory component state', () => {
    const missing = response()
    delete (missing.checks as Record<string, unknown>).ai_gateway
    expect(() => parseRuntimeHealth(missing)).toThrow('Invalid runtime health check response')

    const contradictory = response({ status: 'unavailable', ready: true })
    expect(() => parseRuntimeHealth(contradictory)).toThrow('Inconsistent runtime health response')
  })
})
