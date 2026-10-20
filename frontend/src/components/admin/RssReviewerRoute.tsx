import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '@/context/AuthContext'
export default function RssReviewerRoute({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth()
  if (loading) return <p role="status">正在确认频道审核权限…</p>
  if (!user || !(user.isSuperuser || user.rssCapabilities?.reviewPublicRss)) return <main className="workspace-page"><h1>无权访问</h1><p>需要频道审核权限。</p><Link to="/channels">返回频道管理</Link></main>
  return children
}
