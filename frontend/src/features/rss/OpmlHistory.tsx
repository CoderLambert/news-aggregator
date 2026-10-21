import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import { workspaceRequest, workspaceError } from '@/services/workspaceApi'
import { batchKey, historyKey, importStatusText, invalidateImportEffects, type ImportBatch, type ImportSummary } from './opmlTypes'

interface HistoryPage { count: number; page: number; has_next: boolean; results: ImportSummary[] }
const batchLabels: Record<string, string> = { preview: '尚未确认', confirmed: '后台处理中', complete: '已提交处理', removed: '已移除' }

export default function OpmlHistory({ viewer, onOpen, onBusyChange }: { viewer: number; onOpen: (id: string) => void; onBusyChange: (busy: boolean) => void }) {
  const client = useQueryClient()
  const [page, setPage] = useState(1)
  const [target, setTarget] = useState<ImportSummary | null>(null)
  const lifetime = useRef<AbortController | null>(null)
  useEffect(() => {
    const controller = new AbortController()
    lifetime.current = controller
    return () => { controller.abort(); lifetime.current = null }
  }, [])
  const history = useQuery({ queryKey: [...historyKey(viewer), page], retry: false,
    queryFn: ({ signal }) => workspaceRequest<HistoryPage>(`/me/rss-imports/?page=${page}`, { viewer, signal }),
  })
  const removal = useMutation({ retry: false,
    mutationFn: (id: string) => workspaceRequest<ImportBatch>(`/me/rss-imports/${id}/`, { method: 'DELETE', viewer, signal: lifetime.current?.signal }),
    onSuccess: batch => {
      if (!lifetime.current) return
      client.setQueryData(batchKey(viewer, batch.id), batch)
      invalidateImportEffects(client, viewer)
      setTarget(null)
    },
  })
  useEffect(() => { onBusyChange(removal.isPending); return () => onBusyChange(false) }, [removal.isPending, onBusyChange])
  const counts = (row: ImportSummary) => Object.entries(row.counts).map(([status, count]) => `${importStatusText[status] ?? status} ${count}`).join(' · ')
  return <section aria-label="导入历史" className="space-y-4">
    <p className="text-sm text-muted-foreground">原文件和导入记录仅自己可见。移除订阅后，仍可下载文件和查看记录。</p>
    {history.isPending && <p role="status">正在加载导入历史…</p>}
    {history.error && <p role="alert">{workspaceError(history.error)} <Button variant="outline" disabled={history.isFetching} onClick={() => void history.refetch()}>重新加载历史</Button></p>}
    {history.data?.count === 0 && <p role="status">还没有导入记录，上传 OPML 文件后会自动保存在这里。</p>}
    {removal.isSuccess && <p role="status" className="workspace-notice">已移除 {removal.data.removed_count} 个新增订阅</p>}
    {target && <section aria-label="确认移除本批订阅" className="space-y-3 rounded-lg border border-destructive/40 p-4">
      <h3 className="font-semibold">移除「{target.filename || '历史导入'}」新增的订阅？</h3>
      <p className="text-sm">将停止本批次尚未完成的导入，只移除此批次新增的个人订阅。保留共享频道、文章和导入前已有的订阅，以及后来重新订阅的频道。</p>
      {removal.error && <p role="alert">{workspaceError(removal.error)} 可重试移除；重复操作不会扩大删除范围。</p>}
      <div className="flex flex-wrap gap-2"><Button variant="destructive" disabled={removal.isPending} onClick={() => removal.mutate(target.id)}>确认移除新增订阅</Button>
        <Button variant="outline" disabled={removal.isPending} onClick={() => { setTarget(null); removal.reset() }}>保留订阅</Button></div>
    </section>}
    <ul className="space-y-3">{history.data?.results.map(row => <li key={row.id} className="space-y-2 rounded-lg border border-border p-4">
      <div className="flex flex-wrap justify-between gap-2"><strong className="break-all">{row.filename || '历史导入（未保存原文件）'}</strong><span className="text-sm text-muted-foreground">{batchLabels[row.status] ?? row.status}</span></div>
      <p className="text-xs text-muted-foreground"><time dateTime={row.created_at}>{new Date(row.created_at).toLocaleString('zh-CN')}</time> · 共 {row.total} 项{row.file_available && ` · ${(row.file_size / 1024).toFixed(1)} KiB`}</p>
      <p className="text-sm">{counts(row)}</p>
      {row.removed_at && <p className="text-sm">已移除 {row.removed_count} 个新增订阅</p>}
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" disabled={removal.isPending} onClick={() => onOpen(row.id)}>查看详情与进度</Button>
        {row.file_available && <Button asChild variant="outline"><a href={`/api/me/rss-imports/${row.id}/file/`} download>下载原文件</a></Button>}
        {!row.removed_at && <Button variant="outline" disabled={removal.isPending || !!target} onClick={() => { removal.reset(); setTarget(row) }}>移除此批新增订阅</Button>}
      </div>
    </li>)}</ul>
    {history.data && history.data.count > 20 && <nav aria-label="导入历史分页" className="flex items-center justify-between gap-2">
      <Button variant="outline" disabled={page <= 1 || removal.isPending || history.isFetching} onClick={() => { setTarget(null); setPage(value => value - 1) }}>上一页</Button>
      <span className="text-sm">第 {history.data.page} 页 · 共 {history.data.count} 次</span>
      <Button variant="outline" disabled={!history.data.has_next || removal.isPending || history.isFetching} onClick={() => { setTarget(null); setPage(value => value + 1) }}>下一页</Button>
    </nav>}
  </section>
}
