export interface ArticleFetchFailureCode {
  provider: string
  code: string
}

export interface JinaFallbackPolicy {
  domain: string
  enabled: boolean
  autoDiscovered: boolean
  failureCount: number
  lastFailureCodes: ArticleFetchFailureCode[]
  lastSeenAt: string | null
  updatedAt: string
}

export interface ArticleFetchEvent {
  id: number
  newsId: number | null
  domain: string
  outcome: 'success' | 'failed' | 'validated' | 'legacy_validated'
  provider: string
  failureCodes: ArticleFetchFailureCode[]
  qualityScore: number | null
  contentLength: number
  elapsedMs: number
  createdAt: string
  persistenceOutcome?: string
  logicalOutcome?: string
  physicalRequests?: number
  httpStatuses?: number[]
  retryAfterAt?: string | null
}

export interface ArticleFetchDomainStats {
  domain: string
  total: number
  failed: number
  succeeded: number
}

export interface ArticleFetchProviderStats {
  provider: string
  outcome: 'success' | 'failed' | 'validated' | 'legacy_validated'
  count: number
}

export interface ArticleFetchDashboard {
  windowDays: number
  retentionDays: number
  summary: {
    total: number
    success: number
    failed: number
    successRate: number
    unresolvedArticles: number
  }
  domains: ArticleFetchDomainStats[]
  providers: ArticleFetchProviderStats[]
  topFailureCodes: Array<{ code: string; count: number }>
  policies: JinaFallbackPolicy[]
  recentEvents: ArticleFetchEvent[]
  serverTime: string
}
