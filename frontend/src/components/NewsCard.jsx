import { Link } from 'react-router-dom'
import { EyeOff } from 'lucide-react'
import { useLanguage } from '../context/useLanguage'
import { useAuth } from '../context/AuthContext'
import { Badge } from '@/components/ui/badge'
import TranslationStatus from './news-detail/TranslationStatus'
import { blockNews } from '@/services/api'

function formatRelativeTime(dateStr, t) {
  const now = new Date()
  const date = new Date(dateStr)
  const diffMs = now - date
  const diffMin = Math.floor(diffMs / 60000)
  if (diffMin < 1) return t.justNow
  if (diffMin < 60) return `${diffMin} ${t.minAgo}`
  const diffHr = Math.floor(diffMin / 60)
  if (diffHr < 24) return `${diffHr} ${t.hrAgo}`
  const diffDay = Math.floor(diffHr / 24)
  if (diffDay < 7) return `${diffDay} ${t.dayAgo}`
  return date.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })
}

/**
 * Resolve display text based on displayMode:
 *   'zh'        → Chinese (fallback original)
 *   'original'  → Original language only
 *   'bilingual' → Original title, with Chinese subtitle below
 */
function resolveDisplay(news, displayMode) {
  const isEn = news.source_language === 'en'
  const hasZh = isEn && !!news.title_zh

  if (!hasZh) {
    // No translation available — always show original
    return { title: news.title, subtitle: null, content: news.content }
  }

  switch (displayMode) {
    case 'zh':
      return { title: news.title_zh, subtitle: null, content: news.content_zh || news.content }
    case 'bilingual':
      return { title: news.title, subtitle: news.title_zh, content: news.content_zh || news.content }
    case 'original':
    default:
      return { title: news.title, subtitle: null, content: news.content }
  }
}

export default function NewsCard({ news, onRemoved }) {
  const { displayMode, t } = useLanguage()
  const { user } = useAuth()
  const { title, subtitle, content } = resolveDisplay(news, displayMode)

  const handleBlock = async (e) => {
    e.preventDefault()
    e.stopPropagation()
    if (!user) return
    try {
      await blockNews(news.id)
      onRemoved?.(news.id)
    } catch (err) {
      console.error('Failed to block:', err)
    }
  }

  return (
    <Link
      to={`/news/${news.id}`}
      className="group block bg-white rounded-xl border border-gray-200 overflow-hidden hover:shadow-md hover:border-gray-300 transition-all duration-200 relative"
    >
      {news.cover_image && (
        <div className="aspect-video bg-gray-100 overflow-hidden">
          <img
            src={news.cover_image}
            alt={title}
            className="w-full h-full object-cover"
            loading="lazy"
          />
        </div>
      )}
      <div className="p-4">
        <div className="flex items-start justify-between gap-2 mb-2">
          <div className="flex-1 min-w-0">
            <h2 className="text-base font-semibold text-gray-900 line-clamp-2">
              {title}
            </h2>
            {subtitle && (
              <p className="text-xs text-gray-400 line-clamp-1 mt-0.5 leading-tight">
                {subtitle}
              </p>
            )}
          </div>
          {/* Compact translation badge — null when translation succeeded */}
          <TranslationStatus news={news} size="compact" />
        </div>
        <p className="text-sm text-gray-500 line-clamp-2 mb-3">
          {content?.slice(0, 120)}...
        </p>
        <div className="flex items-center justify-between text-xs text-gray-400">
          <Badge variant="blue" className="px-2 py-0.5 rounded">{news.category_name}</Badge>
          <div className="flex items-center gap-2">
            <span>{news.source_name}</span>
            <span>{formatRelativeTime(news.publish_time, t)}</span>
          </div>
        </div>
      </div>

      {/* 屏蔽按钮 — 仅登录用户可见 */}
      {user && (
        <button
          onClick={handleBlock}
          className="
            absolute top-2 right-2 w-7 h-7 rounded-full
            bg-white/80 backdrop-blur-sm border border-gray-200
            flex items-center justify-center
            text-gray-400 hover:text-red-500 hover:border-red-300 hover:bg-red-50
            active:scale-90 transition-all duration-200
            z-10
          "
          aria-label="屏蔽此新闻"
          title="屏蔽此新闻"
        >
          <EyeOff size={13} />
        </button>
      )}
    </Link>
  )
}
