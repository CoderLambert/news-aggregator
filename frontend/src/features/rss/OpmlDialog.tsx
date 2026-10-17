import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import WorkspaceModal from '@/components/workspace/WorkspaceModal'
import { workspaceRequest, workspaceError } from '@/services/workspaceApi'
import type { ChannelGroup } from '@/types/channels'

interface ImportItem { id: string; title: string; feed_url: string; groups: string[]; status: string; error_code: string; operation_id: string | null }
interface ImportBatch { id: string; status: string; preview_token?: string; items: ImportItem[]; groups: string[] }
interface ConfirmRequest { preview_token: string; selected_ids: string[]; group_map: Record<string, number | { create: string } | null> }
interface RetryRequest { batchId: string; selected_ids: string[] }
interface OpmlDialogProps { viewer: number; groups: ChannelGroup[]; onClose: () => void }
const statusText: Record<string, string> = { preview: '待选择', invalid: '无效地址', pending: '等待处理', queued: '正在连接', succeeded: '已连接', failed: '处理失败' }
const validBatchId = (value: string) => /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(value)
const batchKey = (viewer: number, id: string | null) => ['private', 'rss-import', viewer, id] as const

export default function OpmlDialog(props: OpmlDialogProps) {
  return <OpmlSession key={props.viewer} {...props} />
}

function OpmlSession({ viewer, groups, onClose }: OpmlDialogProps) {
  const client = useQueryClient()
  const lifetime = useRef<AbortController | null>(null)
  useEffect(() => {
    const controller = new AbortController()
    lifetime.current = controller
    return () => { controller.abort(); lifetime.current = null }
  }, [])
  const [file, setFile] = useState<File | null>(null)
  const [selected, setSelected] = useState<string[]>([])
  const [groupMap, setGroupMap] = useState<Record<string, string>>({})
  const [batchId, setBatchId] = useState<string | null>(null)
  const [resumeId, setResumeId] = useState('')
  const invalidateSubscriptions = () => {
    void client.invalidateQueries({ queryKey: ['channels'] })
    void client.invalidateQueries({ queryKey: ['workspace'] })
    void client.invalidateQueries({ queryKey: ['private', 'rss-subscriptions', viewer] })
  }
  const preview = useMutation({ retry: false, mutationFn: async (upload: File) => {
    if (upload.size > 1024 * 1024) throw new Error('文件须小于1MiB。')
    const body = new FormData(); body.append('file', upload)
    return workspaceRequest<ImportBatch>('/me/rss-imports/preview/', { method: 'POST', body, viewer, signal: lifetime.current?.signal })
  }, onSuccess: batch => {
    if (!lifetime.current) return
    setSelected(batch.items.filter(item => item.status !== 'invalid').map(item => item.id))
    setGroupMap({})
  } })
  const confirm = useMutation({ retry: false, mutationFn: (body: ConfirmRequest) => workspaceRequest<ImportBatch>('/me/rss-imports/confirm/', {
    method: 'POST', viewer, body, signal: lifetime.current?.signal,
  }), onSuccess: batch => {
    if (!lifetime.current) return
    // Preserve the confirmed record even if the first progress GET fails.
    client.setQueryData(batchKey(viewer, batch.id), batch)
    setBatchId(batch.id)
    invalidateSubscriptions()
  } })
  const progress = useQuery({ queryKey: batchKey(viewer, batchId), enabled: !!batchId,
    retry: false, refetchOnWindowFocus: false, refetchOnReconnect: false, refetchOnMount: 'always',
    queryFn: ({ signal }) => workspaceRequest<ImportBatch>(`/me/rss-imports/${batchId}/`, { signal }),
    refetchInterval: query => !query.state.error && query.state.data?.items.some(item => ['pending', 'queued'].includes(item.status)) ? 2000 : false,
  })
  const retry = useMutation({ retry: false, mutationFn: ({ batchId: id, selected_ids }: RetryRequest) => workspaceRequest<ImportBatch>(`/me/rss-imports/${id}/`, {
    method: 'POST', viewer, body: { selected_ids }, signal: lifetime.current?.signal,
  }), onSuccess: batch => {
    if (!lifetime.current) return
    client.setQueryData(batchKey(viewer, batch.id), batch)
    invalidateSubscriptions()
    void progress.refetch({ cancelRefetch: false })
  } })
  const busy = preview.isPending || confirm.isPending || retry.isPending
  const batch = batchId ? progress.data : preview.data
  const resetPreview = () => {
    preview.reset(); confirm.reset(); retry.reset()
    setSelected([]); setGroupMap({}); setBatchId(null)
  }
  const reloadProgress = async () => {
    const result = await progress.refetch({ cancelRefetch: false })
    // A lost retry response may already have queued work. Reconcile with GET
    // before offering another POST, never blindly replay a failed retry.
    if (lifetime.current && result.isSuccess) retry.reset()
  }
  const submitConfirm = () => {
    if (busy || confirm.isError || !preview.data?.preview_token || !selected.length) return
    confirm.mutate({ preview_token: preview.data.preview_token, selected_ids: [...selected],
      group_map: Object.fromEntries(Object.entries(groupMap).map(([label, value]) => [label, value === 'new' ? { create: label.slice(0, 40) } : value ? Number(value) : null])),
    })
  }
  return <WorkspaceModal title="导入与导出订阅" onClose={onClose} busy={busy}>
    <p className="workspace-muted">上传 OPML 文件，先检查订阅与分组，再确认导入。最多500个订阅，文件不超过1MiB。</p>
    <form className="workspace-inline-form" onSubmit={event => {
      event.preventDefault()
      if (busy || !file || file.size > 1024 * 1024) return
      resetPreview(); preview.mutate(file)
    }}>
      <label>OPML 文件<input type="file" accept=".opml,.xml,text/xml,application/xml" disabled={busy} onChange={event => {
        if (busy) return
        setFile(event.target.files?.[0] ?? null); resetPreview()
      }} /></label>
      <button type="submit" className="workspace-button" disabled={busy || !file || file.size > 1024 * 1024}>预览文件</button>
    </form>
    {file && file.size > 1024 * 1024 && <p role="alert">文件超过1MiB，请缩小后重试。</p>}
    {preview.isPending && <p role="status">正在预览文件，不会订阅或抓取来源…</p>}
    {preview.error && <p role="alert" className="workspace-error">文件预览失败：{workspaceError(preview.error)} 可点击「预览文件」重试。</p>}
    <p><a className="workspace-link" href="/api/me/rss-subscriptions/export/" download="subscriptions.opml">导出我的订阅</a></p>
    <form className="workspace-inline-form" onSubmit={event => {
      event.preventDefault()
      const id = resumeId.trim()
      if (busy || !validBatchId(id) || (id === batchId && progress.isFetching)) return
      preview.reset(); confirm.reset(); retry.reset(); setSelected([]); setGroupMap({})
      if (id === batchId) void reloadProgress()
      else setBatchId(id)
    }}>
      <label>恢复导入记录<input value={resumeId} disabled={busy} placeholder="导入记录编号" onChange={event => setResumeId(event.target.value)} /></label>
      <button className="workspace-button secondary" disabled={busy || (progress.isFetching && resumeId.trim() === batchId) || !validBatchId(resumeId.trim())}>查看进度</button>
    </form>
    {batchId && <p role="status">导入记录：<code>{batchId}</code>。关闭窗口后仍会继续，可用此编号恢复查看。</p>}
    {batchId && progress.isPending && <p role="status">正在读取导入进度…</p>}
    {confirm.error && !batchId && <p role="alert" className="workspace-error">导入确认结果未确认：{workspaceError(confirm.error)} 重试会保留原预览、选择和分组；修改选择请重新预览文件。
      <button type="button" className="workspace-link" disabled={busy} onClick={() => { if (confirm.variables) confirm.mutate(confirm.variables) }}>重试确认导入</button>
    </p>}
    {batchId && (progress.error || retry.error) && <p role="alert" className="workspace-error">
      {retry.error ? '重试提交结果未确认，请先重新读取进度，避免重复提交。' : '导入进度读取失败，后台任务不受影响。'}
      {workspaceError(progress.error ?? retry.error)}
      <button type="button" className="workspace-link" disabled={busy || progress.isFetching} onClick={() => { void reloadProgress() }}>重新读取导入进度</button>
    </p>}
    {batch && <section aria-label="导入预览与进度">
      {!batchId && batch.groups.map(label => <label className="workspace-resolved-choice" key={label}>{label}
        <select aria-label={label + '映射分组'} disabled={busy || confirm.isError} value={groupMap[label] ?? ''} onChange={event => setGroupMap(current => ({ ...current, [label]: event.target.value }))}>
          <option value="">不加入分组</option><option value="new">创建「{label.slice(0, 40)}」</option>{groups.map(group => <option key={group.id} value={group.id}>{group.name}</option>)}
        </select></label>)}
      <ul className="workspace-resolved">{batch.items.map(item => <li key={item.id} className="workspace-resolved-choice">
        {!batchId && <input type="checkbox" aria-label={'导入 ' + (item.title || item.feed_url)} disabled={busy || confirm.isError || item.status === 'invalid'} checked={selected.includes(item.id)} onChange={event => setSelected(current => event.target.checked ? [...current, item.id] : current.filter(id => id !== item.id))} />}
        <span><strong>{item.title || item.feed_url}</strong><small className="break-all">{item.feed_url}</small><small>{batchId && item.status === 'preview' ? '未选择，未导入' : statusText[item.status] ?? '等待确认'}{item.error_code ? ' · ' + item.error_code : ''}</small></span>
        {batchId && item.status === 'failed' && <button type="button" className="workspace-button secondary" disabled={busy || progress.isFetching || progress.isError || retry.isError} onClick={() => retry.mutate({ batchId, selected_ids: [item.id] })}>重试此项</button>}
      </li>)}</ul>
    </section>}
    <footer className="workspace-modal-actions"><button type="button" className="workspace-button secondary" disabled={busy} onClick={onClose}>关闭</button>
      {!batchId && preview.data && <button type="button" className="workspace-button" disabled={busy || confirm.isError || !selected.length} onClick={submitConfirm}>确认导入 {selected.length} 项</button>}
    </footer>
  </WorkspaceModal>
}
