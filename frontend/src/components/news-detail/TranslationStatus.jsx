import { Loader2, WifiOff, AlertCircle } from 'lucide-react'
import { Badge } from '@/components/ui/badge'

/**
 * TranslationStatus — backend translation_status badge.
 *
 * Two presentation modes via `size`:
 *   'default' — px-2 py-1, used on the news-detail page header
 *   'compact' — px-2 py-0.5, used on news-list cards next to the title
 *
 * Returns null for status 'success' or unknown so callers can drop it
 * unconditionally into a row of badges.
 */
export default function TranslationStatus({ news, size = 'default' }) {
  const status = news.translation_status
  const retryCount = news.translation_retry_count || 0
  if (!status || status === 'success') return null

  const padding = size === 'compact' ? 'py-0.5' : 'py-1'

  if (status === 'pending' || status === 'translating') {
    const isPending = status === 'pending'
    return (
      <Badge variant="amber" className={padding}>
        {isPending
          ? <span className="size-1.5 rounded-full bg-amber-500 animate-pulse" />
          : <Loader2 className="animate-spin" />
        }
        {isPending ? (size === 'compact' ? '待翻译' : '等待翻译') : (size === 'compact' ? '翻译中' : '正在翻译...')}
      </Badge>
    )
  }

  if (status === 'network_error') {
    const detail = retryCount > 0 ? (size === 'compact' ? `(${retryCount}次重试)` : `· 已重试 ${retryCount} 次`) : ''
    return (
      <Badge
        variant="amber"
        className={`${padding} border-orange-200 bg-orange-50 text-orange-600`}
        title={`网络错误 (${retryCount} 次重试)`}
      >
        <WifiOff />
        {size === 'compact' ? `网络错误 ${detail}` : `翻译失败（网络错误）${detail}`}
      </Badge>
    )
  }

  if (status === 'failed') {
    return (
      <Badge variant="red" className={padding} title={news.translation_error}>
        <AlertCircle />
        {size === 'compact'
          ? '翻译失败'
          : `翻译失败${retryCount > 0 ? ` · 已重试 ${retryCount} 次` : ''}`}
      </Badge>
    )
  }

  return null
}
