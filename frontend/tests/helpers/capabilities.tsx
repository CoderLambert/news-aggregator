/* eslint-disable react-refresh/only-export-components */
import { useState } from 'react'
import type { ReactNode } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { QueryClient as QueryClientInstance } from '@tanstack/react-query'
import { CapabilityProvider } from '@/context/CapabilitiesContext'
import type { CapabilityName, SiteCapabilities } from '@/services/api'

const TEST_FEATURE_NAMES: CapabilityName[] = [
  'news', 'keyword_search', 'semantic_search', 'accounts', 'signup', 'favorites',
  'blocked_news', 'chat_history', 'fetch_full', 'translation', 'chat',
  'suggested_questions', 'tts', 'research', 'provider_comparisons', 'admin',
  'chatgpt_subscription',
]

export function fullCapabilities(overrides: Partial<Record<CapabilityName, boolean>> = {}): SiteCapabilities {
  return {
    site_mode: 'full',
    chatgpt_auth_mode: 'local_oss',
    features: Object.fromEntries(TEST_FEATURE_NAMES.map((name) => [
      name,
      { enabled: overrides[name] ?? true, reason: overrides[name] === false ? 'public_read_only' : null },
    ])) as SiteCapabilities['features'],
  }
}

export function readOnlyCapabilities(): SiteCapabilities {
  return {
    site_mode: 'read_only',
    chatgpt_auth_mode: 'disabled',
    features: Object.fromEntries(TEST_FEATURE_NAMES.map((name) => [
      name,
      name === 'news' || name === 'keyword_search'
        ? { enabled: true, reason: null }
        : { enabled: false, reason: 'public_read_only' },
    ])) as SiteCapabilities['features'],
  }
}

export function CapabilitiesTestProvider({
  children,
  value = fullCapabilities(),
  client: providedClient,
}: {
  children: ReactNode
  value?: SiteCapabilities
  client?: QueryClientInstance
}) {
  const [ownedClient] = useState(() => {
    const initialClient = providedClient ?? new QueryClient({ defaultOptions: { queries: { retry: false } } })
    initialClient.setQueryData(['capabilities'], value)
    return initialClient
  })
  const client = providedClient ?? ownedClient
  return (
    <QueryClientProvider client={client}>
      <CapabilityProvider>{children}</CapabilityProvider>
    </QueryClientProvider>
  )
}
