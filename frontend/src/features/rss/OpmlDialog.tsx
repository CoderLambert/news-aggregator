import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import WorkspaceModal from '@/components/workspace/WorkspaceModal'
import { workspaceRequest, workspaceError } from '@/services/workspaceApi'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { NativeSelect } from '@/components/ui/native-select'
import OpmlHistory from './OpmlHistory'
import { batchKey, importStatusText as statusText, importOutcomeText, invalidateImportEffects, type ImportBatch } from './opmlTypes'
import type { ChannelGroup } from '@/types/channels'

interface ConfirmRequest { preview_token: string; selected_ids: string[]; group_map: Record<string, number | { create: string } | null> }
interface RetryRequest { batchId: string; selected_ids: string[] }
interface OpmlDialogProps { viewer: number; groups: ChannelGroup[]; onClose: () => void }
const validBatchId = (value: string) => /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(value)

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
  const [showHistory, setShowHistory] = useState(false)
  const [historyBusy, setHistoryBusy] = useState(false)
  const [cancelOpen, setCancelOpen] = useState(false)
  const invalidateSubscriptions = () => invalidateImportEffects(client, viewer)
  const preview = useMutation({ retry: false, mutationFn: async (upload: File) => {
    if (upload.size > 1024 * 1024) throw new Error('文件须小于1MiB。')
    const body = new FormData(); body.append('file', upload)
    return workspaceRequest<ImportBatch>('/me/rss-imports/preview/', { method: 'POST', body, viewer, signal: lifetime.current?.signal })
  }, onSuccess: batch => {
    if (!lifetime.current) return
    setSelected(batch.items.filter(item => item.status !== 'invalid' && item.outcome !== 'already_subscribed').map(item => item.id))
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
    queryFn: ({ signal }) => workspaceRequest<ImportBatch>(`/me/rss-imports/${batchId}/`, { viewer, signal }),
    refetchInterval: query => !query.state.error && !query.state.data?.paused && !query.state.data?.cancelled_at && query.state.data?.items.some(item => ['pending', 'queued'].includes(item.status)) ? 2000 : false,
  })
  const progressFingerprint = progress.data?.items.map(item => `${item.id}:${item.status}:${item.subscription_id ?? ''}`).join('|')
  useEffect(() => {
    if (batchId && progressFingerprint !== undefined) invalidateImportEffects(client, viewer)
  }, [batchId, progressFingerprint, client, viewer])
  const retry = useMutation({ retry: false, mutationFn: ({ batchId: id, selected_ids }: RetryRequest) => workspaceRequest<ImportBatch>(`/me/rss-imports/${id}/`, {
    method: 'POST', viewer, body: { selected_ids }, signal: lifetime.current?.signal,
  }), onSuccess: batch => {
    if (!lifetime.current) return
    client.setQueryData(batchKey(viewer, batch.id), batch)
    invalidateSubscriptions()
    void progress.refetch({ cancelRefetch: false })
  } })
  const control = useMutation({ retry: false, mutationFn: (action: 'pause' | 'resume' | 'cancel') => workspaceRequest<ImportBatch>(`/me/rss-imports/${batchId}/`, {
    method: 'PATCH', viewer, body: { action }, signal: lifetime.current?.signal,
  }), onSuccess: batch => {
    if (!lifetime.current) return
    client.setQueryData(batchKey(viewer, batch.id), batch)
    invalidateSubscriptions()
    setCancelOpen(false)
  } })
  const busy = preview.isPending || confirm.isPending || retry.isPending || control.isPending || historyBusy
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
  const validItems = preview.data?.items.filter(item => item.status !== 'invalid' && item.outcome !== 'already_subscribed') ?? []
  return <WorkspaceModal title="OPML 批量导入" onClose={onClose} busy={busy}>
    <div role="group" aria-label="OPML 管理" className="mb-4 flex flex-wrap gap-2">
      <Button type="button" variant={showHistory ? 'outline' : 'default'} aria-pressed={!showHistory} disabled={busy} onClick={() => setShowHistory(false)}>导入文件</Button>
      <Button type="button" variant={showHistory ? 'default' : 'outline'} aria-pressed={showHistory} disabled={busy} onClick={() => setShowHistory(true)}>导入历史</Button>
    </div>
    {showHistory ? <OpmlHistory viewer={viewer} onBusyChange={setHistoryBusy} onOpen={id => {
      preview.reset(); confirm.reset(); retry.reset(); setSelected([]); setGroupMap({}); setBatchId(id); setResumeId(id); setShowHistory(false)
    }} /> : <>
    <p className="workspace-muted">上传 OPML 文件，先检查订阅与分组，再确认导入。最多500个订阅，文件不超过1MiB。文件会保存到仅自己可见的导入历史。</p>
    <form className="workspace-inline-form" onSubmit={event => {
      event.preventDefault()
      if (busy || !file || file.size > 1024 * 1024) return
      resetPreview(); preview.mutate(file)
    }}>
      <label>OPML 文件<Input type="file" accept=".opml,.xml,text/xml,application/xml" disabled={busy} onChange={event => {
        if (busy) return
        setFile(event.target.files?.[0] ?? null); resetPreview()
      }} /></label>
      <Button type="submit" disabled={busy || !file || file.size > 1024 * 1024}>预览文件</Button>
    </form>
    {file && file.size > 1024 * 1024 && <p role="alert">文件超过1MiB，请缩小后重试。</p>}
    {preview.isPending && <p role="status">正在预览文件，不会订阅或抓取来源…</p>}
    {preview.error && <p role="alert" className="workspace-error">文件预览失败：{workspaceError(preview.error)} 可点击「预览文件」重试。</p>}
    {!batchId && preview.data && validBatchId(preview.data.id) &&
      <p className="workspace-caption">本次预览记录编号：<code>{preview.data.id}</code>。确认结果不明确时，可按此编号只读核对。</p>}
    <p><a className="workspace-link" href="/api/me/rss-subscriptions/export/" download="subscriptions.opml">导出我的订阅</a></p>
    <form className="workspace-inline-form" onSubmit={event => {
      event.preventDefault()
      const id = resumeId.trim()
      if (busy || !validBatchId(id) || (id === batchId && progress.isFetching)) return
      preview.reset(); confirm.reset(); retry.reset(); setSelected([]); setGroupMap({})
      if (id === batchId) void reloadProgress()
      else setBatchId(id)
    }}>
      <label>恢复导入记录<Input value={resumeId} disabled={busy} placeholder="导入记录编号" onChange={event => setResumeId(event.target.value)} /></label>
      <Button variant="outline" disabled={busy || (progress.isFetching && resumeId.trim() === batchId) || !validBatchId(resumeId.trim())}>查看进度</Button>
    </form>
    {batchId && <p role="status">导入记录：<code>{batchId}</code>。{batch?.status === 'removed' ? '此批次已移除，原文件保留在导入历史。' : batch?.status === 'preview' ? '仅完成预览，尚未开始导入。' : batch?.cancelled_at ? '剩余任务已取消，已建立的订阅保留。' : batch?.paused ? '此批次已暂停，点击继续后自动接入。' : '关闭窗口后仍会继续，有处理空位时自动接入，可在历史恢复查看。'}</p>}
    {batchId && progress.isPending && <p role="status">正在读取导入进度…</p>}
    {batchId && batch && !batch.removed_at && !batch.cancelled_at && batch.status !== 'preview' && batch.items.some(item => ['pending', 'queued', 'failed'].includes(item.status)) && <div className="flex flex-wrap gap-2">
      <Button type="button" variant="outline" disabled={busy || progress.isFetching || control.isError} onClick={() => control.mutate(batch.paused ? 'resume' : 'pause')}>{batch.paused ? '继续自动接入' : '暂停接入'}</Button>
      <Button type="button" variant="outline" disabled={busy || control.isError} onClick={() => setCancelOpen(true)}>取消剩余任务</Button>
    </div>}
    {control.error && <p role="alert">操作结果未确认：{workspaceError(control.error)}
      <Button type="button" variant="link" disabled={busy || progress.isFetching} onClick={() => { void reloadProgress().then(() => control.reset()) }}>重新读取进度</Button>
    </p>}
    {cancelOpen && <WorkspaceModal title="取消剩余导入任务？" onClose={() => setCancelOpen(false)} busy={busy}>
      <p>只取消本批次尚未完成的任务，保留已建立的订阅、原文件和历史记录。其他用户的接入不受影响。</p>
      {control.error && <p role="alert">操作结果未确认，请关闭此窗口后重新读取进度。</p>}
      <footer className="workspace-modal-actions"><Button type="button" variant="outline" disabled={busy} onClick={() => setCancelOpen(false)}>保留任务</Button><Button type="button" variant="destructive" disabled={busy || control.isError} onClick={() => control.mutate('cancel')}>确认取消剩余</Button></footer>
    </WorkspaceModal>}

    {confirm.error && !batchId && <p role="alert" className="workspace-error">导入确认结果未确认：{workspaceError(confirm.error)} 请先核对导入记录，重试将沿用本次的频道选择和分组。
      {preview.data && validBatchId(preview.data.id) &&
        <Button type="button" variant="outline" disabled={busy}
          onClick={() => { const id = preview.data?.id; if (id && validBatchId(id)) { setResumeId(id); setBatchId(id) } }}>核对确认结果</Button>}
      <Button type="button" variant="link" disabled={busy} onClick={() => { if (confirm.variables) confirm.mutate(confirm.variables) }}>重试确认导入</Button>
    </p>}
    {batchId && batch?.status === 'preview' && preview.data?.id !== batchId && <p className="workspace-muted">此历史记录尚未确认导入。请从历史下载原文件，重新预览后选择频道并确认。</p>}
    {batchId && batch?.status === 'preview' && preview.data?.id === batchId &&
      <p role="status">此记录仍处于预览状态，确认可能未提交。
        <Button type="button" variant="outline" disabled={busy}
          onClick={() => { setBatchId(null); confirm.reset() }}>返回预览继续确认</Button>
      </p>}
    {batchId && (progress.error || retry.error) && <p role="alert" className="workspace-error">
      {retry.error ? '重试提交结果未确认，请先重新读取进度，避免重复提交。' : '导入进度读取失败，后台任务不受影响。'}
      {workspaceError(progress.error ?? retry.error)}
      <Button type="button" variant="link" disabled={busy || progress.isFetching} onClick={() => { void reloadProgress() }}>重新读取导入进度</Button>
    </p>}
    {batch && <section aria-label="导入预览与进度" className="space-y-3">
      {!batchId ? <div className="space-y-2">
        <p role="status">共 {batch.items.length} 项 · 可导入 {validItems.length} 项 · 无效 {batch.items.length - validItems.length} 项 · 重复合并 {batch.duplicate_count ?? 0} 项 · 已订阅 {batch.items.filter(item => item.outcome === 'already_subscribed').length} 项 · 已选 {selected.length} 项</p>
        <Button type="button" variant="outline" disabled={busy || confirm.isError || !validItems.length} onClick={() => setSelected(selected.length === validItems.length ? [] : validItems.map(item => item.id))}>{selected.length === validItems.length && validItems.length ? '取消全选' : '全选有效频道'}</Button>
      </div> : <p role="status" aria-live="polite">{batch.status === 'removed' ? `本批次已移除 ${batch.removed_count} 个新增订阅` : `已订阅/接入 ${batch.items.filter(item => item.status === 'succeeded').length} · 失败 ${batch.items.filter(item => item.status === 'failed').length} · 处理中 ${batch.items.filter(item => ['pending', 'queued'].includes(item.status)).length}`}</p>}
      {!batchId && batch.groups.map(label => <label className="workspace-resolved-choice" key={label}>{label}
        <NativeSelect aria-label={label + '映射分组'} disabled={busy || confirm.isError} value={groupMap[label] ?? ''} onChange={event => setGroupMap(current => ({ ...current, [label]: event.target.value }))}>
          <option value="">不加入分组</option><option value="new">创建「{label.slice(0, 40)}」</option>{groups.map(group => <option key={group.id} value={group.id}>{group.name}</option>)}
        </NativeSelect></label>)}
      <ul className="workspace-resolved max-h-[40vh] overflow-y-auto overscroll-contain">{batch.items.map(item => <li key={item.id} className="workspace-resolved-choice">
        {!batchId && <Input className="size-4 shrink-0 accent-primary shadow-none" type="checkbox" aria-label={'导入 ' + (item.title || item.feed_url)} disabled={busy || confirm.isError || item.status === 'invalid' || item.outcome === 'already_subscribed'} checked={selected.includes(item.id)} onChange={event => setSelected(current => event.target.checked ? [...current, item.id] : current.filter(id => id !== item.id))} />}
        <span><strong>{item.title || item.feed_url}</strong><small className="break-all">{item.feed_url}</small><small>{batchId && item.status === 'preview' ? '未选择，未导入' : (item.status === 'succeeded' && item.outcome !== 'already_subscribed' ? '已接入' : importOutcomeText[item.outcome ?? ''] ?? statusText[item.status] ?? '等待确认')}{item.error_code ? ' · ' + (item.error_code === 'throttled' ? (item.status === 'pending' ? '连接名额暂满，等待自动继续' : '连接暂受限，请稍后重试') : item.error_code === 'subscription_limit' ? '已达到订阅数量上限' : item.error_code) : ''}</small>{!!item.duplicate_count && <small>文件内已合并 {item.duplicate_count} 个重复条目</small>}{item.next_attempt && <small>下次自动处理：{new Date(item.next_attempt).toLocaleTimeString('zh-CN')}</small>}</span>
        {batchId && item.status === 'failed' && (item.can_retry ?? true) && <Button type="button" variant="outline" disabled={busy || progress.isFetching || progress.isError || retry.isError} onClick={() => retry.mutate({ batchId, selected_ids: [item.id] })}>重试此项</Button>}
      </li>)}</ul>
    </section>}
    </>}
    <footer className="workspace-modal-actions"><Button type="button" variant="outline" disabled={busy} onClick={onClose}>关闭</Button>
      {!showHistory && !batchId && preview.data && <Button type="button" disabled={busy || confirm.isError || !selected.length} onClick={submitConfirm}>确认导入 {selected.length} 项</Button>}
    </footer>
  </WorkspaceModal>
}
