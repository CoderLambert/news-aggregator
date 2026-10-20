import { useQuery } from '@tanstack/react-query'
import { workspaceRequest, workspaceError } from '@/services/workspaceApi'

interface Subscription { id: number; name: string; feeds: { id: string; connection_state: string; desired_mode: string }[] }
interface Health { verification_counts?: Record<string, number>; engine_ready: boolean; initial_sync: boolean; last_successful_incremental: string | null; last_successful_full_reconcile: string | null; lag: number | null; error_class: string | null }
const labels: Record<string, string> = { pending: '等待连接', connecting: '正在连接', ready: '来源已连接', paused: '采集暂停', error: '连接失败', unknown: '连接结果待核对' }
const timeLabel = (value: string | null) => value ? new Date(value).toLocaleString() : '尚无完成记录'

export default function ConnectionStatus({ viewer, admin }: { viewer: number; admin: boolean }) {
  const subscriptions = useQuery({ enabled: !admin, queryKey: ['private', 'rss-subscriptions', viewer],
    queryFn: ({ signal }) => workspaceRequest<{ results: Subscription[] }>('/me/rss-subscriptions/', { signal }),
    refetchInterval: 15_000 })
  const health = useQuery({ queryKey: ['private', 'rss-health', viewer], enabled: admin,
    queryFn: ({ signal }) => workspaceRequest<Health>('/admin/rss/health/', { signal }), refetchInterval: 15_000 })
  const errors = subscriptions.error ?? health.error
  if (!admin && !errors && !subscriptions.data?.results.length) return null
  if (admin) return <section className="workspace-soft-panel" aria-label="RSS 运行概览">
    <p>RSS 连接状态{health.data ? health.data.engine_ready ? ' · 引擎可用' : ' · 引擎状态待确认' : ''}</p>
    {health.isPending && <p role="status">正在读取引擎状态…</p>}
    {health.error && <p role="alert">{workspaceError(health.error)}<button type="button" onClick={() => void health.refetch()}>重新加载</button></p>}
    <p>待处理频道：{health.data?.verification_counts?.pending ?? '—'}</p>
    <a className="workspace-button" href="/admin/rss/channels">处理待核验频道</a>
  </section>
  return <details className="workspace-soft-panel">
    <summary>RSS 连接状态{health.data ? health.data.engine_ready ? ' · 引擎可用' : ' · 引擎状态待确认' : ''}</summary>
    {errors && <p role="alert">{workspaceError(errors)}<button type="button" className="workspace-link" onClick={() => { void subscriptions.refetch(); if (admin) void health.refetch() }}>重新加载</button></p>}
    {subscriptions.data?.results.map(subscription => <p key={subscription.id}><strong>{subscription.name}</strong> · {subscription.feeds.map(feed => labels[feed.connection_state] ?? '等待确认').join('、')}</p>)}
    {health.data && <dl className="workspace-caption">
      <dt>初始同步</dt><dd>{health.data.initial_sync ? '尚未完成' : '已有同步完成记录'}</dd>
      <dt>最近增量同步完成</dt><dd>{timeLabel(health.data.last_successful_incremental)}</dd>
      <dt>最近全保留条目对账完成</dt><dd>{timeLabel(health.data.last_successful_full_reconcile)}</dd>
      <dt>已观测 ID 距离</dt><dd>{health.data.lag ?? '未知'}（不等于待处理文章数量）</dd>
      {health.data.error_class && <><dt>最近错误</dt><dd>{health.data.error_class}</dd></>}
    </dl>}
    <p className="workspace-caption">连接成功后，文章同步由后台继续完成。暂停采集会保留历史文章。</p>
  </details>
}
