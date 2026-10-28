import type { QueryClient } from '@tanstack/react-query'
import { refreshRssViews } from './queryRefresh'

export interface ImportItem { id: string; title: string; feed_url: string; groups: string[]; status: string; error_code: string; operation_id: string | null; subscription_id?: number | null; outcome?: string; next_attempt?: string | null; can_retry?: boolean; can_organize?: boolean; duplicate_count?: number }
export interface ImportSummary {
  id: string; status: string; filename: string; file_size: number; file_available: boolean; created_at: string
  removed_at: string | null; removed_count: number; paused?: boolean; cancelled_at?: string | null; duplicate_count?: number; outcomes?: Record<string, number>; counts: Record<string, number>; total: number
}
export interface ImportBatch extends ImportSummary {
  preview_token?: string; items: ImportItem[]; groups: string[]
  organize_existing?: boolean; organization_only?: boolean
  group_plan?: Record<string, { root_name: string | null; name: string; action: 'create' | 'reuse' | 'conflict'; group_id: number | null; create_root: boolean; reason: string }>
  group_matches?: Record<string, number>; group_labels?: Record<string, string>; group_names?: Record<string, string>
}
export const batchKey = (viewer: number, id: string | null) => ['private', 'rss-import', viewer, id] as const
export const historyKey = (viewer: number) => ['private', 'rss-import-history', viewer] as const
export function invalidateImportEffects(client: QueryClient, viewer: number) {
  void refreshRssViews(client, viewer)
  void client.invalidateQueries({ queryKey: ['private', 'rss-subscriptions', viewer] })
  void client.invalidateQueries({ queryKey: historyKey(viewer) })
}
export const importStatusText: Record<string, string> = { preview: '待选择', invalid: '无效地址', pending: '等待处理', queued: '正在连接', succeeded: '已连接', failed: '处理失败', removed: '本批处理已停止' }

export const importOutcomeText: Record<string, string> = { organized: '已整理归组', connected: '已接入', invalid: '无效地址', already_subscribed: '已订阅，跳过', reused: '复用已有渠道', following: '等待共享接入', waiting: '等待接入', connecting: '正在接入', retry_wait: '稍后自动重试', checking: '正在核对连接结果', needs_attention: '需要处理', paused: '已暂停', cancelled: '已取消' }
