import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import WorkspaceModal from '@/components/workspace/WorkspaceModal'
import { workspaceRequest, workspaceError } from '@/services/workspaceApi'
import type { ChannelGroup } from '@/types/channels'

interface ImportItem { id: string; title: string; feed_url: string; groups: string[]; status: string; error_code: string; operation_id: string | null }
interface ImportBatch { id: string; status: string; preview_token?: string; items: ImportItem[]; groups: string[] }
const statusText: Record<string, string> = { preview: '待选择', invalid: '无效地址', pending: '等待处理', queued: '正在连接', succeeded: '已连接', failed: '处理失败' }

export default function OpmlDialog({ viewer, groups, onClose }: { viewer: number; groups: ChannelGroup[]; onClose: () => void }) {
  const client = useQueryClient()
  const [file, setFile] = useState<File | null>(null)
  const [selected, setSelected] = useState<string[]>([])
  const [groupMap, setGroupMap] = useState<Record<string, string>>({})
  const [batchId, setBatchId] = useState<string | null>(null)
  const [resumeId, setResumeId] = useState('')
  const preview = useMutation({ mutationFn: async (upload: File) => {
    if (upload.size > 1024 * 1024) throw new Error('文件须小于1MiB。')
    const body = new FormData(); body.append('file', upload)
    return workspaceRequest<ImportBatch>('/me/rss-imports/preview/', { method: 'POST', body, viewer })
  }, onSuccess: batch => { setSelected(batch.items.filter(item => item.status !== 'invalid').map(item => item.id)); setGroupMap({}); setBatchId(null) } })
  const confirm = useMutation({ mutationFn: () => workspaceRequest<ImportBatch>('/me/rss-imports/confirm/', {
    method: 'POST', viewer, body: { preview_token: preview.data?.preview_token, selected_ids: selected,
      group_map: Object.fromEntries(Object.entries(groupMap).map(([label, value]) => [label, value === 'new' ? { create: label.slice(0, 40) } : value ? Number(value) : null])) },
  }), onSuccess: batch => { setBatchId(batch.id); void client.invalidateQueries({ queryKey: ['channels'] }); void client.invalidateQueries({ queryKey: ['workspace'] }) } })
  const progress = useQuery({ queryKey: ['private', 'rss-import', viewer, batchId], enabled: !!batchId,
    queryFn: ({ signal }) => workspaceRequest<ImportBatch>(`/me/rss-imports/${batchId}/`, { signal }),
    refetchInterval: query => query.state.data?.items.some(item => ['pending', 'queued'].includes(item.status)) ? 2000 : false,
  })
  const retry = useMutation({ mutationFn: (ids: string[]) => workspaceRequest<ImportBatch>(`/me/rss-imports/${batchId}/`, { method: 'POST', viewer, body: { selected_ids: ids } }),
    onSuccess: () => { void progress.refetch() } })
  const busy = preview.isPending || confirm.isPending || retry.isPending
  const error = preview.error ?? confirm.error ?? progress.error ?? retry.error
  const batch = batchId ? progress.data : preview.data
  return <WorkspaceModal title="导入与导出订阅" onClose={onClose} busy={busy}>
    <p className="workspace-muted">上传 OPML 文件，先检查订阅与分组，再确认导入。最多500个订阅，文件不超过1MiB。</p>
    <form className="workspace-inline-form" onSubmit={event => { event.preventDefault(); if (file) preview.mutate(file) }}>
      <label>OPML 文件<input type="file" accept=".opml,.xml,text/xml,application/xml" disabled={busy} onChange={event => setFile(event.target.files?.[0] ?? null)} /></label>
      <button type="submit" className="workspace-button" disabled={busy || !file || file.size > 1024 * 1024}>预览文件</button>
    </form>
    {file && file.size > 1024 * 1024 && <p role="alert">文件超过1MiB，请缩小后重试。</p>}
    <p><a className="workspace-link" href="/api/me/rss-subscriptions/export/" download="subscriptions.opml">导出我的订阅</a></p>
    <form className="workspace-inline-form" onSubmit={event => { event.preventDefault(); setBatchId(resumeId.trim()) }}>
      <label>恢复导入记录<input value={resumeId} placeholder="导入记录编号" onChange={event => setResumeId(event.target.value)} /></label>
      <button className="workspace-button secondary" disabled={busy || !/^[0-9a-f-]{36}$/i.test(resumeId.trim())}>查看进度</button>
    </form>
    {error && <p role="alert" className="workspace-error">{workspaceError(error)}</p>}
    {batch && <section aria-label="导入预览与进度">
      {batchId && <p role="status">导入记录：<code>{batch.id}</code>。关闭窗口后仍会继续，可用此编号恢复查看。</p>}
      {!batchId && batch.groups.map(label => <label className="workspace-resolved-choice" key={label}>{label}
        <select aria-label={label + '映射分组'} disabled={busy} value={groupMap[label] ?? ''} onChange={event => setGroupMap(current => ({ ...current, [label]: event.target.value }))}>
          <option value="">不加入分组</option><option value="new">创建「{label.slice(0, 40)}」</option>{groups.map(group => <option key={group.id} value={group.id}>{group.name}</option>)}
        </select></label>)}
      <ul className="workspace-resolved">{batch.items.map(item => <li key={item.id} className="workspace-resolved-choice">
        {!batchId && <input type="checkbox" aria-label={'导入 ' + (item.title || item.feed_url)} disabled={busy || item.status === 'invalid'} checked={selected.includes(item.id)} onChange={event => setSelected(current => event.target.checked ? [...current, item.id] : current.filter(id => id !== item.id))} />}
        <span><strong>{item.title || item.feed_url}</strong><small className="break-all">{item.feed_url}</small><small>{statusText[item.status] ?? '等待确认'}{item.error_code ? ' · ' + item.error_code : ''}</small></span>
        {batchId && item.status === 'failed' && <button type="button" className="workspace-button secondary" disabled={busy} onClick={() => retry.mutate([item.id])}>重试此项</button>}
      </li>)}</ul>
    </section>}
    <footer className="workspace-modal-actions"><button type="button" className="workspace-button secondary" disabled={busy} onClick={onClose}>关闭</button>
      {!batchId && preview.data && <button type="button" className="workspace-button" disabled={busy || !selected.length} onClick={() => confirm.mutate()}>确认导入 {selected.length} 项</button>}
    </footer>
  </WorkspaceModal>
}
