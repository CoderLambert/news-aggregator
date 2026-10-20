import { useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useAuth } from '@/context/AuthContext'
import { actOnAddition, additionLabels, changeRecommendation, fetchAdditions, fetchMyRecommendations, recommendationLabels, rssReviewKey } from '@/services/rssReviewApi'
import type { Addition, Recommendation } from '@/services/rssReviewApi'
import { refreshRssViews } from '@/features/rss/queryRefresh'
import { workspaceError } from '@/services/workspaceApi'
import { verificationError } from '@/services/rssAdminApi'
import RecommendFeedDialog from '@/features/rss/RecommendFeedDialog'
import '@/pages/admin/rssChannels.css'

export default function RssAdditionsPage() {
  const { user } = useAuth()
  return user ? <AdditionSession key={user.id} viewer={user.id} /> : <div className="workspace-page"><h1>添加记录</h1><p>请登录后查看自己的添加记录。</p></div>
}
function AdditionSession({ viewer }: { viewer: number }) {
  const [params, setParams] = useSearchParams(); const client = useQueryClient()
  const tab = params.get('tab') === 'recommendations' ? 'recommendations' : 'additions'
  const [now, setNow] = useState(Date.now); const [recommend, setRecommend] = useState<number | null>(null); const [resubmit, setResubmit] = useState<Recommendation | null>(null)
  useEffect(() => { const timer = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(timer) }, [])
  const search = new URLSearchParams({ status: params.get('status') ?? 'all', page: params.get('page') ?? '1', page_size: params.get('page_size') ?? '25' }).toString()
  const additions = useQuery({ queryKey: [...rssReviewKey(viewer), 'additions', search], queryFn: ({ signal }) => fetchAdditions(search, signal), enabled: tab === 'additions', retry: false, refetchInterval: () => document.hidden ? false : 3000 })
  const recommendations = useQuery({ queryKey: [...rssReviewKey(viewer), 'mine', search], queryFn: ({ signal }) => fetchMyRecommendations(search, signal), enabled: tab === 'recommendations', retry: false, refetchInterval: () => document.hidden ? false : 5000 })
  const observed = useRef(new Map<string, string>())
  const observedSearch = useRef(search)
  useEffect(() => {
    if (!additions.data) return
    if (observedSearch.current !== search) { observed.current.clear(); observedSearch.current = search }
    let changed = false
    const seen = new Set(additions.data.results.map(row => row.operation_id))
    for (const id of observed.current.keys()) { if (!seen.has(id)) { observed.current.delete(id); changed = true } }
    for (const row of additions.data.results) {
      const stamp = `${row.state}:${row.article_count ?? 0}`
      if (observed.current.get(row.operation_id) !== stamp && ['succeeded', 'failed', 'cancelled'].includes(row.state)) changed = true
      observed.current.set(row.operation_id, stamp)
    }
    if (changed) void refreshRssViews(client, viewer)
  }, [additions.data, client, viewer, search])
  const refresh = () => { void client.invalidateQueries({ queryKey: rssReviewKey(viewer) }); void refreshRssViews(client, viewer) }
  const action = useMutation({ retry: false, mutationFn: ({ row, name, key }: { row: Addition; name: string; key: string }) => actOnAddition(viewer, row.operation_id, name, row.version, key), onSuccess: refresh })
  const withdraw = useMutation({ retry: false, mutationFn: (row: Recommendation) => changeRecommendation(viewer, row.submission_id!, { action: 'withdraw', expected_version: row.version }, crypto.randomUUID()), onSuccess: refresh })
  const data = tab === 'additions' ? additions.data : recommendations.data
  const error = tab === 'additions' ? additions.error : recommendations.error
  const pending = tab === 'additions' ? additions.isPending : recommendations.isPending
  const update = (key: string, value: string) => { const next = new URLSearchParams(params); next.set(key, value); if (key !== 'page') next.set('page', '1'); if (key === 'tab') next.delete('status'); setParams(next) }
  return <main className="workspace-page"><header className="workspace-page-heading"><div><h1>添加记录</h1><p>个人 RSS 连接成功后即可使用，无需等待公开审核。</p></div><Link className="workspace-button secondary" to="/channels">返回频道管理</Link></header>
    <div className="workspace-tabs" role="group" aria-label="添加记录范围"><button aria-pressed={tab === 'additions'} onClick={() => update('tab', 'additions')}>连接记录</button><button aria-pressed={tab === 'recommendations'} onClick={() => update('tab', 'recommendations')}>我的推荐</button></div>
    {tab === 'additions' && <label>连接状态<select value={params.get('status') ?? 'all'} onChange={e => update('status', e.target.value)}><option value="all">全部</option>{Object.entries(additionLabels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>}
    {pending && <p role="status">正在读取添加记录…</p>}{error && <p role="alert">{workspaceError(error)}<button onClick={() => { void (tab === 'additions' ? additions.refetch() : recommendations.refetch()) }}>重新加载</button></p>}
    {data?.count === 0 && <p role="status">暂无记录。可以在频道管理中添加个人 RSS。</p>}
    {(action.error || withdraw.error) && <p role="alert">{workspaceError(action.error ?? withdraw.error)}</p>}
    {tab === 'additions' && additions.data?.results.map(row => <article key={row.operation_id} className="rss-addition-row"><h2 className="rss-feed-url">{row.name}</h2><p>{additionLabels[row.state]}{row.state === 'succeeded' ? row.article_state === 'ready' ? ` · 已有 ${row.article_count} 篇文章可阅读。` : row.article_state === 'empty' ? ' · 同步已完成，当前没有文章。' : ' · 文章将在后台同步，可前往我的订阅阅读。' : ''}</p>
      {row.error_code && <p>{verificationError(row.error_code)}</p>}
      <div className="workspace-actions">{row.actions.map(name => {
        const seconds = name === 'retry' ? Math.max(0, Math.ceil((Date.parse(row.cooldown_until) - now) / 1000)) : 0
        return <button key={name} className="workspace-button secondary" disabled={action.isPending || seconds > 0} onClick={() => action.mutate({ row, name, key: crypto.randomUUID() })}>{seconds > 0 ? `${seconds} 秒后可重试` : name === 'reconcile' ? '核对连接结果' : name === 'cancel' ? '取消添加' : '重新连接'}</button>
      })}{row.state === 'succeeded' && row.source_id && <><Link className="workspace-button secondary" to={`/channels/${row.source_id}`}>查看频道</Link>{row.can_recommend && <button className="workspace-button secondary" onClick={() => setRecommend(row.source_id)}>推荐到公共频道</button>}</>}</div>
    </article>)}
    {tab === 'recommendations' && recommendations.data?.results.map(row => <article key={row.submission_id} className="rss-addition-row"><h2>{row.name}</h2><p>{row.withdrawn ? '已撤回' : recommendationLabels[row.state]}</p><p className="rss-feed-url">{row.feed_url}</p>{row.reason && <p>审核说明：{row.reason}</p>}{!row.withdrawn && row.state === 'pending' && <button className="workspace-button secondary" disabled={withdraw.isPending} onClick={() => withdraw.mutate(row)}>撤回推荐</button>}{['rejected', 'withdrawn'].includes(row.state) && row.personal_source_id && <button className="workspace-button secondary" onClick={() => setResubmit(row)}>更正后重提</button>}{row.public_source_id && <Link to={`/channels/${row.public_source_id}`}>查看公开频道</Link>}</article>)}
    <footer className="workspace-actions"><label>每页条数<select value={params.get('page_size') ?? '25'} onChange={e => update('page_size', e.target.value)}><option value="25">25</option><option value="50">50</option></select></label><button disabled={!data || data.page <= 1} onClick={() => update('page', String((data?.page ?? 1) - 1))}>上一页</button><span>第 {data?.page ?? 1} 页 · 共 {data?.count ?? 0} 条</span><button disabled={!data || data.page * data.page_size >= data.count} onClick={() => update('page', String((data?.page ?? 1) + 1))}>下一页</button></footer>
    {resubmit && resubmit.personal_source_id && <RecommendFeedDialog viewer={viewer} sourceId={resubmit.personal_source_id} initial={resubmit} onClose={() => setResubmit(null)} onDone={() => { setResubmit(null); refresh() }} />}
    {recommend !== null && <RecommendFeedDialog viewer={viewer} sourceId={recommend} onClose={() => setRecommend(null)} onDone={() => { setRecommend(null); refresh(); update('tab', 'recommendations') }} />}
  </main>
}
