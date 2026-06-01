import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { Heart, Bookmark, ArrowLeft, Clock, LogIn, EyeOff, RotateCcw } from 'lucide-react'
import LoadingSpinner from '../components/LoadingSpinner'
import { fetchUserFavorites, fetchBlockedNews, unblockNews } from '../services/api'
import { useAuth } from '../context/AuthContext'
import AuthModal from '../components/AuthModal'

/**
 * FavoritesPage — 用户收藏/屏蔽列表页
 */
export default function FavoritesPage() {
  const { user } = useAuth()
  const [favorites, setFavorites] = useState([])
  const [blocked, setBlocked] = useState([])
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState('all')
  const [tab, setTab] = useState('favorites') // 'favorites' | 'blocked'
  const [showAuth, setShowAuth] = useState(false)

  useEffect(() => {
    if (!user) {
      queueMicrotask(() => setLoading(false))
      return
    }

    let cancelled = false

    const load = async () => {
      setLoading(true)
      try {
        if (tab === 'favorites') {
          const params = filter === 'all' ? {} : { type: filter }
          const data = await fetchUserFavorites(params)
          if (!cancelled) setFavorites(data.results || [])
        } else {
          const data = await fetchBlockedNews()
          if (!cancelled) setBlocked(data.results || [])
        }
      } catch (err) {
        console.error('Failed to load:', err)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    load()

    return () => { cancelled = true }
  }, [filter, tab, user])

  const handleUnblock = async (newsId) => {
    try {
      await unblockNews(newsId)
      setBlocked(prev => prev.filter(b => b.news?.id !== newsId))
    } catch (err) {
      console.error('Failed to unblock:', err)
    }
  }

  if (loading) return <LoadingSpinner />

  // 未登录状态
  if (!user) {
    return (
      <div className="max-w-3xl mx-auto px-4 pt-4 pb-8 sm:pt-6 sm:pb-10 w-full overflow-x-hidden">
        <nav className="flex items-center justify-between mb-8">
          <Link
            to="/"
            className="inline-flex items-center gap-1.5 text-sm text-neutral-500 hover:text-neutral-900 transition-colors"
          >
            <ArrowLeft className="size-3.5" />
            返回主页
          </Link>
        </nav>

        <div className="text-center py-16">
          <div className="w-20 h-20 mx-auto mb-6 rounded-full bg-neutral-100 flex items-center justify-center">
            <LogIn className="w-10 h-10 text-neutral-400" />
          </div>
          <h2 className="text-xl font-semibold text-neutral-800 mb-2">登录后查看收藏</h2>
          <p className="text-neutral-500 mb-6">登录小闻账号，收藏和点赞你感兴趣的新闻</p>
          <button
            onClick={() => setShowAuth(true)}
            className="inline-flex items-center gap-2 px-6 py-2.5 rounded-full text-sm font-medium text-white bg-gradient-to-r from-orange-400 to-pink-400 hover:from-orange-500 hover:to-pink-500 transition-all shadow-md hover:shadow-lg active:scale-[0.97]"
          >
            <LogIn className="w-4 h-4" />
            立即登录
          </button>
        </div>

        {showAuth && <AuthModal onClose={() => setShowAuth(false)} />}
      </div>
    )
  }

  return (
    <div className="max-w-3xl mx-auto px-4 pt-4 pb-8 sm:pt-6 sm:pb-10 w-full overflow-x-hidden">
      {/* 顶部导航 */}
      <nav className="flex items-center justify-between mb-6">
        <Link
          to="/"
          className="inline-flex items-center gap-1.5 text-sm text-neutral-500 hover:text-neutral-900 transition-colors"
        >
          <ArrowLeft className="size-3.5" />
          返回主页
        </Link>
        <h1 className="text-lg font-semibold text-neutral-900">
          {tab === 'favorites' ? '我的收藏' : '屏蔽管理'}
        </h1>
      </nav>

      {/* Tab 切换：收藏 / 屏蔽 */}
      <div className="flex gap-2 mb-6">
        <button
          onClick={() => setTab('favorites')}
          className={`
            px-4 py-2 rounded-full text-sm font-medium transition-all duration-200
            ${tab === 'favorites'
              ? 'bg-gradient-to-br from-orange-400 to-orange-500 text-white shadow-md shadow-orange-200'
              : 'bg-white text-gray-600 border border-gray-200 hover:border-orange-300 hover:text-orange-500'
            }
          `}
        >
          <Heart className="inline-block w-3.5 h-3.5 mr-1" fill={tab === 'favorites' ? 'currentColor' : 'none'} />
          收藏
        </button>
        <button
          onClick={() => setTab('blocked')}
          className={`
            px-4 py-2 rounded-full text-sm font-medium transition-all duration-200
            ${tab === 'blocked'
              ? 'bg-gradient-to-br from-red-400 to-red-500 text-white shadow-md shadow-red-200'
              : 'bg-white text-gray-600 border border-gray-200 hover:border-red-300 hover:text-red-500'
            }
          `}
        >
          <EyeOff className="inline-block w-3.5 h-3.5 mr-1" />
          屏蔽
        </button>
      </div>

      {/* 收藏 Tab 内容 */}
      {tab === 'favorites' && (
        <>
          {/* 筛选标签 */}
          <div className="flex gap-2 mb-6">
            {[
              { key: 'all', label: '全部' },
              { key: 'like', label: '点赞' },
              { key: 'bookmark', label: '收藏' },
            ].map(f => (
              <button
                key={f.key}
                onClick={() => setFilter(f.key)}
                className={`
                  px-4 py-2 rounded-full text-sm font-medium transition-all duration-200
                  ${filter === f.key
                    ? 'bg-gradient-to-br from-orange-400 to-orange-500 text-white shadow-md shadow-orange-200'
                    : 'bg-white text-gray-600 border border-gray-200 hover:border-orange-300 hover:text-orange-500'
                  }
                `}
              >
                {f.key === 'like' && <Heart className="inline-block w-3.5 h-3.5 mr-1" fill={filter === f.key ? 'currentColor' : 'none'} />}
                {f.key === 'bookmark' && <Bookmark className="inline-block w-3.5 h-3.5 mr-1" fill={filter === f.key ? 'currentColor' : 'none'} />}
                {f.label}
              </button>
            ))}
          </div>

          {favorites.length === 0 ? (
            <div className="text-center py-16 text-gray-400">
              <Heart className="w-16 h-16 mx-auto mb-4 opacity-30" />
              <p className="text-lg">还没有收藏内容</p>
              <p className="text-sm mt-2">去浏览新闻，看到喜欢的就点个赞吧！</p>
            </div>
          ) : (
            <div className="space-y-4">
              {favorites.map(fav => (
                <FavoriteCard key={fav.id} favorite={fav} />
              ))}
            </div>
          )}
        </>
      )}

      {/* 屏蔽 Tab 内容 */}
      {tab === 'blocked' && (
        <>
          {blocked.length === 0 ? (
            <div className="text-center py-16 text-gray-400">
              <EyeOff className="w-16 h-16 mx-auto mb-4 opacity-30" />
              <p className="text-lg">没有屏蔽内容</p>
              <p className="text-sm mt-2">不想看到的新闻可以点击屏蔽按钮隐藏</p>
            </div>
          ) : (
            <div className="space-y-3">
              {blocked.map(block => (
                <BlockedCard key={block.id} block={block} onUnblock={handleUnblock} />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}

/**
 * FavoriteCard — 单条收藏卡片
 */
function FavoriteCard({ favorite }) {
  const news = favorite.news
  const title = news?.title_zh || news?.title || '未知标题'
  const summary = news?.content_zh || news?.content || ''
  const date = favorite.created_at ? new Date(favorite.created_at).toLocaleDateString('zh-CN') : ''
  const isLiked = favorite.type === 'like'

  return (
    <Link
      to={`/news/${news?.id}`}
      className="block bg-white rounded-2xl p-5 shadow-sm hover:shadow-md transition-all duration-200 border border-gray-100 hover:border-orange-200"
    >
      <div className="flex items-start gap-3">
        <div className={`
          flex-shrink-0 w-10 h-10 rounded-full flex items-center justify-center
          ${isLiked
            ? 'bg-gradient-to-br from-orange-400 to-orange-500 text-white'
            : 'bg-gradient-to-br from-blue-400 to-blue-500 text-white'
          }
        `}>
          {isLiked ? <Heart size={18} fill="currentColor" /> : <Bookmark size={18} fill="currentColor" />}
        </div>
        <div className="flex-1 min-w-0">
          <h3 className="text-base font-semibold text-neutral-900 line-clamp-2 mb-1">{title}</h3>
          <p className="text-sm text-gray-500 line-clamp-2 mb-2">{summary.slice(0, 100)}...</p>
          <div className="flex items-center gap-3 text-xs text-gray-400">
            <span className="flex items-center gap-1"><Clock className="w-3 h-3" />{date}</span>
            {news?.source && <span className="truncate">{news.source.name}</span>}
          </div>
        </div>
      </div>
    </Link>
  )
}

/**
 * BlockedCard — 单条屏蔽卡片（带恢复按钮）
 */
function BlockedCard({ block, onUnblock }) {
  const news = block.news
  const title = news?.title_zh || news?.title || '未知标题'
  const date = block.created_at ? new Date(block.created_at).toLocaleDateString('zh-CN') : ''

  return (
    <div className="flex items-center gap-3 bg-white rounded-2xl p-4 shadow-sm border border-gray-100">
      <div className="flex-shrink-0 w-10 h-10 rounded-full flex items-center justify-center bg-gray-100 text-gray-400">
        <EyeOff size={18} />
      </div>
      <div className="flex-1 min-w-0">
        <h3 className="text-sm font-medium text-neutral-700 line-clamp-1">{title}</h3>
        <span className="text-xs text-gray-400">{date}</span>
      </div>
      <button
        onClick={() => onUnblock(news?.id)}
        className="flex items-center gap-1 px-3 py-1.5 rounded-full text-xs font-medium text-orange-600 bg-orange-50 hover:bg-orange-100 active:scale-95 transition-all"
        title="取消屏蔽"
      >
        <RotateCcw size={12} />
        恢复
      </button>
    </div>
  )
}
