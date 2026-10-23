import { queryOptions } from '@tanstack/react-query'
import { isRecord } from '@/types/news'
import { workspaceRequest } from '@/services/workspaceApi'

export const runtimeHealthCheckNames = [
  'database',
  'rss_worker',
  'rss_engine',
  'channel_worker',
  'search_index',
  'translation_redis',
  'ai_gateway',
] as const

export type RuntimeHealthCheckName = typeof runtimeHealthCheckNames[number]
export type RuntimeHealthStatus = 'ready' | 'unavailable' | 'disabled'

export interface RuntimeHealthCheck {
  enabled: boolean
  ready: boolean
  status: RuntimeHealthStatus
  code: string
}

export interface RuntimeHealthSnapshot {
  schemaVersion: 1
  status: 'ready' | 'unavailable'
  ready: boolean
  checkedAt: string
  checks: Record<RuntimeHealthCheckName, RuntimeHealthCheck>
}

function parseCheck(value: unknown): RuntimeHealthCheck {
  if (!isRecord(value)) throw new TypeError('Invalid runtime health check response')
  const status = value.status
  if (!['ready', 'unavailable', 'disabled'].includes(typeof status === 'string' ? status : '')) {
    throw new TypeError('Invalid runtime health check status')
  }
  if (typeof value.enabled !== 'boolean' || typeof value.ready !== 'boolean' || typeof value.code !== 'string') {
    throw new TypeError('Invalid runtime health check fields')
  }
  if ((status === 'disabled') !== !value.enabled || (status === 'ready') !== value.ready) {
    throw new TypeError('Inconsistent runtime health check state')
  }
  return { enabled: value.enabled, ready: value.ready, status: status as RuntimeHealthStatus, code: value.code }
}

export function parseRuntimeHealth(value: unknown): RuntimeHealthSnapshot {
  if (
    !isRecord(value)
    || value.schema_version !== 1
    || !['ready', 'unavailable'].includes(typeof value.status === 'string' ? value.status : '')
    || typeof value.ready !== 'boolean'
    || typeof value.checked_at !== 'string'
    || !isRecord(value.checks)
  ) {
    throw new TypeError('Invalid runtime health response')
  }
  const checks = {} as Record<RuntimeHealthCheckName, RuntimeHealthCheck>
  for (const name of runtimeHealthCheckNames) checks[name] = parseCheck(value.checks[name])
  if ((value.status === 'ready') !== value.ready) throw new TypeError('Inconsistent runtime health response')
  return {
    schemaVersion: 1,
    status: value.status as RuntimeHealthSnapshot['status'],
    ready: value.ready,
    checkedAt: value.checked_at,
    checks,
  }
}

export async function fetchRuntimeHealth(signal?: AbortSignal): Promise<RuntimeHealthSnapshot> {
  return parseRuntimeHealth(await workspaceRequest<unknown>('/admin/runtime-health/', { signal }))
}

export const runtimeHealthKeys = {
  all: ['runtimeHealth'] as const,
  byViewer: (viewer: number) => [...runtimeHealthKeys.all, viewer] as const,
}

export const runtimeHealthOptions = (viewer: number) => queryOptions({
  queryKey: runtimeHealthKeys.byViewer(viewer),
  queryFn: ({ signal }) => fetchRuntimeHealth(signal),
  staleTime: 10_000,
  refetchInterval: () => typeof document !== 'undefined' && document.hidden ? false : 30_000,
})
