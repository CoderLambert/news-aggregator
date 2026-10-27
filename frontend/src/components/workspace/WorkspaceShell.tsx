import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { ReactNode, MouseEvent } from 'react'
import { Link, useLocation, useNavigationType } from 'react-router-dom'
import { useAuth } from '@/context/AuthContext'
import { readingPosition, rememberReadingPosition } from '@/services/readingPosition'
import { BookOpen, ChevronDown, ChevronRight, Folder, FolderOpen, Heart, House, Menu, Moon, Plus, Rss, Search, Settings, Sparkles, Sun } from 'lucide-react'
import { useChannelConfig } from '@/services/channelQueries'
import { useCapability } from '@/context/CapabilitiesContext'
import WorkspaceModal from './WorkspaceModal'
import '@/styles/workspace.css'
import { Button } from '@/components/ui/button'
import { channelGroupPath } from '@/types/channels'

export default function WorkspaceShell({ children }: { children: ReactNode }) {
  const shellRef = useRef<HTMLDivElement>(null)
  const config = useChannelConfig()
  const accounts = useCapability('accounts').enabled
  const favorites = useCapability('favorites').enabled
  const location = useLocation()
  const navigationType = useNavigationType()
  const { user } = useAuth()
  const viewerKey = user?.id ?? 'anonymous'
  const [drawer, setDrawer] = useState(false)
  const [collapsedRoots, setCollapsedRoots] = useState<Set<number>>(() => new Set())
  const [dark, setDark] = useState(() => { try { return localStorage.getItem('newshub-theme') === 'dark' } catch { return false } })
  useEffect(() => {
    document.documentElement.classList.toggle('dark', dark)
    try { localStorage.setItem('newshub-theme', dark ? 'dark' : 'light') } catch { /* Private mode may disable storage. */ }
  }, [dark])
  useLayoutEffect(() => {
    const main = shellRef.current?.querySelector<HTMLElement>('.workspace-main > main')
    if (!main) return
    const previous = readingPosition(viewerKey, location.pathname, location.search)
    const returnState = location.state
    const requestedArticleId = typeof returnState === 'object' && returnState !== null && 'restoreArticleId' in returnState
      ? String(returnState.restoreArticleId)
      : null
    const shouldRestore = Boolean(previous && (
      (navigationType === 'POP' && !location.pathname.startsWith('/news/')) ||
      requestedArticleId === previous.articleId
    ))
    document.documentElement.scrollTop = 0
    document.body.scrollTop = 0
    if (!shouldRestore || !previous) {
      main.scrollTop = 0
      return
    }

    // A route can return before paginated article cards finish rendering.
    // Observe only the owned reading container, bounded by a timeout.
    let done = false
    const restore = () => {
      if (done) return
      const anchor = document.getElementById('news-card-' + previous.articleId)
      if (!anchor || !main.contains(anchor)) return
      main.scrollTop = Math.max(0, previous.top + anchor.getBoundingClientRect().top
        - main.getBoundingClientRect().top - previous.offset)
      if (anchor instanceof HTMLElement) anchor.focus({ preventScroll: true })
      done = true
    }
    main.scrollTop = previous.top
    const observer = new MutationObserver(restore)
    observer.observe(main, { childList: true, subtree: true })
    const expiry = window.setTimeout(() => {
      observer.disconnect()
    }, 10000)
    restore()
    return () => {
      done = true
      observer.disconnect()
      window.clearTimeout(expiry)
    }
  }, [location.pathname, location.search, location.state, navigationType, viewerKey])

  function captureArticleNavigation(event: MouseEvent<HTMLDivElement>) {
    if (!(event.target instanceof Element)) return
    const link = event.target.closest<HTMLAnchorElement>('a[id^="news-card-"]')
    const main = shellRef.current?.querySelector<HTMLElement>('.workspace-main > main')
    if (!link || !main || !main.contains(link)) return
    const articleId = link.id.slice('news-card-'.length)
    if (!/^[1-9]\d*$/.test(articleId)) return
    rememberReadingPosition(viewerKey, location.pathname, location.search, {
      top: main.scrollTop,
      articleId,
      offset: link.getBoundingClientRect().top - main.getBoundingClientRect().top,
    })
  }
  useEffect(() => {
    const shell = shellRef.current
    if (!shell) return
    const timers = new Map<HTMLElement, ReturnType<typeof setTimeout>>()
    const handleScroll = (event: Event) => {
      const target = event.target
      if (!(target instanceof HTMLElement) || !target.matches('.workspace-scroll, .workspace-main > main')) return
      target.classList.add('is-scrolling')
      const previousTimer = timers.get(target)
      if (previousTimer) clearTimeout(previousTimer)
      timers.set(target, setTimeout(() => {
        target.classList.remove('is-scrolling')
        timers.delete(target)
      }, 650))
    }
    shell.addEventListener('scroll', handleScroll, true)
    return () => {
      shell.removeEventListener('scroll', handleScroll, true)
      timers.forEach(timer => clearTimeout(timer))
    }
  }, [])
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
      {(config.groups.data ?? []).filter(group => group.root_id === null).map(group => <Link key={group.id} to={readingLink('group', group.id)} onClick={() => setDrawer(false)}
        aria-current={location.pathname === '/' && new URLSearchParams(location.search).get('group_id') === String(group.id) ? 'page' : undefined}>
        <Folder size={15} className="shrink-0" aria-hidden="true" /><span className="min-w-0 flex-1 whitespace-normal break-words [overflow-wrap:anywhere]" title={group.name}>{group.name}</span><small title={group.source_ids.length + ' 个频道'}>{group.source_ids.length}</small>
      </Link>)}
      {(config.roots.data ?? []).map(root => {
        const children = (config.groups.data ?? []).filter(group => group.root_id === root.id)
        const collapsed = collapsedRoots.has(root.id)
        return <div key={root.id} className="min-w-0">
          <Button type="button" variant="ghost" className="h-auto w-full min-w-0 justify-start whitespace-normal text-left" aria-expanded={!collapsed}
            aria-label={(collapsed ? '展开 ' : '折叠 ') + root.name}
            onClick={() => setCollapsedRoots(current => {
              const next = new Set(current)
              if (next.has(root.id)) next.delete(root.id)
              else next.add(root.id)
              return next
            })}>
            {collapsed ? <ChevronRight size={15} className="shrink-0" aria-hidden="true" /> : <ChevronDown size={15} className="shrink-0" aria-hidden="true" />}
            {collapsed ? <Folder size={15} className="shrink-0" aria-hidden="true" /> : <FolderOpen size={15} className="shrink-0" aria-hidden="true" />}<span className="min-w-0 break-words [overflow-wrap:anywhere]">{root.name}</span>
          </Button>
          {!collapsed && <div className="ml-6 border-l pl-2">{children.map(group => <Link key={group.id} to={readingLink('group', group.id)} onClick={() => setDrawer(false)}
            aria-current={location.pathname === '/' && new URLSearchParams(location.search).get('group_id') === String(group.id) ? 'page' : undefined}>
            <Folder size={15} className="shrink-0" aria-hidden="true" /><span className="min-w-0 flex-1 whitespace-normal break-words [overflow-wrap:anywhere]" title={channelGroupPath(group, config.roots.data ?? [])}>{group.name}</span><small title={group.source_ids.length + ' 个频道'}>{group.source_ids.length}</small>
          </Link>)}</div>}
        </div>
      })}
      {config.error && <button type="button" className="workspace-link" onClick={() => void config.retry()}>重试加载分组</button>}
      <Link className="workspace-new-group" to="/channels/groups" onClick={() => setDrawer(false)}><Plus size={16} aria-hidden="true" />新建分组</Link>
    </section>}
    <div className="workspace-sidebar-bottom"><p>让值得阅读的信息<br />有序地来到你面前。</p>
      <Link to="/settings" onClick={() => setDrawer(false)}><Settings size={16} aria-hidden="true" />设置</Link>
      <button type="button" onClick={() => setDark(value => !value)}>{dark ? <Sun size={16} aria-hidden="true" /> : <Moon size={16} aria-hidden="true" />}{dark ? '切换浅色' : '切换深色'}</button>
    </div>
  </>
  return <div ref={shellRef} className="workspace-shell" onClickCapture={captureArticleNavigation}>
    <aside className="workspace-sidebar workspace-scroll">{navigation}</aside>
    <div className="workspace-main">
      <button type="button" className="workspace-mobile-navigation" onClick={() => setDrawer(true)} aria-expanded={drawer}><Menu size={17} aria-hidden="true" />工作区导航</button>
      {children}
    </div>
    {drawer && <WorkspaceModal title="工作区导航" onClose={() => setDrawer(false)}><div className="workspace-mobile-drawer">{navigation}</div></WorkspaceModal>}
  </div>
}
