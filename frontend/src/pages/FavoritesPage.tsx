import { useRef, useState } from 'react'
import type { KeyboardEvent, ReactNode } from 'react'
import { Link, useLocation, useSearchParams } from 'react-router-dom'
import { ArrowLeft, Bookmark, Clock, EyeOff, Heart, LogIn, RotateCcw } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import LoadingSpinner from '@/components/LoadingSpinner'
import { useAuth } from '@/context/AuthContext'
import AuthModal from '@/components/AuthModal'
import { useUnblockNews } from '@/hooks/useNewsMutations'
import { blockedNewsOptions, favoritesOptions } from '@/services/userNewsQueries'
import type { BlockedNewsItem, UserFavorite } from '@/types/userNews'
import type { FavoriteFilter } from '@/services/userNewsQueries'

type Tab = 'favorites' | 'blocked'

function parseFilter(value: string | null): FavoriteFilter {
  return value === 'like' || value === 'bookmark' ? value : 'all'
}

export default function FavoritesPage() {
  const { user, loading: authLoading } = useAuth()
  const location = useLocation()
  const [searchParams, setSearchParams] = useSearchParams()
  const [showAuth, setShowAuth] = useState(false)
  const tabRefs = useRef<Record<Tab, HTMLButtonElement | null>>({ favorites: null, blocked: null })
  const unblockMutation = useUnblockNews()
  const tab: Tab = searchParams.get('view') === 'blocked' ? 'blocked' : 'favorites'
  const filter = parseFilter(searchParams.get('filter'))
  const viewerId = user?.id ?? 0
  const favoritesQuery = useQuery({ ...favoritesOptions(viewerId, filter), enabled: Boolean(user) && tab === 'favorites' })
  const blockedQuery = useQuery({ ...blockedNewsOptions(viewerId), enabled: Boolean(user) && tab === 'blocked' })
  const currentQuery = tab === 'favorites' ? favoritesQuery : blockedQuery
  const favorites = favoritesQuery.data?.results ?? []
  const blocked = blockedQuery.data?.results ?? []
  const returnPath = `${location.pathname}${location.search}`

  function updatePreferences(nextTab: Tab, nextFilter = filter) {
    const next = new URLSearchParams()
    if (nextTab === 'blocked') next.set('view', 'blocked')
    if (nextFilter !== 'all') next.set('filter', nextFilter)
    setSearchParams(next)
  }

  async function handleUnblock(newsId: number) {
    unblockMutation.reset()
    const currentIndex = blocked.findIndex((entry) => entry.news.id === newsId)
    const focusNewsId = blocked[currentIndex + 1]?.news.id ?? blocked[currentIndex - 1]?.news.id
    try {
      if (!user) return
      await unblockMutation.mutateAsync({ newsId, viewerId: user.id })
      window.requestAnimationFrame(() => {
        const adjacentAction = focusNewsId ? document.getElementById(`restore-blocked-${focusNewsId}`) : null
        ;(adjacentAction ?? tabRefs.current.blocked)?.focus()
      })
    } catch {
      window.requestAnimationFrame(() => {
        const failedAction = document.getElementById(`restore-blocked-${newsId}`)
        ;(failedAction ?? tabRefs.current.blocked)?.focus()
      })
    }
  }

  function handleTabKeyDown(event: KeyboardEvent<HTMLButtonElement>, currentTab: Tab) {
    const tabs: Tab[] = ['favorites', 'blocked']
    const currentIndex = tabs.indexOf(currentTab)
    const nextIndex = event.key === 'ArrowRight'
      ? (currentIndex + 1) % tabs.length
      : event.key === 'ArrowLeft'
        ? (currentIndex + tabs.length - 1) % tabs.length
        : event.key === 'Home'
          ? 0
          : event.key === 'End' ? tabs.length - 1 : -1
    if (nextIndex < 0) return
    event.preventDefault()
    const nextTab = tabs[nextIndex]
    updatePreferences(nextTab)
    tabRefs.current[nextTab]?.focus()
  }

  if (authLoading) return <LoadingSpinner />

  if (!user) {
    return (
      <div className="mx-auto w-full max-w-3xl px-4 pb-10 pt-6">
        <BackHome />
        <div className="py-16 text-center">
          <div className="mx-auto mb-6 flex size-16 items-center justify-center rounded-2xl bg-muted"><LogIn className="size-8 text-muted-foreground" /></div>
          <h1 className="text-2xl font-semibold">登录后管理内容偏好</h1>
          <p className="mx-auto mt-3 max-w-md text-sm leading-6 text-muted-foreground">收藏、点赞和屏蔽记录与 NewsHub 账号关联。</p>
          <button type="button" onClick={() => setShowAuth(true)} className="mt-6 inline-flex min-h-11 items-center gap-2 rounded-lg bg-primary px-5 text-sm font-medium text-primary-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
            <LogIn className="size-4" />立即登录
          </button>
        </div>
        {showAuth && <AuthModal onClose={() => setShowAuth(false)} />}
      </div>
    )
  }

  return (
    <div className="mx-auto w-full max-w-3xl px-4 pb-12 pt-6 sm:pt-10">
      <BackHome />
      <header className="mb-7 mt-4">
        <p className="text-sm font-medium text-orange-600">个性化阅读</p>
        <h1 className="mt-1 text-3xl font-semibold tracking-tight">内容偏好</h1>
        <p className="mt-2 text-sm leading-6 text-muted-foreground">集中管理收藏、点赞和不希望在列表中看到的新闻。</p>
      </header>

      <div className="mb-6 grid grid-cols-2 gap-2 rounded-xl bg-muted p-1.5" role="tablist" aria-label="内容偏好分类">
        <PreferenceTab tab="favorites" current={tab} buttonRef={(element) => { tabRefs.current.favorites = element }} onKeyDown={handleTabKeyDown} onSelect={updatePreferences} icon={Heart}>收藏与点赞</PreferenceTab>
        <PreferenceTab tab="blocked" current={tab} buttonRef={(element) => { tabRefs.current.blocked = element }} onKeyDown={handleTabKeyDown} onSelect={updatePreferences} icon={EyeOff}>已屏蔽</PreferenceTab>
      </div>

      {currentQuery.isError && (
        <div role="alert" className="mb-5 flex min-h-11 items-center justify-between gap-3 rounded-xl border border-destructive/30 bg-destructive/5 px-4 text-sm text-destructive">
          <span>{tab === 'favorites' ? '收藏内容加载失败。' : '屏蔽内容加载失败。'}</span>
          <button type="button" className="min-h-11 font-medium underline underline-offset-4" onClick={() => void currentQuery.refetch()}>重试</button>
        </div>
      )}

      <section id="favorites-panel" role="tabpanel" aria-labelledby="favorites-tab" tabIndex={0} hidden={tab !== 'favorites'}>
        <div className="mb-6 flex flex-wrap gap-2" role="group" aria-label="收藏筛选">
          {([{ key: 'all', label: '全部' }, { key: 'like', label: '点赞' }, { key: 'bookmark', label: '收藏' }] as const).map((option) => (
            <button key={option.key} type="button" aria-pressed={filter === option.key} onClick={() => updatePreferences('favorites', option.key)} className={`min-h-11 rounded-full border px-4 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${filter === option.key ? 'border-orange-500 bg-orange-50 text-orange-700' : 'border-border bg-background text-muted-foreground hover:text-foreground'}`}>
              {option.key === 'like' && <Heart aria-hidden="true" className="mr-1.5 inline-block size-4" fill={filter === option.key ? 'currentColor' : 'none'} />}
              {option.key === 'bookmark' && <Bookmark aria-hidden="true" className="mr-1.5 inline-block size-4" fill={filter === option.key ? 'currentColor' : 'none'} />}
              {option.label}
            </button>
          ))}
        </div>
        {favoritesQuery.isFetching && favoritesQuery.data && <p role="status" className="mb-3 text-center text-xs text-muted-foreground">正在更新…</p>}
        {favoritesQuery.isPending ? <LoadingSpinner /> : !favorites.length && !currentQuery.isError
          ? <EmptyState icon={Heart} title="还没有收藏内容" description="浏览新闻时，可以用点赞或收藏保存感兴趣的内容。" />
          : <div className="space-y-3">{favorites.map((favorite) => <FavoriteCard key={favorite.id} favorite={favorite} returnPath={returnPath} />)}</div>}
      </section>

      <section id="blocked-panel" role="tabpanel" aria-labelledby="blocked-tab" tabIndex={0} hidden={tab !== 'blocked'}>
        {blockedQuery.isFetching && blockedQuery.data && <p role="status" className="mb-3 text-center text-xs text-muted-foreground">正在更新…</p>}
        {unblockMutation.isError && <p role="alert" className="mb-4 rounded-xl border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">恢复失败，请重试。</p>}
        {blockedQuery.isPending ? <LoadingSpinner /> : !blocked.length && !currentQuery.isError
          ? <EmptyState icon={EyeOff} title="没有屏蔽内容" description="屏蔽的新闻会集中显示在这里，随时可以恢复。" />
          : <div className="space-y-3">{blocked.map((block) => <BlockedCard key={block.id} block={block} onUnblock={handleUnblock} pending={unblockMutation.isPending} />)}</div>}
      </section>
    </div>
  )
}

function BackHome() {
  return <Link to="/" className="inline-flex min-h-11 items-center gap-2 rounded-md text-sm text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"><ArrowLeft aria-hidden="true" className="size-4" />返回首页</Link>
}

function PreferenceTab({ tab, current, buttonRef, onKeyDown, onSelect, icon: Icon, children }: {
  tab: Tab
  current: Tab
  buttonRef: (element: HTMLButtonElement | null) => void
  onKeyDown: (event: KeyboardEvent<HTMLButtonElement>, currentTab: Tab) => void
  onSelect: (tab: Tab) => void
  icon: typeof Heart
  children: ReactNode
}) {
  const selected = tab === current
  return (
    <button ref={buttonRef} type="button" role="tab" id={`${tab}-tab`} aria-controls={`${tab}-panel`} aria-selected={selected} tabIndex={selected ? 0 : -1} onKeyDown={(event) => onKeyDown(event, tab)} onClick={() => onSelect(tab)} className={`min-h-11 rounded-lg px-4 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${selected ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'}`}>
      <Icon aria-hidden="true" className="mr-2 inline-block size-4" fill={tab === 'favorites' && selected ? 'currentColor' : 'none'} />{children}
    </button>
  )
}

function EmptyState({ icon: Icon, title, description }: { icon: typeof Heart; title: string; description: string }) {
  return <div className="rounded-2xl border border-dashed border-border px-5 py-14 text-center"><Icon aria-hidden="true" className="mx-auto size-10 text-muted-foreground/50" /><h2 className="mt-4 font-medium">{title}</h2><p className="mx-auto mt-2 max-w-sm text-sm leading-6 text-muted-foreground">{description}</p></div>
}

function FavoriteCard({ favorite, returnPath }: { favorite: UserFavorite; returnPath: string }) {
  const news = favorite.news
  const title = news.title_zh || news.title || '未知标题'
  const summary = news.content_zh || news.content
  const excerpt = summary.length > 100 ? `${summary.slice(0, 100)}…` : summary
  const date = favorite.created_at ? new Date(favorite.created_at).toLocaleDateString('zh-CN') : ''
  const isLiked = favorite.type === 'like'
  return (
    <Link to={`/news/${news.id}`} state={{ from: returnPath }} className="block rounded-2xl border border-border bg-card p-5 transition-colors hover:border-orange-300 hover:bg-muted/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
      <div className="flex items-start gap-3"><div className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-muted text-orange-600">{isLiked ? <Heart size={18} fill="currentColor" /> : <Bookmark size={18} fill="currentColor" />}</div><div className="min-w-0 flex-1"><h2 className="line-clamp-2 text-base font-semibold leading-6">{title}</h2>{excerpt && <p className="mt-1 line-clamp-2 text-sm leading-6 text-muted-foreground">{excerpt}</p>}<div className="mt-3 flex items-center gap-3 text-xs text-muted-foreground">{date && <span className="flex items-center gap-1"><Clock className="size-3" />{date}</span>}{news.source_name && <span className="truncate">{news.source_name}</span>}</div></div></div>
    </Link>
  )
}

function BlockedCard({ block, onUnblock, pending }: { block: BlockedNewsItem; onUnblock: (newsId: number) => void; pending: boolean }) {
  const news = block.news
  const title = news.title_zh || news.title || '未知标题'
  const date = block.created_at ? new Date(block.created_at).toLocaleDateString('zh-CN') : ''
  return (
    <article className="flex items-center gap-3 rounded-2xl border border-border bg-card p-4"><div className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-muted text-muted-foreground"><EyeOff size={18} /></div><div className="min-w-0 flex-1"><h2 className="line-clamp-2 text-sm font-medium leading-5">{title}</h2>{date && <time className="mt-1 block text-xs text-muted-foreground">{date}</time>}</div><button id={`restore-blocked-${news.id}`} type="button" disabled={pending} onClick={() => onUnblock(news.id)} className="inline-flex min-h-11 shrink-0 items-center gap-1.5 rounded-lg border border-border px-3 text-sm font-medium transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-wait disabled:opacity-50"><RotateCcw size={14} />{pending ? '恢复中…' : '恢复'}</button></article>
  )
}
