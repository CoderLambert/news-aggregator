/* eslint-disable react-refresh/only-export-components */
import { createContext, useContext } from 'react'
import type { ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import * as capabilitiesApi from '@/services/api'
import type { CapabilityName, CapabilityReason, SiteCapabilities } from '@/services/api'

export const CAPABILITIES_QUERY_KEY = ['capabilities'] as const

export const FAIL_CLOSED_CAPABILITIES: SiteCapabilities = {
  site_mode: 'read_only',
  chatgpt_auth_mode: 'disabled',
  features: {
    news: { enabled: true, reason: null },
    keyword_search: { enabled: true, reason: null },
    semantic_search: { enabled: false, reason: 'capabilities_unavailable' },
    accounts: { enabled: false, reason: 'capabilities_unavailable' },
    signup: { enabled: false, reason: 'capabilities_unavailable' },
    favorites: { enabled: false, reason: 'capabilities_unavailable' },
    blocked_news: { enabled: false, reason: 'capabilities_unavailable' },
    chat_history: { enabled: false, reason: 'capabilities_unavailable' },
    fetch_full: { enabled: false, reason: 'capabilities_unavailable' },
    translation: { enabled: false, reason: 'capabilities_unavailable' },
    chat: { enabled: false, reason: 'capabilities_unavailable' },
    suggested_questions: { enabled: false, reason: 'capabilities_unavailable' },
    tts: { enabled: false, reason: 'capabilities_unavailable' },
    research: { enabled: false, reason: 'capabilities_unavailable' },
    provider_comparisons: { enabled: false, reason: 'capabilities_unavailable' },
    admin: { enabled: false, reason: 'capabilities_unavailable' },
    chatgpt_subscription: { enabled: false, reason: 'capabilities_unavailable' },
  },
}

const REASON_MESSAGES: Record<CapabilityReason, string> = {
  public_read_only: '本站当前仅提供新闻阅读',
  ai_disabled: '此 AI 功能当前已关闭',
  semantic_search_disabled: '语义搜索当前不可用',
  signup_disabled: '公开注册当前已关闭',
  chatgpt_auth_disabled: 'ChatGPT 订阅连接当前已关闭',
  hosted_integration_unapproved: '网站订阅集成尚未获批',
  chatgpt_plan_usage_disabled: 'ChatGPT 订阅模型调用当前已关闭',
  capabilities_unavailable: '功能状态暂不可用，请稍后重试',
}

export function capabilityReasonMessage(reason: CapabilityReason | null | undefined): string {
  return reason ? REASON_MESSAGES[reason] : '此功能当前不可用'
}

interface CapabilitiesContextValue {
  capabilities: SiteCapabilities
  loading: boolean
  failed: boolean
}

const CapabilitiesContext = createContext<CapabilitiesContextValue | null>(null)

export function CapabilityProvider({ children }: { children: ReactNode }) {
  const query = useQuery({
    queryKey: CAPABILITIES_QUERY_KEY,
    queryFn: () => {
      if (typeof capabilitiesApi.fetchCapabilities !== 'function') {
        throw new Error('Site capabilities are unavailable')
      }
      return capabilitiesApi.fetchCapabilities()
    },
    staleTime: 60_000,
    retry: false,
  })

  const value: CapabilitiesContextValue = {
    capabilities: query.data ?? FAIL_CLOSED_CAPABILITIES,
    loading: query.isPending,
    failed: query.isError,
  }
  return <CapabilitiesContext.Provider value={value}>{children}</CapabilitiesContext.Provider>
}

export function useCapabilities(): CapabilitiesContextValue {
  return useContext(CapabilitiesContext) ?? {
    capabilities: FAIL_CLOSED_CAPABILITIES,
    loading: false,
    failed: true,
  }
}

export function useCapability(name: CapabilityName) {
  const value = useCapabilities()
  const feature = value.capabilities.features[name]
  return { ...value, enabled: feature?.enabled === true, reason: feature?.reason ?? 'capabilities_unavailable' as const }
}
