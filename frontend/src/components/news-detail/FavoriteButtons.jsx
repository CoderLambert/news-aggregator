import { useState, useEffect, useRef } from 'react'
import { Heart, Bookmark, LogIn, EyeOff } from 'lucide-react'
import gsap from 'gsap'
import { useGSAP } from '@gsap/react'
import { toggleFavorite, checkFavoriteStatus, blockNews, checkBlockedStatus } from '@/services/api'
import { useAuth } from '@/context/AuthContext'

gsap.registerPlugin(useGSAP)

/**
 * FavoriteButtons — 点赞 + 收藏 + 屏蔽按钮组（小闻风格）
 */
export default function FavoriteButtons({ newsId, className = '', onAuthRequired, onBlocked }) {
  const { user } = useAuth()
  const [isLiked, setIsLiked] = useState(false)
  const [isBookmarked, setIsBookmarked] = useState(false)
  const [isBlocked, setIsBlocked] = useState(false)
  const [likeCount, setLikeCount] = useState(0)
  const [bookmarkCount, setBookmarkCount] = useState(0)
  const [loading, setLoading] = useState(true)

  const likeRef = useRef(null)
  const bookmarkRef = useRef(null)
  const blockRef = useRef(null)
  const containerRef = useRef(null)

  // 加载收藏和屏蔽状态
  useEffect(() => {
    if (!newsId || !user) {
      queueMicrotask(() => setLoading(false))
      return
    }

    Promise.all([
      checkFavoriteStatus(newsId).catch(() => ({})),
      checkBlockedStatus(newsId).catch(() => ({ is_blocked: false })),
    ]).then(([favData, blockData]) => {
      setIsLiked(favData.is_liked || false)
      setIsBookmarked(favData.is_bookmarked || false)
      setLikeCount(favData.like_count || 0)
      setBookmarkCount(favData.bookmark_count || 0)
      setIsBlocked(blockData.is_blocked || false)
    }).finally(() => setLoading(false))
  }, [newsId, user])

  // GSAP 入场动画
  useGSAP(() => {
    if (!containerRef.current || loading) return

    gsap.fromTo(containerRef.current, {
      opacity: 0,
      scale: 0.8,
      y: 10,
    }, {
      opacity: 1,
      scale: 1,
      y: 0,
      duration: 0.6,
      ease: 'back.out(1.7)',
    })
  }, { dependencies: [loading] })

  const handleClick = (type) => {
    if (!user) {
      onAuthRequired?.()
      return
    }
    if (type === 'block') {
      handleBlock()
    } else {
      handleToggle(type)
    }
  }

  const handleToggle = async (type) => {
    try {
      const result = await toggleFavorite(newsId, type)

      if (result.removed) {
        if (type === 'like') {
          setIsLiked(false)
          setLikeCount(prev => Math.max(0, prev - 1))
        } else {
          setIsBookmarked(false)
          setBookmarkCount(prev => Math.max(0, prev - 1))
        }
      } else {
        if (type === 'like') {
          setIsLiked(true)
          setLikeCount(prev => prev + 1)
        } else {
          setIsBookmarked(true)
          setBookmarkCount(prev => prev + 1)
        }
      }

      const targetRef = type === 'like' ? likeRef : bookmarkRef
      if (targetRef?.current) {
        gsap.to(targetRef.current, {
          scale: 1.3,
          duration: 0.15,
          yoyo: true,
          repeat: 1,
          ease: 'power2.out',
        })
      }
    } catch (err) {
      console.error('Failed to toggle favorite:', err)
    }
  }

  const handleBlock = async () => {
    try {
      await blockNews(newsId)
      setIsBlocked(true)

      // 屏蔽飞走动画
      if (blockRef?.current) {
        gsap.to(blockRef.current, {
          scale: 0.5,
          opacity: 0,
          y: -20,
          duration: 0.4,
          ease: 'back.in(1.7)',
        })
      }

      // 通知父组件刷新列表
      onBlocked?.()
    } catch (err) {
      console.error('Failed to block news:', err)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center gap-2 opacity-30">
        <div className="w-10 h-10 rounded-full bg-gray-200 animate-pulse" />
        <div className="w-10 h-10 rounded-full bg-gray-200 animate-pulse" />
        <div className="w-8 h-8 rounded-full bg-gray-200 animate-pulse" />
      </div>
    )
  }

  return (
    <div
      ref={containerRef}
      className={`flex items-center gap-2 ${className}`}
    >
      {/* 点赞按钮 */}
      <button
        ref={likeRef}
        onClick={() => handleClick('like')}
        className={`
          group relative flex items-center gap-1.5 px-3 py-2 rounded-full
          transition-all duration-200
          ${!user
            ? 'bg-neutral-100 text-neutral-400 cursor-pointer hover:bg-neutral-200'
            : isLiked
              ? 'bg-gradient-to-br from-orange-400 to-orange-500 text-white shadow-md shadow-orange-200'
              : 'bg-white text-gray-500 hover:text-orange-500 border border-gray-200 hover:border-orange-300 hover:shadow-sm'
          }
        `}
        aria-label={isLiked ? '取消点赞' : '点赞'}
      >
        {!user && !isLiked ? (
          <LogIn size={16} />
        ) : (
          <Heart size={18} fill={isLiked ? 'currentColor' : 'none'} strokeWidth={2} />
        )}
        <span className="text-xs font-medium tabular-nums">
          {likeCount > 0 ? likeCount : ''}
        </span>
        {!user && !isLiked && (
          <span className="text-xs ml-0.5">登录</span>
        )}
      </button>

      {/* 收藏按钮 */}
      <button
        ref={bookmarkRef}
        onClick={() => handleClick('bookmark')}
        className={`
          group relative flex items-center gap-1.5 px-3 py-2 rounded-full
          transition-all duration-200
          ${!user
            ? 'bg-neutral-100 text-neutral-400 cursor-pointer hover:bg-neutral-200'
            : isBookmarked
              ? 'bg-gradient-to-br from-orange-400 to-orange-500 text-white shadow-md shadow-orange-200'
              : 'bg-white text-gray-500 hover:text-orange-500 border border-gray-200 hover:border-orange-300 hover:shadow-sm'
          }
        `}
        aria-label={isBookmarked ? '取消收藏' : '收藏'}
      >
        {!user && !isBookmarked ? (
          <LogIn size={16} />
        ) : (
          <Bookmark size={18} fill={isBookmarked ? 'currentColor' : 'none'} strokeWidth={2} />
        )}
        <span className="text-xs font-medium tabular-nums">
          {bookmarkCount > 0 ? bookmarkCount : ''}
        </span>
        {!user && !isBookmarked && (
          <span className="text-xs ml-0.5">登录</span>
        )}
      </button>

      {/* 屏蔽按钮 — 仅登录用户可见 */}
      {user && !isBlocked && (
        <button
          ref={blockRef}
          onClick={() => handleClick('block')}
          className="
            flex items-center justify-center w-9 h-9 rounded-full
            bg-white text-gray-400 border border-gray-200
            hover:text-red-500 hover:border-red-300 hover:bg-red-50
            active:scale-90 transition-all duration-200
          "
          aria-label="屏蔽此新闻"
          title="屏蔽此新闻"
        >
          <EyeOff size={16} />
        </button>
      )}

      {/* 已屏蔽标记 */}
      {user && isBlocked && (
        <span className="text-xs text-red-400 flex items-center gap-1 px-2 py-1 rounded-full bg-red-50 border border-red-100">
          <EyeOff size={12} />
          已屏蔽
        </span>
      )}
    </div>
  )
}
