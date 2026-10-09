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
  retryOf: string | null
  latestRetryId: string | null
  latestRetryStatus: CrawlRunStatus | null
  cancelRequestedAt: string | null
}

export interface CrawlerTarget {
  spiderName: string
  displayName: string
  enabled: boolean
  sortOrder: number
  lastStatus: string
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
