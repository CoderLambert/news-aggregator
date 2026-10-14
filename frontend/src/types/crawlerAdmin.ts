export type CrawlRunStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancel_requested' | 'cancelled' | 'skipped'
export type CrawlBatchStatus = 'queued' | 'running' | 'succeeded' | 'partial' | 'failed' | 'cancelled'

export interface CrawlerSettings {
  schedulerEnabled: boolean
  intervalSeconds: number
  runOnWorkerStart: boolean
  nextRunAt: string | null
  workerHeartbeatAt: string | null
  workerInstanceId: string
  workerOnline: boolean
  updatedAt: string
}

export interface CrawlRun {
  id: string
  batchId: string
  spiderName: string
  targetName: string
  sourceActive?: boolean
  status: CrawlRunStatus
  queuedAt: string
  startedAt: string | null
  heartbeatAt: string | null
  finishedAt: string | null
  durationSeconds: number | null
  exitCode: number | null
  items: number
  responses: number
  errors: number
  httpStatuses: Record<string, number>
  finishReason: string
  safeError: string
  outcome?: string
  entriesCommitted?: number
  entriesChanged?: number
  warnings?: string[]
  retryOf: string | null
  latestRetryId: string | null
  latestRetryStatus: CrawlRunStatus | null
  latestRetryDisplayStatus?: string | null
  cancelRequestedAt: string | null
}

export interface CrawlerTarget {
  spiderName: string
  displayName: string
  enabled: boolean
  supported?: boolean
  unsupportedReason?: string
  sortOrder: number
  lastStatus: string
  lastResultStatus?: string
  lastStartedAt: string | null
  lastFinishedAt: string | null
  lastItems: number
  lastResponses: number
  lastErrors: number
  lastSafeError: string
  activeRun: CrawlRun | null
}

export interface CrawlBatch {
  id: string
  trigger: 'scheduled' | 'startup' | 'manual' | 'retry'
  status: CrawlBatchStatus
  queuedAt: string
  startedAt: string | null
  finishedAt: string | null
  total: number
  succeeded: number
  failed: number
  cancelled: number
  runs: CrawlRun[]
}

export interface CrawlerDashboard {
  settings: CrawlerSettings
  activeRun: CrawlRun | null
  targets: CrawlerTarget[]
  recentBatches: CrawlBatch[]
  serverTime: string
}

export type SourceConfigStatus = 'draft' | 'probed' | 'approved' | 'enabled' | 'blocked' | 'unsupported'
export type SourceEndpointKind = 'rss' | 'atom' | 'json' | 'html'

export interface SourceEndpointConfig {
  id?: number
  kind: SourceEndpointKind
  url: string
  allowedDomains: string[]
  priority: number
  parserConfig: Record<string, unknown>
  conditionalRequests: boolean
  requestIntervalSeconds: number
  maxResponseBytes: number
  maxPages: number
  maxItems: number
  enabled: boolean
}

export interface SourceProbeSample {
  title: string
  url: string
  identity: string
  publishedAt: string
}

export interface SourceMonitoring {
  lastSuccessAt: string | null
  lastFeedSuccessAt: string | null
  nextPollAt: string | null
  cooldownUntil: string | null
  lastTargetFinishedAt: string | null
  lastFailure: string
  lastHttpStatuses: Record<string, number>
  latestArticle: { id: number; title: string; url: string; publishTime: string } | null
}

export interface SourceConfigRecord {
  sourceKey: string
  sourceId: number | null
  publisherName: string
  channelName: string
  category: number | null
  categoryName: string
  region: 'domestic' | 'international'
  language: string
  contentKind: string
  readingPolicy: string
  status: SourceConfigStatus
  configVersion: number
  summaryAllowed: boolean
  feedFullContentAllowed: boolean
  officialHtmlFullContentAllowed: boolean
  probeSummary: Record<string, unknown> & { sample_articles?: unknown[]; outcome?: string; content_type?: string; http_status?: number }
  probedAt: string | null
  approvedAt: string | null
  unavailableReason: string
  maintenance: 'code' | 'database'
  probeIsCurrent: boolean
  approvalIsCurrent: boolean
  canEnable: boolean
  readOnly: boolean
  endpoints: SourceEndpointConfig[]
  monitoring: SourceMonitoring
}

export interface SourceConfigInput {
  source_key: string
  publisher_name: string
  channel_name: string
  category: number
  region: 'domestic' | 'international'
  language: string
  content_kind: string
  reading_policy: string
  summary_allowed: boolean
  feed_full_content_allowed: boolean
  official_html_full_content_allowed: boolean
  endpoints: Array<{
    kind: SourceEndpointKind
    url: string
    allowed_domains: string[]
    priority: number
    parser_config: Record<string, unknown>
    conditional_requests: boolean
    request_interval_seconds: number
    max_response_bytes: number
    max_pages: number
    max_items: number
    enabled: boolean
  }>
}
