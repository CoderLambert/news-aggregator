import { useRef } from 'react'
import type { MutableRefObject } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Bookmark, EyeOff, Heart, LogIn } from 'lucide-react'
import gsap from 'gsap'
import { useGSAP } from '@gsap/react'
import { useAuth } from '@/context/AuthContext'
import { blockStatusOptions, favoriteStatusOptions } from '@/services/userNewsQueries'
import { useBlockNews, useToggleFavorite, useUnblockNews } from '@/hooks/useNewsMutations'
import { useCapabilities } from '@/context/CapabilitiesContext'

gsap.registerPlugin(useGSAP)

interface FavoriteButtonsProps {
  newsId: number | string
  className?: string
  onAuthRequired?: () => void
  onBlocked?: () => void
}

function pulse(ref: MutableRefObject<HTMLButtonElement | null>) {
  if (ref.current) {
    gsap.to(ref.current, { scale: 1.3, duration: 0.15, yoyo: true, repeat: 1, ease: 'power2.out' })
  }
}

export default function FavoriteButtons({ newsId, className = '', onAuthRequired, onBlocked }: FavoriteButtonsProps) {
  const { user } = useAuth()
  const { capabilities } = useCapabilities()
  const favoritesEnabled = capabilities.features.favorites.enabled
  const blockedNewsEnabled = capabilities.features.blocked_news.enabled
  const parsedId = Number(newsId)
  const validId = Number.isSafeInteger(parsedId) && parsedId > 0
  const viewerId = user?.id ?? 0
  const favoriteQuery = useQuery({ ...favoriteStatusOptions(viewerId, parsedId), enabled: favoritesEnabled && Boolean(user) && validId })
  const blockQuery = useQuery({ ...blockStatusOptions(viewerId, parsedId), enabled: blockedNewsEnabled && Boolean(user) && validId })
  const favoriteMutation = useToggleFavorite()
  const blockMutation = useBlockNews()
  const unblockMutation = useUnblockNews()

  const likeRef = useRef<HTMLButtonElement>(null)
  const bookmarkRef = useRef<HTMLButtonElement>(null)
  const blockRef = useRef<HTMLButtonElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const loading = Boolean(user) && ((favoritesEnabled && favoriteQuery.isPending) || (blockedNewsEnabled && blockQuery.isPending))
  const favoriteStatus = favoriteQuery.data
  const blockStatus = blockQuery.data
  const isLiked = favoriteStatus?.is_liked ?? false
  const isBookmarked = favoriteStatus?.is_bookmarked ?? false
  const isBlocked = blockStatus?.is_blocked ?? false
  useGSAP(() => {
    if (!containerRef.current || loading) return
    gsap.fromTo(containerRef.current, { opacity: 0, scale: 0.8, y: 10 }, {
      opacity: 1,
      scale: 1,
      y: 0,
      duration: 0.6,
      ease: 'back.out(1.7)',
    })
  }, { dependencies: [loading] })

  async function toggleFavorite(type: 'like' | 'bookmark') {
    if (!favoritesEnabled) return
    if (!user) {
      onAuthRequired?.()
      return
    }
    if (!validId || !favoriteStatus || favoriteMutation.isPending) return
    try {
      await favoriteMutation.mutateAsync({ newsId: parsedId, viewerId: user.id, type })
      pulse(type === 'like' ? likeRef : bookmarkRef)
    } catch {
      // Mutation state supplies inline feedback while preserving the last confirmed status.
    }
  }

  async function toggleBlock() {
    if (!blockedNewsEnabled) return
    if (!user) {
      onAuthRequired?.()
      return
    }
    if (!validId || !blockStatus || blockMutation.isPending || unblockMutation.isPending) return
    try {
      if (blockStatus.is_blocked) await unblockMutation.mutateAsync({ newsId: parsedId, viewerId: user.id })
      else {
        await blockMutation.mutateAsync({ newsId: parsedId, viewerId: user.id })
        if (blockRef.current) {
          gsap.to(blockRef.current, { scale: 0.5, opacity: 0, y: -20, duration: 0.4, ease: 'back.in(1.7)' })
        }
        onBlocked?.()
      }
    } catch {
      // The status remains unchanged when the server rejects the mutation.
    }
  }

  if (!favoritesEnabled && !blockedNewsEnabled) return null

  if (loading) {
    return (
      <div className="flex items-center gap-2 opacity-30" role="status" aria-label="加载互动状态">
        <div className="size-10 animate-pulse rounded-full bg-gray-200" />
        <div className="size-10 animate-pulse rounded-full bg-gray-200" />
        <div className="size-8 animate-pulse rounded-full bg-gray-200" />
      </div>
    )
  }

  const statusError = (favoritesEnabled && favoriteQuery.isError) || (blockedNewsEnabled && blockQuery.isError)
  const favoriteStatusReady = Boolean(favoriteStatus && validId)
  const blockStatusReady = Boolean(blockStatus && validId)
  const favoritePending = favoriteMutation.isPending
  const blockPending = blockMutation.isPending || unblockMutation.isPending

  return (
    <div ref={containerRef} className={`flex items-center gap-2 ${className}`}>
      {user && statusError && (
        <div role="alert" className="flex items-center gap-2 text-xs text-red-700">
          <span>互动状态加载失败。</span>
          {favoritesEnabled && favoriteQuery.isError && <button type="button" className="underline" onClick={() => void favoriteQuery.refetch()}>重试</button>}
          {blockedNewsEnabled && blockQuery.isError && <button type="button" className="underline" onClick={() => void blockQuery.refetch()}>重试</button>}
        </div>
      )}

      {favoritesEnabled && <button
        ref={likeRef}
        type="button"
        onClick={() => void toggleFavorite('like')}
        disabled={Boolean(user) && (!favoriteStatusReady || favoritePending)}
        className={`group relative flex items-center gap-1.5 rounded-full px-3 py-2 transition-all duration-200 disabled:cursor-not-allowed disabled:opacity-60 ${!user
          ? 'cursor-pointer bg-neutral-100 text-neutral-400 hover:bg-neutral-200'
          : isLiked
            ? 'bg-gradient-to-br from-orange-400 to-orange-500 text-white shadow-md shadow-orange-200'
            : 'border border-gray-200 bg-white text-gray-500 hover:border-orange-300 hover:text-orange-500 hover:shadow-sm'}`}
        aria-label={isLiked ? '取消点赞' : '点赞'}
      >
        {!user && !isLiked ? <LogIn size={16} /> : <Heart size={18} fill={isLiked ? 'currentColor' : 'none'} strokeWidth={2} />}
        <span className="tabular-nums text-xs font-medium">{(favoriteStatus?.like_count ?? 0) > 0 ? favoriteStatus?.like_count : ''}</span>
        {!user && !isLiked && <span className="ml-0.5 text-xs">登录</span>}
      </button>}

      {favoritesEnabled && <button
        ref={bookmarkRef}
        type="button"
        onClick={() => void toggleFavorite('bookmark')}
        disabled={Boolean(user) && (!favoriteStatusReady || favoritePending)}
        className={`group relative flex items-center gap-1.5 rounded-full px-3 py-2 transition-all duration-200 disabled:cursor-not-allowed disabled:opacity-60 ${!user
          ? 'cursor-pointer bg-neutral-100 text-neutral-400 hover:bg-neutral-200'
          : isBookmarked
            ? 'bg-gradient-to-br from-orange-400 to-orange-500 text-white shadow-md shadow-orange-200'
            : 'border border-gray-200 bg-white text-gray-500 hover:border-orange-300 hover:text-orange-500 hover:shadow-sm'}`}
        aria-label={isBookmarked ? '取消收藏' : '收藏'}
      >
        {!user && !isBookmarked ? <LogIn size={16} /> : <Bookmark size={18} fill={isBookmarked ? 'currentColor' : 'none'} strokeWidth={2} />}
        <span className="tabular-nums text-xs font-medium">{(favoriteStatus?.bookmark_count ?? 0) > 0 ? favoriteStatus?.bookmark_count : ''}</span>
        {!user && !isBookmarked && <span className="ml-0.5 text-xs">登录</span>}
      </button>}

      {blockedNewsEnabled && user && !isBlocked && (
        <button
          ref={blockRef}
          type="button"
          onClick={() => void toggleBlock()}
          disabled={!blockStatusReady || blockPending}
          className="flex size-9 items-center justify-center rounded-full border border-gray-200 bg-white text-gray-400 transition-all duration-200 hover:border-red-300 hover:bg-red-50 hover:text-red-500 active:scale-90 disabled:cursor-not-allowed disabled:opacity-50"
          aria-label="屏蔽此新闻"
          title="屏蔽此新闻"
        >
          <EyeOff size={16} />
        </button>
      )}

      {blockedNewsEnabled && user && isBlocked && (
        <button
          type="button"
          onClick={() => void toggleBlock()}
          disabled={!blockStatusReady || blockPending}
          className="flex cursor-pointer items-center gap-1 rounded-full border border-red-100 bg-red-50 px-2 py-1 text-xs text-red-400 transition-all hover:bg-red-100 active:scale-95 disabled:cursor-not-allowed disabled:opacity-50"
          aria-label="取消屏蔽"
          title="点击取消屏蔽"
        >
          <EyeOff size={12} />
          已屏蔽
        </button>
      )}

      {favoritesEnabled && favoriteMutation.isError && <p role="alert" className="text-xs text-red-700">操作失败，请重试。</p>}
      {blockedNewsEnabled && (blockMutation.isError || unblockMutation.isError) && <p role="alert" className="text-xs text-red-700">屏蔽操作失败，请重试。</p>}
    </div>
  )
}
