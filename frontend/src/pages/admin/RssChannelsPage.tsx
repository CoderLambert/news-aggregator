import { useEffect, useId, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSearchParams, useNavigate } from 'react-router-dom'
import { useAuth } from '@/context/AuthContext'
import { useRssReviewGuard } from '@/features/rss/useRssReviewGuard'
import RecommendFeedDialog from '@/features/rss/RecommendFeedDialog'
import AdminLayout from '@/components/admin/AdminLayout'
import { workspaceError, workspaceRequest } from '@/services/workspaceApi'
import { actionReasons, fetchVerificationDetail, fetchVerificationList, phaseLabels, rssAdminKey, verificationError, verificationLabels } from '@/services/rssAdminApi'
import type { VerificationBatch, VerificationFeed, VerificationSource } from '@/services/rssAdminApi'
import './rssChannels.css'

const dateLabel = (value: string | null) => value ? new Date(value).toLocaleString('zh-CN') : '尚未核验'
const poll = () => document.hidden ? false as const : 3000
const remaining = (feed: VerificationFeed, now: number) => Math.max(0, Math.ceil(((feed.cooldown_until ? Date.parse(feed.cooldown_until) : 0) - now) / 1000))
function allowed(feed: VerificationFeed, now: number): boolean {
  return !remaining(feed, now) && (feed.can_verify || feed.action_reason === 'cooldown')
}
function RecoverButton({ source, now, busy, submit }: { source: VerificationSource; now: number; busy: boolean; submit: (rows: VerificationSource[]) => void }) {
  const seconds = Math.max(0, ...source.feeds.map(f => remaining(f, now)))
  const canVerify = source.feeds.some(f => allowed(f, now))
  const reason = source.feeds.find(f => f.action_reason)?.action_reason
  return <span className="rss-action"><button type="button" className="workspace-button secondary" disabled={busy || !canVerify || seconds > 0}
    onClick={() => submit([source])}>{seconds > 0 ? `${seconds} 秒后可核验` : '核验并恢复'}</button>
    {!seconds && !canVerify && <small>{actionReasons[reason ?? ''] ?? '当前频道不满足恢复条件。'}</small>}</span>
}
function VerificationDetails({ sourceId, viewer, authority, now, busy, submit, close }: {
  sourceId: number; viewer: number; authority: number; now: number; busy: boolean; submit: (rows: VerificationSource[]) => void; close: () => void
}) {
  const dialog = useRef<HTMLDialogElement>(null)
  const heading = useId()
  const detail = useQuery({ queryKey: [...rssAdminKey(viewer), authority, 'detail', sourceId],
    queryFn: ({ signal }) => fetchVerificationDetail(sourceId, signal), refetchInterval: poll })
  useEffect(() => {
    const previous = document.activeElement
    const node = dialog.current
    node?.showModal()
    return () => { node?.close(); if (previous instanceof HTMLElement && previous.isConnected) previous.focus() }
  }, [])
  return <dialog ref={dialog} className="rss-verification-drawer" aria-labelledby={heading} onCancel={e => { e.preventDefault(); close() }}>
    <header><h2 id={heading}>频道核验详情</h2><button type="button" className="workspace-button secondary" aria-label="关闭频道核验详情" onClick={close}>关闭</button></header>
    {detail.isPending && <p role="status">正在读取核验记录…</p>}
    {detail.error && <p role="alert">{workspaceError(detail.error)}<button type="button" onClick={() => void detail.refetch()}>重试</button></p>}
    {detail.data && <><h3>{detail.data.name}</h3><p>{verificationLabels[detail.data.status]} · {detail.data.can_subscribe ? '已开放订阅' : '连接确认后自动开放订阅'}</p>
      <RecoverButton source={detail.data} now={now} busy={busy} submit={submit} />
      {detail.data.feeds.map(feed => <section key={feed.id} className="rss-detail-feed"><p className="rss-feed-url">{feed.feed_url}</p>
        {feed.effective_feed_url && <p className="rss-feed-url">引擎确认的 RSS 地址：{feed.effective_feed_url}</p>}
        <p>{phaseLabels[feed.execution_phase] ?? '等待执行'}</p>
        {feed.recovery_requires_boundary && <p className="workspace-muted">核验会先查找已有连接。缺失连接且旧请求结果不明时，需要管理员确认旧请求已经结束，才能安全恢复。</p>}
        {feed.error_code && <p>{verificationError(feed.error_code)}</p>}
        <h4>核验记录</h4>{!feed.history?.length && <p>暂无核验记录。</p>}
        <ol className="rss-history">{feed.history?.map(record => <li key={record.id}>
          <strong>{phaseLabels[record.phase] ?? '等待执行'}</strong><p>{dateLabel(record.updated_at)} · 尝试 {record.attempts} 次</p>
          {record.error_code && <p>{verificationError(record.error_code)} <code>{record.error_code}</code></p>}
          {record.resolved_at && <p>已解除阻塞：{record.resolution === 'engine_restart' ? '已确认引擎重启边界' : '已确认唯一连接'} · {dateLabel(record.resolved_at)}</p>}
          {record.recovery_of && <small>关联原始操作：{record.recovery_of}</small>}
        </li>)}</ol></section>)}
    </>}
  </dialog>
}

function VerificationSession({ viewer, authority }: { viewer: number; authority: number }) {
  const [adding, setAdding] = useState(false)
  const { user } = useAuth()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const queryClient = useQueryClient()
  const [searchDraft, setSearchDraft] = useState({ base: params.get('q') ?? '', value: params.get('q') ?? '' })
  const search = searchDraft.base === (params.get('q') ?? '') ? searchDraft.value : (params.get('q') ?? '')
  const mounted = useRef(true)
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  const [selected, setSelected] = useState<number[]>([])
  const [now, setNow] = useState(Date.now)
  const idempotency = useRef<{ fingerprint: string; key: string } | null>(null)
  const status = params.get('status') ?? 'pending'
  const page = Math.max(1, Number(params.get('page')) || 1)
  const pageSize = params.get('page_size') === '50' ? 50 : 25
  const sourceId = Number(params.get('source')) || null
  const batchId = params.get('batch')
  const q = params.get('q') ?? ''
  const searchParams = new URLSearchParams({ q, status, page: String(page), page_size: String(pageSize) }).toString()
  const list = useQuery({ queryKey: [...rssAdminKey(viewer), authority, 'list', searchParams], queryFn: ({ signal }) => fetchVerificationList(searchParams, signal), refetchInterval: poll })
  const batch = useQuery({ queryKey: [...rssAdminKey(viewer), authority, 'batch', batchId], enabled: !!batchId,
    queryFn: ({ signal }) => workspaceRequest<VerificationBatch>(`/admin/rss/verification-batches/${batchId}/`, { signal }),
    refetchInterval: query => query.state.data?.done ? false : poll() })
  useEffect(() => {
    if (batch.data?.done) void queryClient.invalidateQueries({ queryKey: ['workspace'] })
  }, [batch.data?.done, queryClient])
  const update = (changes: Record<string, string | null>, resetPage = true) => {
    const next = new URLSearchParams(params)
    for (const [key, value] of Object.entries(changes)) { if (value === null) next.delete(key); else next.set(key, value) }
    if (resetPage) next.set('page', '1')
    setSelected([])
    setParams(next)
  }
  const mutation = useMutation({ retry: false,
    mutationFn: ({ rows, key }: { rows: VerificationSource[]; key: string }) => workspaceRequest<VerificationBatch>('/admin/rss/verification-batches/', {
      method: 'POST', viewer, idempotencyKey: key, body: { action: 'verify_and_recover', targets: rows.map(s => ({ source_id: s.source_id, expected_versions: s.expected_versions })) },
    }),
    onSuccess: result => {
      if (!mounted.current) return
      queryClient.setQueryData([...rssAdminKey(viewer), authority, 'batch', result.id], result)
      update({ batch: result.id }, false)
      void queryClient.invalidateQueries({ queryKey: rssAdminKey(viewer) })
      void queryClient.invalidateQueries({ queryKey: ['workspace'] })
    },
  })
  const submit = (rows: VerificationSource[]) => {
    const fingerprint = JSON.stringify(rows.map(s => [s.source_id, s.expected_versions]))
    if (idempotency.current?.fingerprint !== fingerprint || mutation.isSuccess) idempotency.current = { fingerprint, key: crypto.randomUUID() }
    mutation.mutate({ rows, key: idempotency.current!.key })
  }
  useEffect(() => { const interval = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(interval) }, [])
  // Server time anchors countdowns even if the browser clock differs.
  const clock = list.data ? Date.parse(list.data.server_time) + now - list.dataUpdatedAt : now
  const rows = list.data?.results ?? []
  const eligible = rows.filter(s => s.feeds.some(f => allowed(f, clock)))
  const chosen = eligible.filter(s => selected.includes(s.source_id))
  const denied = useRssReviewGuard(list.error, mutation.error, batch.error)
  if (denied) return <AdminLayout><p role="alert">审核权限已改变，正在重新确认账号权限。</p></AdminLayout>
  return <AdminLayout><section className="rss-channels" aria-labelledby="rss-channel-heading">
    <header className="rss-page-heading"><div><h1 id="rss-channel-heading">频道核验</h1>{user?.isSuperuser && <button className="workspace-button" onClick={() => setAdding(true)}>新增公共频道</button>}<p>核验连接并恢复缺失频道，成功后自动开放订阅。</p></div>
      <button type="button" className="workspace-button secondary" onClick={() => void list.refetch()} disabled={list.isFetching}>刷新列表</button></header>
    <nav className="rss-counts" aria-label="核验状态分类">{['pending', 'verifying', 'passed', 'all'].map(s => <button type="button" key={s}
      aria-pressed={status === s} onClick={() => update({ status: s })}><span>{verificationLabels[s]}</span><strong>{list.data?.counts[s] ?? '—'}</strong></button>)}</nav>
    <div className="rss-filters"><form role="search" onSubmit={e => { e.preventDefault(); update({ q: search.trim() || null }) }}>
      <label>搜索频道名称或 RSS 地址<input value={search} onChange={e => setSearchDraft({ base: q, value: e.target.value })} maxLength={200} placeholder="频道名称或 https://…/feed" /></label><button className="workspace-button secondary">搜索</button></form>
      <label>状态筛选<select value={status} onChange={e => update({ status: e.target.value })}>{['pending', 'unverified', 'verifying', 'passed', 'failed', 'unknown', 'paused', 'all'].map(s => <option key={s} value={s}>{verificationLabels[s]}</option>)}</select></label>
      <label>每页条数<select value={pageSize} onChange={e => update({ page_size: e.target.value })}><option value="25">25 条</option><option value="50">50 条</option></select></label></div>
    {list.isPending && <p role="status">正在加载频道…</p>}
    {list.error && <p role="alert">{workspaceError(list.error)}<button type="button" className="workspace-link" onClick={() => void list.refetch()}>重新加载</button></p>}
    {mutation.error && <p role="alert">{workspaceError(mutation.error)}</p>}
    {batchId && <section aria-label="批量核验进度" className="rss-batch" aria-live="polite"><h2>批量核验进度</h2>
      {batch.error ? <p role="alert">{workspaceError(batch.error)}<button type="button" onClick={() => void batch.refetch()}>重试查询</button></p> : <>
        <p>{batch.data?.done ? '本批核验已结束' : '后台正在核验，可刷新或稍后返回此页面。'}</p>
        <p>{Object.entries(batch.data?.counts ?? {}).map(([s, count]) => `${({ accepted: '已接受', running: '执行中', completed: '已完成', failed: '失败', skipped: '已跳过', unknown: '结果未知' } as Record<string, string>)[s] ?? s} ${count}`).join(' · ')}</p>
        <ul>{batch.data?.items.map((item, i) => <li key={item.binding_id ?? i}>{item.name ?? rows.find(s => s.source_id === item.source_id)?.name ?? `频道 ${item.source_id ?? ''}`}：{({ accepted: '已接受', running: '执行中', completed: '已完成', failed: '失败', skipped: '已跳过', unknown: '结果未知' } as Record<string, string>)[item.status]}{item.reason && ` · ${actionReasons[item.reason] ?? verificationError(item.reason)}`}</li>)}</ul>
      </>}
      <button type="button" className="workspace-link" onClick={() => update({ batch: null }, false)}>收起进度</button></section>}
    {!!rows.length && <div className="rss-selection"><label><input type="checkbox" aria-label="选择本页可核验频道" checked={eligible.length > 0 && chosen.length === eligible.length}
      disabled={!eligible.length || mutation.isPending} onChange={e => setSelected(e.target.checked ? eligible.map(s => s.source_id) : [])} />本页可核验频道</label>
      <button type="button" className="workspace-button" disabled={!chosen.length || mutation.isPending} onClick={() => submit(chosen)}>核验所选（{chosen.length} / 50）</button></div>}
    {list.data && !rows.length && <p className="workspace-empty" role="status">没有符合条件的频道。</p>}
    <ul className="rss-channel-list">{rows.map(source => <li key={source.source_id} className="rss-channel-row" onClick={e => {
      if (!(e.target as HTMLElement).closest('button, input, a, label')) update({ source: String(source.source_id) }, false)
    }}>
      <input type="checkbox" aria-label={'选择' + source.name} checked={chosen.some(s => s.source_id === source.source_id)} disabled={!eligible.includes(source) || mutation.isPending}
        onChange={e => setSelected(ids => e.target.checked ? [...ids, source.source_id].slice(0, 50) : ids.filter(id => id !== source.source_id))} />
      <div className="rss-channel-identity"><button type="button" className="workspace-link" aria-label={'查看' + source.name + '详情'} onClick={() => update({ source: String(source.source_id) }, false)}>{source.name}</button>
        {source.feeds.map(feed => <p key={feed.id} className="rss-feed-url">{feed.feed_url}</p>)}</div>
      <div><span className={'rss-status rss-status-' + source.status}>{verificationLabels[source.status]}</span>
        {source.feeds.map(feed => <p key={feed.id} className="workspace-caption">{verificationError(feed.error_code)}</p>)}</div>
      <div className="workspace-caption">最近核验{source.feeds.map(feed => <p key={feed.id}>{dateLabel(feed.checked_at)}</p>)}</div>
      <RecoverButton source={source} now={clock} busy={mutation.isPending} submit={submit} />
    </li>)}</ul>
    {list.data && <nav className="rss-pagination" aria-label="频道分页"><button type="button" className="workspace-button secondary" disabled={page <= 1} onClick={() => update({ page: String(page-1) }, false)}>上一页</button>
      <span>第 {page} / {Math.max(1, Math.ceil(list.data.count/pageSize))} 页 · {list.data.count} 个频道</span><button type="button" className="workspace-button secondary" disabled={page*pageSize >= list.data.count} onClick={() => update({ page: String(page+1) }, false)}>下一页</button></nav>}
    {sourceId && <VerificationDetails key={sourceId} sourceId={sourceId} viewer={viewer} authority={authority} now={clock} busy={mutation.isPending} submit={submit} close={() => update({ source: null }, false)} />}
    {adding && <RecommendFeedDialog viewer={viewer} onClose={() => setAdding(false)} onDone={() => { setAdding(false); navigate('/admin/rss/recommendations?status=all') }} />}
  </section></AdminLayout>
}
export default function RssChannelsPage() {
  const { user } = useAuth()
  const authority = user?.isSuperuser ? 0 : user?.rssCapabilities?.reviewerVersion
  return user && (user.isSuperuser || (user.rssCapabilities?.reviewPublicRss && authority != null))
    ? <VerificationSession key={`${user.id}:${authority}`} viewer={user.id} authority={authority ?? 0} /> : null
}
