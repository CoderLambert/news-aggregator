import { useState } from 'react'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { RefreshCw, Sparkles } from 'lucide-react'
import { useAuth } from '@/context/AuthContext'
import { useCapability } from '@/context/CapabilitiesContext'
import { FeedLoadingContext } from '@/context/FeedLoadingContext'
import { workspaceRequest, workspaceKeys, type Dashboard, type ReadingStats } from '@/services/workspaceApi'

export default function FeedWorkspace({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth()
  const accounts = useCapability('accounts').enabled
  const viewer = user?.id ?? 'anonymous'
  const [loadedViewer, setLoadedViewer] = useState<number | string | null>(null)
  const feedLoaded = !loading && loadedViewer === viewer
  const [offset, setOffset] = useState(0)
  const dashboard = useQuery({ queryKey: ['workspace', viewer, 'dashboard'], enabled: feedLoaded,
    queryFn: ({ signal }) => workspaceRequest<Dashboard>('/smart-channels/dashboard/', { signal }), staleTime: 60_000 })
  const stats = useQuery({ queryKey: workspaceKeys.stats(viewer), enabled: accounts && !!user && feedLoaded,
    queryFn: ({ signal }) => workspaceRequest<ReadingStats>('/me/reading-stats/', { signal }) })
  const stories = dashboard.data?.stories ?? []
  const visible = stories.slice(offset < stories.length ? offset : 0, (offset < stories.length ? offset : 0) + 5)
  const max = Math.max(1, ...(stats.data?.week.map(day => day.count) ?? []))
  return <div className="feed-workspace">
    <section className="feed-workspace-content" aria-label="资讯阅读列表"><FeedLoadingContext.Provider value={setLoadedViewer}>{children}</FeedLoadingContext.Provider></section>
    <aside className="feed-workspace-aside workspace-scroll">
      <section className="workspace-panel"><header className="workspace-panel-heading"><h2>{dashboard.data?.kind === 'popular' ? '近期热读' : '最新更新'}</h2>
        <button type="button" className="workspace-link" disabled={stories.length <= 5} onClick={() => setOffset(current => current === 0 ? 5 : 0)}><RefreshCw size={13} aria-hidden="true" />换一批</button>
      </header>
        {dashboard.isPending && <p className="workspace-muted" role="status">正在加载资讯…</p>}
        {dashboard.isError && <button type="button" className="workspace-link" onClick={() => void dashboard.refetch()}>加载失败，重试</button>}
        <ol className="workspace-trending">{visible.map((story, index) => <li key={story.id}><span aria-hidden="true">{offset + index + 1}</span><Link to={'/news/' + story.id}>{story.title}<small>{story.source_name}</small></Link></li>)}</ol>
        {dashboard.data && !stories.length && <p className="workspace-muted">暂无资讯，频道更新后会出现在这里。</p>}
        {dashboard.data?.kind === 'popular' && <p className="workspace-caption">按近两日站内独立读者数排序</p>}
      </section>
      <section className="workspace-panel"><header className="workspace-panel-heading"><h2>阅读数据</h2></header>
        {!user ? <p className="workspace-muted">登录后记录你的阅读足迹。</p> : stats.data ? <>
          <dl className="workspace-reading-numbers"><div><dt>今日阅读</dt><dd>{stats.data.today}<small>篇</small></dd></div><div><dt>累计文章</dt><dd>{stats.data.total}</dd></div><div><dt>连续阅读</dt><dd>{stats.data.streak}<small>天</small></dd></div></dl>
          <div className="workspace-reading-chart" role="img" aria-label={'近七日阅读：' + stats.data.week.map(day => day.day + ' ' + day.count + ' 篇').join('；')}>
            {stats.data.week.map(day => <span key={day.day} title={day.day + ' · ' + day.count + ' 篇'}><i style={{ height: Math.max(3, day.count / max * 60) + 'px' }} /><small>{day.day.slice(8)}</small></span>)}
          </div><p className="workspace-caption">打开文章并停留后累计 · {stats.data.timezone}</p>
          <Link className="workspace-link" to="/channels/smart">管理阅读记录与整理设置</Link>
        </> : stats.isError ? <button type="button" className="workspace-link" onClick={() => void stats.refetch()}>读取失败，重试</button> : <p role="status" className="workspace-muted">正在读取…</p>}
      </section>
      {accounts && <Link to="/channels/smart" className="workspace-smart-promo"><Sparkles size={24} aria-hidden="true" /><strong>让频道更有条理</strong><span>选择主题预设，预览并整理你的订阅。</span><b>开始智能整理 →</b></Link>}
    </aside>
  </div>
}
