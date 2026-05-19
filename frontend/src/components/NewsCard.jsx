import { Link } from 'react-router-dom'

function formatRelativeTime(dateStr) {
  const now = new Date()
  const date = new Date(dateStr)
  const diffMs = now - date
  const diffMin = Math.floor(diffMs / 60000)
  if (diffMin < 1) return '刚刚'
  if (diffMin < 60) return `${diffMin} 分钟前`
  const diffHr = Math.floor(diffMin / 60)
  if (diffHr < 24) return `${diffHr} 小时前`
  const diffDay = Math.floor(diffHr / 24)
  if (diffDay < 7) return `${diffDay} 天前`
  return date.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })
}

export default function NewsCard({ news }) {
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
            alt={news.title}
            className="w-full h-full object-cover"
            loading="lazy"
          />
        </div>
      )}
      <div className="p-4">
        <h2 className="text-base font-semibold text-gray-900 line-clamp-2 mb-2">
          {news.title}
        </h2>
        <p className="text-sm text-gray-500 line-clamp-2 mb-3">
          {news.content?.slice(0, 120)}...
        </p>
        <div className="flex items-center justify-between text-xs text-gray-400">
          <span className="bg-blue-50 text-blue-600 px-2 py-0.5 rounded">
            {news.category_name}
          </span>
          <div className="flex items-center gap-2">
            <span>{news.source_name}</span>
            <span>{formatRelativeTime(news.publish_time)}</span>
          </div>
        </div>
      </div>
    </Link>
  )
}
