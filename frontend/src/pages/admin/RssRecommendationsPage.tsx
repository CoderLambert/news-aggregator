import { useEffect, useId, useRef, useState } from 'react'
import { useSearchParams, Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { refreshRssViews } from '@/features/rss/queryRefresh'
import { useAuth } from '@/context/AuthContext'
import { useRssReviewGuard } from '@/features/rss/useRssReviewGuard'
import AdminLayout from '@/components/admin/AdminLayout'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import ReviewRecommendationsDialog from '@/features/rss/ReviewRecommendationsDialog'
import { decideRecommendation, fetchReviewCategories, fetchRecommendation, fetchRecommendations, recommendationLabels, rssReviewKey, verifyRecommendation } from '@/services/rssReviewApi'
import type { Recommendation } from '@/services/rssReviewApi'
import { workspaceError } from '@/services/workspaceApi'
import { verificationError } from '@/services/rssAdminApi'
import './rssChannels.css'

function Details({ id, viewer, epoch, close }: { id: string; viewer: number; epoch: number; close: () => void }) {
  const ref = useRef<HTMLDialogElement>(null); const heading = useId(); const client = useQueryClient()
  const [reason, setReason] = useState(''); const [name, setName] = useState(''); const [category, setCategory] = useState(''); const [language, setLanguage] = useState(''); const [now, setNow] = useState(Date.now)
  useEffect(() => { const timer = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(timer) }, [])
  const key = useRef(crypto.randomUUID())
  const detail = useQuery({ queryKey: [...rssReviewKey(viewer), epoch, 'recommendation', id], queryFn: ({ signal }) => fetchRecommendation(id, signal), retry: false, refetchInterval: () => document.hidden ? false : 3000 })
  useEffect(() => { const previous = document.activeElement; const node = ref.current; node?.showModal(); return () => { node?.close(); if (previous instanceof HTMLElement && previous.isConnected) previous.focus() } }, [])
  const refreshedDetail = useRef('')
  useEffect(() => {
    if (detail.data?.state === 'published' && refreshedDetail.current !== id) {
      refreshedDetail.current = id; void refreshRssViews(client, viewer)
    }
  }, [detail.data?.state, id, client, viewer])
  const categories = useQuery({ queryKey: [...rssReviewKey(viewer), 'categories'], queryFn: ({ signal }) => fetchReviewCategories(signal), retry: false, enabled: detail.data?.can_review === true })
  const action = useMutation({ retry: false, mutationFn: ({ row, action }: { row: Recommendation; action: string }) => action === 'verify'
    ? verifyRecommendation(viewer, id, row.version, key.current)
    : decideRecommendation(viewer, id, { action, expected_version: row.version, reason, ...(name.trim() ? { name: name.trim() } : {}), ...(category ? { category_id: Number(category) } : {}), ...(language ? { language } : {}) }, key.current),
    onSuccess: () => { key.current = crypto.randomUUID(); void client.invalidateQueries({ queryKey: rssReviewKey(viewer) }) } })
  const denied = useRssReviewGuard(detail.error, action.error)
  const row = denied ? undefined : detail.data
  const cooldown = row?.cooldown_until ? Math.max(0, Math.ceil((Date.parse(row.cooldown_until) - now) / 1000)) : 0
  return <dialog ref={ref} className="rss-verification-drawer" aria-labelledby={heading} onCancel={e => { e.preventDefault(); if (!action.isPending) close() }}><header><h2 id={heading}>公开推荐详情</h2><button className="workspace-button secondary" onClick={close} disabled={action.isPending}>关闭</button></header>
    {detail.isPending && <p role="status">正在读取推荐资料…</p>}{detail.error && <p role="alert">{workspaceError(detail.error)}<button onClick={() => void detail.refetch()}>重试</button></p>}
    {row && <><h3>{row.name}</h3><p className="rss-feed-url">{row.feed_url}</p><p>{recommendationLabels[row.state]}</p><p>连接状态：{row.connection_state === 'ready' ? '已连接' : row.connection_state === 'unknown' || row.connection_state === 'paused' ? '需要核对' : '等待连接'}</p><p>{row.scope_description}</p>{row.error_code && <p>{verificationError(row.error_code)}</p>}
      {row.notes?.map((note, i) => <p key={i}>推荐说明：{note.note || '未填写'}</p>)}
      {row.can_review ? <div className="rss-public-form"><label>公开名称<input value={name || row.name} maxLength={255} onChange={e => { key.current = crypto.randomUUID(); action.reset(); setName(e.target.value) }} disabled={action.isPending} /></label><label>分类<select value={category || String(row.category_id)} onChange={e => { key.current = crypto.randomUUID(); action.reset(); setCategory(e.target.value) }} disabled={action.isPending}><option value={row.category_id}>{row.category_name}</option>{categories.data?.filter(item => item.id !== row.category_id).map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><label>语言<select value={language || row.language} onChange={e => { key.current = crypto.randomUUID(); action.reset(); setLanguage(e.target.value) }} disabled={action.isPending}><option value="zh">中文</option><option value="en">英文</option><option value="other">其他</option></select></label><label>审核说明（驳回时必填）<textarea value={reason} maxLength={1000} onChange={e => { key.current = crypto.randomUUID(); action.reset(); setReason(e.target.value) }} disabled={action.isPending} /></label><div className="workspace-actions"><button className="workspace-button" disabled={action.isPending} onClick={() => action.mutate({ row, action: 'approve' })}>通过审核</button><button className="workspace-button secondary" disabled={action.isPending || !reason.trim()} onClick={() => action.mutate({ row, action: 'reject' })}>驳回推荐</button></div></div> : <p>当前状态或权限不允许审核。本人提交的推荐需要其他审核员处理。</p>}
      {row.can_verify && <button className="workspace-button secondary" disabled={action.isPending || cooldown > 0} onClick={() => action.mutate({ row, action: 'verify' })}>{cooldown > 0 ? `${cooldown} 秒后可核验` : '核验并恢复'}</button>}
      {row.reason && <p>审核说明：{row.reason}</p>}{row.public_source_id && <Link to={`/channels/${row.public_source_id}`}>查看公开频道</Link>}
      <h4>审核记录</h4><ol className="rss-history">{row.history?.map((event, i) => <li key={i}>{event.action === 'approve' || event.action === 'register' ? '通过' : '驳回'} · {new Date(event.created_at).toLocaleString('zh-CN')} · 版本 {event.candidate_version}{event.reason && <p>{event.reason}</p>}</li>)}</ol>
    </>}{action.error && <p role="alert">{workspaceError(action.error)}。请刷新核对当前权限和版本。</p>}
  </dialog>
}
export default function RssRecommendationsPage() {
  const { user } = useAuth()
  if (!user) return null
  return <ReviewSession key={`${user.id}:${user.rssCapabilities?.reviewerVersion ?? 0}`} viewer={user.id} epoch={user.rssCapabilities?.reviewerVersion ?? 0} />
}
function ReviewSession({ viewer, epoch }: { viewer: number; epoch: number }) {
  const [selected, setSelected] = useState<string[]>([])
  const [reviewing, setReviewing] = useState<Recommendation[] | null>(null)
  const [params, setParams] = useSearchParams(); const [search, setSearch] = useState(params.get('q') ?? '')
  const status = params.get('status') ?? 'pending'; const page = params.get('page') ?? '1'; const size = params.get('page_size') ?? '25'
  const query = new URLSearchParams({ q: params.get('q') ?? '', status, page, page_size: size }).toString()
  const list = useQuery({ queryKey: [...rssReviewKey(viewer), epoch, 'queue', query], queryFn: ({ signal }) => fetchRecommendations(query, signal), retry: false, refetchInterval: () => document.hidden ? false : 3000 })
  const client = useQueryClient()
  const published = useRef(new Map<string, string>())
  const observedQuery = useRef(query)
  useEffect(() => {
    if (!list.data) return
    if (observedQuery.current !== query) { published.current.clear(); observedQuery.current = query }
    let changed = false
    const seen = new Set(list.data.results.map(row => row.candidate_id))
    for (const id of published.current.keys()) { if (!seen.has(id)) { published.current.delete(id); changed = true } }
    for (const row of list.data.results) {
      if (row.state === 'published' && published.current.get(row.candidate_id) !== 'published') changed = true
      published.current.set(row.candidate_id, row.state)
    }
    if (changed) void refreshRssViews(client, viewer)
  }, [list.data, client, viewer, query])
  const denied = useRssReviewGuard(list.error)
  const eligible = (list.data?.results ?? []).filter(row => row.can_review && row.state === 'pending')
  const selectedRows = eligible.filter(row => selected.includes(row.candidate_id))
  if (denied) return <AdminLayout><p role="alert">审核权限已改变，正在重新确认账号权限。</p></AdminLayout>
  const change = (key: string, value: string | null) => { const next = new URLSearchParams(params); if (value === null) next.delete(key); else next.set(key, value); if (!['page', 'candidate'].includes(key)) { next.set('page', '1'); next.delete('candidate') } setParams(next) }
  return <AdminLayout><section className="rss-channel-verification"><header className="workspace-page-heading"><div><h1>公开频道审核</h1><p>人工审核与连接核验都通过后，频道才会开放公共订阅。</p></div></header>
    <nav className="rss-counts" aria-label="审核状态">{['pending', 'approved', 'published', 'all'].map(state => <button key={state} aria-pressed={status === state} onClick={() => change('status', state)}>{state === 'all' ? '全部' : recommendationLabels[state]} <strong>{state === 'all' ? Object.values(list.data?.counts ?? {}).reduce((a, b) => a + b, 0) : list.data?.counts?.[state] ?? '—'}</strong></button>)}</nav>
    <form role="search" className="rss-review-search" onSubmit={e => { e.preventDefault(); change('q', search.trim()) }}><label>搜索公开推荐<input value={search} maxLength={200} onChange={e => setSearch(e.target.value)} /></label><button className="workspace-button secondary">搜索</button><label>审核状态<select value={status} onChange={e => change('status', e.target.value)}><option value="all">全部</option>{Object.entries(recommendationLabels).map(([key, value]) => <option key={key} value={key}>{value}</option>)}</select></label><label>每页条数<select value={size} onChange={e => change('page_size', e.target.value)}><option value="25">25</option><option value="50">50</option></select></label></form>
    {list.isPending && <p role="status">正在读取推荐队列…</p>}{list.error && <p role="alert">{workspaceError(list.error)}<button onClick={() => void list.refetch()}>重新加载</button></p>}{list.data?.count === 0 && <p role="status">没有符合条件的公开推荐。</p>}
    {eligible.length > 0 && <div className="my-3 flex flex-wrap items-center gap-3">
      <Button variant="outline" onClick={() => setSelected(eligible.slice(0, 10).map(row => row.candidate_id))}>选择本页前 10 个可审核项</Button>
      <Button disabled={!selectedRows.length || selectedRows.length > 10 || list.isError} onClick={() => setReviewing(selectedRows)}>批量审核（{selectedRows.length}/10）</Button>
      <Button variant="ghost" onClick={() => setSelected([])}>清空选择</Button>
    </div>}
    {list.data?.results.map(row => <article key={row.candidate_id} className="rss-addition-row">
      {row.can_review && row.state === 'pending' && <Checkbox aria-label={`选择推荐 ${row.name}`} checked={selected.includes(row.candidate_id)} onChange={e => setSelected(current => e.target.checked ? [...current, row.candidate_id] : current.filter(id => id !== row.candidate_id))} />}
      <h2><button className="workspace-link" onClick={() => change('candidate', row.candidate_id)}>{row.name}</button></h2><p className="rss-feed-url">{row.feed_url}</p><p>{recommendationLabels[row.state]} · {row.category_name}</p>{row.error_code && <p>{verificationError(row.error_code)}</p>}</article>)}
    <nav className="rss-pagination" aria-label="推荐分页"><button disabled={Number(page) <= 1} onClick={() => change('page', String(Number(page) - 1))}>上一页</button><span>第 {page} 页 · 共 {list.data?.count ?? 0} 条</span><button disabled={!list.data || Number(page) * Number(size) >= list.data.count} onClick={() => change('page', String(Number(page) + 1))}>下一页</button></nav>
    {params.get('candidate') && <Details key={params.get('candidate')} id={params.get('candidate')!} viewer={viewer} epoch={epoch} close={() => change('candidate', null)} />}
    {reviewing && <ReviewRecommendationsDialog viewer={viewer} rows={reviewing} onClose={() => { setReviewing(null); setSelected([]) }} />}
  </section></AdminLayout>
}
