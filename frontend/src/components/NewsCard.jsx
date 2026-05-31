import { Link } from 'react-router-dom'
import { useLanguage } from '../context/useLanguage'
import { Badge } from '@/components/ui/badge'
import TranslationStatus from './news-detail/TranslationStatus'

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

export default function NewsCard({ news }) {
  const { lang, t } = useLanguage()
  const showZh = lang === 'zh' && news.source_language === 'en'
  const displayTitle   = showZh && news.title_zh   ? news.title_zh   : news.title
  const displayContent = showZh && news.content_zh ? news.content_zh : news.content

  return (
    <Link
      to={`/news/${news.id}`}
      className="block bg-white rounded-xl border border-gray-200 overflow-hidden hover:shadow-md hover:border-gray-300 transition-all duration-200"
    >
      {news.cover_image && (
        <div className="aspect-video bg-gray-100 overflow-hidden">
          <img
            src={news.cover_image}
            alt={displayTitle}
            className="w-full h-full object-cover"
            loading="lazy"
          />
        </div>
      )}
      <div className="p-4">
        <div className="flex items-start justify-between gap-2 mb-2">
          <h2 className="text-base font-semibold text-gray-900 line-clamp-2 flex-1">
            {displayTitle}
          </h2>
          {/* Compact translation badge — null when translation succeeded */}
          <TranslationStatus news={news} size="compact" />
        </div>
        {showZh && news.title_zh && (
          <p className="text-xs text-gray-400 line-clamp-1 mb-2 italic">{news.title}</p>
        )}
        <p className="text-sm text-gray-500 line-clamp-2 mb-3">
          {displayContent?.slice(0, 120)}...
        </p>
        <div className="flex items-center justify-between text-xs text-gray-400">
          <Badge variant="blue" className="px-2 py-0.5 rounded">{news.category_name}</Badge>
          <div className="flex items-center gap-2">
            <span>{news.source_name}</span>
            <span>{formatRelativeTime(news.publish_time, t)}</span>
          </div>
        </div>
      </div>
    </Link>
  )
}
