import type { QueryClient } from '@tanstack/react-query'
import { refreshRssViews } from './queryRefresh'

export interface ImportItem { id: string; title: string; feed_url: string; groups: string[]; status: string; error_code: string; operation_id: string | null; subscription_id?: number | null }
export interface ImportSummary {
  id: string; status: string; filename: string; file_size: number; file_available: boolean; created_at: string
  removed_at: string | null; removed_count: number; counts: Record<string, number>; total: number
}
export interface ImportBatch extends ImportSummary { preview_token?: string; items: ImportItem[]; groups: string[] }
export const batchKey = (viewer: number, id: string | null) => ['private', 'rss-import', viewer, id] as const
export const historyKey = (viewer: number) => ['private', 'rss-import-history', viewer] as const
export function invalidateImportEffects(client: QueryClient, viewer: number) {
  void refreshRssViews(client, viewer)
  void client.invalidateQueries({ queryKey: ['private', 'rss-subscriptions', viewer] })
  void client.invalidateQueries({ queryKey: historyKey(viewer) })
}
export const importStatusText: Record<string, string> = { preview: '待选择', invalid: '无效地址', pending: '等待处理', queued: '正在连接', succeeded: '已连接', failed: '处理失败', removed: '本批处理已停止' }
