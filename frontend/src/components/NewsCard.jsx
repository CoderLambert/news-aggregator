import { Link } from 'react-router-dom'
import { useLanguage } from '../context/useLanguage'

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

function TranslationBadge({ news }) {
  if (news.source_language !== 'en') return null
  if (news.translation_status === 'success' || !news.translation_status) return null

  const status = news.translation_status
  const retryCount = news.translation_retry_count || 0

  if (status === 'pending' || status === 'translating') {
    return (
      <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-amber-50 text-amber-600 border border-amber-200">
        <span className="w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse" />
        {status === 'translating' ? '翻译中' : '待翻译'}
      </span>
    )
  }

  if (status === 'network_error') {
    return (
      <span
        className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-orange-50 text-orange-600 border border-orange-200"
        title={`网络错误 (${retryCount} 次重试)`}
      >
        <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        网络错误 {retryCount > 0 && `(${retryCount}次重试)`}
      </span>
    )
  }

  if (status === 'failed') {
    return (
      <span
        className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-red-50 text-red-600 border border-red-200"
        title={`翻译失败: ${news.translation_error}`}
      >
        <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        翻译失败
      </span>
    )
  }

  return null
}

export default function NewsCard({ news }) {
  const { lang, t } = useLanguage()

  const displayTitle = (lang === 'zh' && news.source_language === 'en' && news.title_zh)
    ? news.title_zh
    : news.title

  const displayContent = (lang === 'zh' && news.source_language === 'en' && news.content_zh)
    ? news.content_zh
    : news.content

  return (
    <Link
      to={`/news/${news.id}`}
      className="block bg-white rounded-xl border border-gray-200 overflow-hidden
        hover:shadow-md hover:border-gray-300 transition-all duration-200"
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
          <TranslationBadge news={news} />
        </div>
        {lang === 'zh' && news.source_language === 'en' && news.title_zh && (
          <p className="text-xs text-gray-400 line-clamp-1 mb-2 italic">
            {news.title}
          </p>
        )}
        <p className="text-sm text-gray-500 line-clamp-2 mb-3">
          {displayContent?.slice(0, 120)}...
        </p>
        <div className="flex items-center justify-between text-xs text-gray-400">
          <span className="bg-blue-50 text-blue-600 px-2 py-0.5 rounded">
            {news.category_name}
          </span>
          <div className="flex items-center gap-2">
            <span>{news.source_name}</span>
            <span>{formatRelativeTime(news.publish_time, t)}</span>
          </div>
        </div>
      </div>
    </Link>
  )
}
