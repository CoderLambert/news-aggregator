export type SearchIndexRunStatus = 'queued' | 'running' | 'cancel_requested' | 'cancelled' | 'succeeded' | 'failed'
export type SearchIndexRunMode = 'sync' | 'rebuild'

export interface SearchIndexSettings {
  enabled: boolean
  intervalSeconds: number
  batchSize: number
  activeCollection: string
  modelName: string
  schemaVersion: string
  nextRunAt: string | null
  workerHeartbeatAt: string | null
  workerInstanceId: string
  workerOnline: boolean
  lastSuccessAt: string | null
  updatedAt: string
}

export interface SearchIndexAudit {
  available: boolean
  newsCount: number
  vectorCount: number
  missingCount: number
  changedCount: number
  orphanedCount: number
  errorCode: string
}

export interface SearchIndexRun {
  id: string
  trigger: 'startup' | 'scheduled' | 'crawl_batch' | 'manual' | 'recovery'
  mode: SearchIndexRunMode
  status: SearchIndexRunStatus
  crawlBatch: string | null
  collectionName: string
  modelName: string
  schemaVersion: string
  newsCount: number
  vectorCountBefore: number
  vectorCountAfter: number
  missingCount: number
  changedCount: number
  orphanedCount: number
  upsertedCount: number
  deletedCount: number
  failedCount: number
  safeErrorCode: string
  safeErrorMessage: string
  queuedAt: string
  startedAt: string | null
  heartbeatAt: string | null
  finishedAt: string | null
  cancelRequestedAt: string | null
  durationSeconds: number | null
}

export interface SearchIndexDashboard {
  settings: SearchIndexSettings
  audit: SearchIndexAudit
  activeRun: SearchIndexRun | null
  recentRuns: SearchIndexRun[]
  serverTime: string
}
