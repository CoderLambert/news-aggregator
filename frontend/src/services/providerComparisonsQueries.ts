import { queryOptions } from '@tanstack/react-query'
import {
  createProviderComparison as createProviderComparisonRequest,
  fetchProviderComparisons as fetchProviderComparisonsRequest,
  retestProviderComparison as retestProviderComparisonRequest,
} from '@/services/api'
import type { ProviderComparisonInput } from '@/services/api'
export type { ProviderComparisonInput } from '@/services/api'
import { isRecord } from '@/types/news'
import type { Language } from '@/types/news'
import type { ResearchViewerId } from '@/services/researchQueries'

export interface ProviderComparisonResponse {
  count: number
  next: string | null
  previous: string | null
  results: Record<string, unknown>[]
  adapted_sites: Record<string, unknown>[]
  metrics: Record<string, unknown>
}

function recordArray(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.filter(isRecord) : []
}

function parseProviderComparisonResponse(value: unknown): ProviderComparisonResponse {
  if (!isRecord(value) || !Array.isArray(value.results)) {
    throw new TypeError('Invalid provider comparison response')
  }
  return {
    count: typeof value.count === 'number' ? value.count : value.results.length,
    next: typeof value.next === 'string' ? value.next : null,
    previous: typeof value.previous === 'string' ? value.previous : null,
    results: recordArray(value.results),
    adapted_sites: recordArray(value.adapted_sites),
    metrics: isRecord(value.metrics) ? value.metrics : {},
  }
}

export const providerComparisonKeys = {
  all: ['providerComparisons'] as const,
  lists: () => [...providerComparisonKeys.all, 'list'] as const,
  list: (lang: Language, viewerId: ResearchViewerId) =>
    [...providerComparisonKeys.lists(), { lang, viewerId }] as const,
}

export const providerComparisonsOptions = (lang: Language, viewerId: ResearchViewerId) =>
  queryOptions({
    queryKey: providerComparisonKeys.list(lang, viewerId),
    queryFn: async ({ signal }): Promise<ProviderComparisonResponse> =>
      parseProviderComparisonResponse(await fetchProviderComparisonsRequest({}, signal) as unknown),
  })

export async function createProviderComparison(payload: ProviderComparisonInput, signal: AbortSignal): Promise<void> {
  await createProviderComparisonRequest(payload, signal)
}

export async function retestProviderComparison(id: number, signal: AbortSignal): Promise<void> {
  await retestProviderComparisonRequest(id, signal)
}
