import { useState } from 'react'
import { Link } from 'react-router-dom'
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

export default function FavoritesPage() {
  const { user, loading: authLoading } = useAuth()
  const [filter, setFilter] = useState<FavoriteFilter>('all')
  const [tab, setTab] = useState<Tab>('favorites')
  const [showAuth, setShowAuth] = useState(false)
  const unblockMutation = useUnblockNews()
  const viewerId = user?.id ?? 0
  const favoritesQuery = useQuery({
    ...favoritesOptions(viewerId, filter),
    enabled: Boolean(user) && tab === 'favorites',
  })
  const blockedQuery = useQuery({
    ...blockedNewsOptions(viewerId),
    enabled: Boolean(user) && tab === 'blocked',
  })
  const currentQuery = tab === 'favorites' ? favoritesQuery : blockedQuery
  const favorites = favoritesQuery.data?.results ?? []
  const blocked = blockedQuery.data?.results ?? []

  async function handleUnblock(newsId: number) {
    unblockMutation.reset()
    try {
      if (!user) return
      await unblockMutation.mutateAsync({ newsId, viewerId: user.id })
    } catch {
      // Keep the row visible until the server confirms the restore.
    }
  }

  if (authLoading || (user && currentQuery.isPending)) return <LoadingSpinner />

  if (!user) {
    return (
      <div className="mx-auto w-full max-w-3xl overflow-x-hidden px-4 pb-8 pt-4 sm:pb-10 sm:pt-6">
        <nav className="mb-8 flex items-center justify-between">
          <Link to="/" className="inline-flex items-center gap-1.5 text-sm text-neutral-500 transition-colors hover:text-neutral-900">
            <ArrowLeft className="size-3.5" />返回主页
          </Link>
        </nav>
        <div className="py-16 text-center">
          <div className="mx-auto mb-6 flex size-20 items-center justify-center rounded-full bg-neutral-100"><LogIn className="size-10 text-neutral-400" /></div>
          <h2 className="mb-2 text-xl font-semibold text-neutral-800">登录后查看收藏</h2>
          <p className="mb-6 text-neutral-500">登录小闻账号，收藏和点赞你感兴趣的新闻</p>
          <button type="button" onClick={() => setShowAuth(true)} className="inline-flex items-center gap-2 rounded-full bg-gradient-to-r from-orange-400 to-pink-400 px-6 py-2.5 text-sm font-medium text-white shadow-md transition-all hover:from-orange-500 hover:to-pink-500 hover:shadow-lg active:scale-[0.97]">
            <LogIn className="size-4" />立即登录
          </button>
        </div>
        {showAuth && <AuthModal onClose={() => setShowAuth(false)} />}
      </div>
    )
  }

  return (
    <div className="mx-auto w-full max-w-3xl overflow-x-hidden px-4 pb-8 pt-4 sm:pb-10 sm:pt-6">
      <nav className="mb-6 flex items-center justify-between">
        <Link to="/" className="inline-flex items-center gap-1.5 text-sm text-neutral-500 transition-colors hover:text-neutral-900"><ArrowLeft className="size-3.5" />返回主页</Link>
        <h1 className="text-lg font-semibold text-neutral-900">{tab === 'favorites' ? '我的收藏' : '屏蔽管理'}</h1>
      </nav>

      <div className="mb-6 flex gap-2" role="tablist" aria-label="用户新闻管理">
        <button type="button" role="tab" aria-selected={tab === 'favorites'} onClick={() => setTab('favorites')} className={`rounded-full px-4 py-2 text-sm font-medium transition-all duration-200 ${tab === 'favorites' ? 'bg-gradient-to-br from-orange-400 to-orange-500 text-white shadow-md shadow-orange-200' : 'border border-gray-200 bg-white text-gray-600 hover:border-orange-300 hover:text-orange-500'}`}>
          <Heart className="mr-1 inline-block size-3.5" fill={tab === 'favorites' ? 'currentColor' : 'none'} />收藏
        </button>
        <button type="button" role="tab" aria-selected={tab === 'blocked'} onClick={() => setTab('blocked')} className={`rounded-full px-4 py-2 text-sm font-medium transition-all duration-200 ${tab === 'blocked' ? 'bg-gradient-to-br from-red-400 to-red-500 text-white shadow-md shadow-red-200' : 'border border-gray-200 bg-white text-gray-600 hover:border-red-300 hover:text-red-500'}`}>
          <EyeOff className="mr-1 inline-block size-3.5" />屏蔽
        </button>
      </div>

      {currentQuery.isError && (
        <div role="alert" className="mb-5 flex items-center justify-center gap-3 text-sm text-red-700">
          <span>{tab === 'favorites' ? '收藏内容加载失败。' : '屏蔽内容加载失败。'}</span>
          <button type="button" className="underline" onClick={() => void currentQuery.refetch()}>重试</button>
        </div>
      )}

      {tab === 'favorites' && (
        <section role="tabpanel" aria-label="收藏内容">
          <div className="mb-6 flex gap-2" aria-label="收藏筛选">
            {([
              { key: 'all', label: '全部' },
              { key: 'like', label: '点赞' },
              { key: 'bookmark', label: '收藏' },
            ] as const).map((option) => (
              <button key={option.key} type="button" aria-pressed={filter === option.key} onClick={() => setFilter(option.key)} className={`rounded-full px-4 py-2 text-sm font-medium transition-all duration-200 ${filter === option.key ? 'bg-gradient-to-br from-orange-400 to-orange-500 text-white shadow-md shadow-orange-200' : 'border border-gray-200 bg-white text-gray-600 hover:border-orange-300 hover:text-orange-500'}`}>
                {option.key === 'like' && <Heart className="mr-1 inline-block size-3.5" fill={filter === option.key ? 'currentColor' : 'none'} />}
                {option.key === 'bookmark' && <Bookmark className="mr-1 inline-block size-3.5" fill={filter === option.key ? 'currentColor' : 'none'} />}
                {option.label}
              </button>
            ))}
          </div>

          {favoritesQuery.isFetching && favoritesQuery.data && <p role="status" className="mb-3 text-center text-xs text-neutral-400">正在更新…</p>}
          {!favorites.length && !currentQuery.isError ? (
            <div className="py-16 text-center text-gray-400">
              <Heart className="mx-auto mb-4 size-16 opacity-30" />
              <p className="text-lg">还没有收藏内容</p>
              <p className="mt-2 text-sm">去浏览新闻，看到喜欢的就点个赞吧！</p>
            </div>
          ) : (
            <div className="space-y-4">{favorites.map((favorite) => <FavoriteCard key={favorite.id} favorite={favorite} />)}</div>
          )}
        </section>
      )}

      {tab === 'blocked' && (
        <section role="tabpanel" aria-label="屏蔽内容">
          {blockedQuery.isFetching && blockedQuery.data && <p role="status" className="mb-3 text-center text-xs text-neutral-400">正在更新…</p>}
          {unblockMutation.isError && <p role="alert" className="mb-4 text-center text-sm text-red-700">恢复失败，请重试。</p>}
          {!blocked.length && !currentQuery.isError ? (
            <div className="py-16 text-center text-gray-400">
              <EyeOff className="mx-auto mb-4 size-16 opacity-30" />
              <p className="text-lg">没有屏蔽内容</p>
              <p className="mt-2 text-sm">不想看到的新闻可以点击屏蔽按钮隐藏</p>
            </div>
          ) : (
            <div className="space-y-3">
              {blocked.map((block) => (
                <BlockedCard
                  key={block.id}
                  block={block}
                  onUnblock={handleUnblock}
                  pending={unblockMutation.isPending}
                />
              ))}
            </div>
          )}
        </section>
      )}
    </div>
  )
}

function FavoriteCard({ favorite }: { favorite: UserFavorite }) {
  const news = favorite.news
  const title = news.title_zh || news.title || '未知标题'
  const summary = news.content_zh || news.content
  const date = favorite.created_at ? new Date(favorite.created_at).toLocaleDateString('zh-CN') : ''
  const isLiked = favorite.type === 'like'

  return (
    <Link to={`/news/${news.id}`} state={{ from: '/favorites' }} className="block rounded-2xl border border-gray-100 bg-white p-5 shadow-sm transition-all duration-200 hover:border-orange-200 hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-orange-400">
      <div className="flex items-start gap-3">
        <div className={`flex size-10 shrink-0 items-center justify-center rounded-full ${isLiked ? 'bg-gradient-to-br from-orange-400 to-orange-500 text-white' : 'bg-gradient-to-br from-blue-400 to-blue-500 text-white'}`}>
          {isLiked ? <Heart size={18} fill="currentColor" /> : <Bookmark size={18} fill="currentColor" />}
        </div>
        <div className="min-w-0 flex-1">
          <h2 className="mb-1 line-clamp-2 text-base font-semibold text-neutral-900">{title}</h2>
          {summary && <p className="mb-2 line-clamp-2 text-sm text-gray-500">{summary.slice(0, 100)}...</p>}
          <div className="flex items-center gap-3 text-xs text-gray-400">
            {date && <span className="flex items-center gap-1"><Clock className="size-3" />{date}</span>}
            {news.source_name && <span className="truncate">{news.source_name}</span>}
          </div>
        </div>
      </div>
    </Link>
  )
}

function BlockedCard({ block, onUnblock, pending }: {
  block: BlockedNewsItem
  onUnblock: (newsId: number) => void
  pending: boolean
}) {
  const news = block.news
  const title = news.title_zh || news.title || '未知标题'
  const date = block.created_at ? new Date(block.created_at).toLocaleDateString('zh-CN') : ''

  return (
    <article className="flex items-center gap-3 rounded-2xl border border-gray-100 bg-white p-4 shadow-sm">
      <div className="flex size-10 shrink-0 items-center justify-center rounded-full bg-gray-100 text-gray-400"><EyeOff size={18} /></div>
      <div className="min-w-0 flex-1">
        <h2 className="line-clamp-1 text-sm font-medium text-neutral-700">{title}</h2>
        {date && <time className="text-xs text-gray-400">{date}</time>}
      </div>
      <button type="button" disabled={pending} onClick={() => onUnblock(news.id)} className="flex items-center gap-1 rounded-full bg-orange-50 px-3 py-1.5 text-xs font-medium text-orange-600 transition-all hover:bg-orange-100 active:scale-95 disabled:cursor-wait disabled:opacity-50" title="取消屏蔽">
        <RotateCcw size={12} />{pending ? '恢复中…' : '恢复'}
      </button>
    </article>
  )
}
