import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { BookOpen, FolderOpen, Heart, House, Menu, Moon, Plus, Rss, Search, Settings, Sparkles, Sun } from 'lucide-react'
import { useChannelConfig } from '@/services/channelQueries'
import { useCapability } from '@/context/CapabilitiesContext'
import WorkspaceModal from './WorkspaceModal'
import '@/styles/workspace.css'

export default function WorkspaceShell({ children }: { children: ReactNode }) {
  const config = useChannelConfig()
  const accounts = useCapability('accounts').enabled
  const favorites = useCapability('favorites').enabled
  const location = useLocation()
  const [drawer, setDrawer] = useState(false)
  const [dark, setDark] = useState(() => { try { return localStorage.getItem('newshub-theme') === 'dark' } catch { return false } })
  useEffect(() => {
    document.documentElement.classList.toggle('dark', dark)
    try { localStorage.setItem('newshub-theme', dark ? 'dark' : 'light') } catch { /* Private mode may disable storage. */ }
  }, [dark])
  const readingLink = (scope: string, groupId?: number) => {
    const params = new URLSearchParams(location.pathname === '/' ? location.search : '')
    params.set('scope', scope)
    params.delete('source'); params.delete('page'); params.delete('group_id')
    if (groupId) params.set('group_id', String(groupId))
    return '/?' + params.toString()
  }
  const items = [
    { label: '首页', to: '/', icon: House },
    ...(accounts ? [{ label: '我的订阅', to: '/?scope=subscribed', icon: BookOpen }] : []),
    { label: '频道管理', to: '/channels', icon: Rss },
    ...(accounts ? [{ label: '分组管理', to: '/channels/groups', icon: FolderOpen }, { label: 'AI 智能整理', to: '/channels/smart', icon: Sparkles }] : []),
    { label: '检索中心', to: '/search', icon: Search },
    ...(favorites ? [{ label: '智库收藏', to: '/favorites', icon: Heart }] : []),
  ]
  const active = (to: string) => {
    if (to.includes('?')) return location.pathname === '/' && new URLSearchParams(location.search).get('scope') === 'subscribed'
    if (to === '/') return location.pathname === '/' && !['subscribed', 'group', 'ungrouped'].includes(new URLSearchParams(location.search).get('scope') ?? '')
    return location.pathname === to || (to === '/channels' && /^\/channels\/\d+$/.test(location.pathname))
  }
  const navigation = <>
    <Link className="workspace-brand" to="/" onClick={() => setDrawer(false)}><span aria-hidden="true">N</span>NewsHub</Link>
    <nav aria-label="阅读工作区导航" className="workspace-nav">{items.map(({ label, to, icon: Icon }) =>
      <Link key={to} to={to} aria-current={active(to) ? 'page' : undefined} onClick={() => setDrawer(false)}><Icon size={17} aria-hidden="true" />{label}</Link>)}</nav>
    {config.enabled && <section className="workspace-groups" aria-label="快捷分组">
      <p className="workspace-eyebrow">快捷分组 <span>频道数</span></p>
      <Link to={readingLink('all')} onClick={() => setDrawer(false)}><FolderOpen size={15} aria-hidden="true" />全部资讯</Link>
      <Link to={readingLink('ungrouped')} onClick={() => setDrawer(false)}><FolderOpen size={15} aria-hidden="true" />未加入分组</Link>
      {(config.groups.data ?? []).map(group => <Link key={group.id} to={readingLink('group', group.id)} onClick={() => setDrawer(false)}
        aria-current={location.pathname === '/' && new URLSearchParams(location.search).get('group_id') === String(group.id) ? 'page' : undefined}>
        <span className="workspace-topic-dot" aria-hidden="true" /><span className="workspace-truncate">{group.name}</span><small title={group.source_ids.length + ' 个频道'}>{group.source_ids.length}</small>
      </Link>)}
      {config.error && <button type="button" className="workspace-link" onClick={() => void config.retry()}>重试加载分组</button>}
      <Link className="workspace-new-group" to="/channels/groups" onClick={() => setDrawer(false)}><Plus size={16} aria-hidden="true" />新建分组</Link>
    </section>}
    <div className="workspace-sidebar-bottom"><p>让值得阅读的信息<br />有序地来到你面前。</p>
      <Link to="/settings" onClick={() => setDrawer(false)}><Settings size={16} aria-hidden="true" />设置</Link>
      <button type="button" onClick={() => setDark(value => !value)}>{dark ? <Sun size={16} aria-hidden="true" /> : <Moon size={16} aria-hidden="true" />}{dark ? '切换浅色' : '切换深色'}</button>
    </div>
  </>
  return <div className="workspace-shell">
    <aside className="workspace-sidebar">{navigation}</aside>
    <div className="workspace-main">
      <button type="button" className="workspace-mobile-navigation" onClick={() => setDrawer(true)} aria-expanded={drawer}><Menu size={17} aria-hidden="true" />工作区导航</button>
      {children}
    </div>
    {drawer && <WorkspaceModal title="工作区导航" onClose={() => setDrawer(false)}><div className="workspace-mobile-drawer">{navigation}</div></WorkspaceModal>}
  </div>
}
