import type { MouseEvent } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { EyeOff } from 'lucide-react'
import { useLanguage } from '@/context/useLanguage'
import { useAuth } from '@/context/AuthContext'
import { Badge } from '@/components/ui/badge'
import TranslationStatus from '@/components/news-detail/TranslationStatus'
import { useBlockNews } from '@/hooks/useNewsMutations'
import type { DisplayMode, NewsSummary } from '@/types/news'

interface NewsCardProps {
  news: NewsSummary
  onRemoved?: (newsId: number) => void
}

function formatRelativeTime(dateString: string, t: ReturnType<typeof useLanguage>['t']) {
  const differenceMinutes = Math.floor((Date.now() - new Date(dateString).getTime()) / 60_000)
  if (differenceMinutes < 1) return t.justNow
  if (differenceMinutes < 60) return `${differenceMinutes} ${t.minAgo}`
  const differenceHours = Math.floor(differenceMinutes / 60)
  if (differenceHours < 24) return `${differenceHours} ${t.hrAgo}`
  const differenceDays = Math.floor(differenceHours / 24)
  if (differenceDays < 7) return `${differenceDays} ${t.dayAgo}`
  return new Date(dateString).toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })
}

function resolveDisplay(news: NewsSummary, displayMode: DisplayMode) {
  const hasChineseTranslation = news.source_language === 'en' && Boolean(news.title_zh)
  if (!hasChineseTranslation) return { title: news.title, subtitle: null, content: news.content }
  if (displayMode === 'zh') return { title: news.title_zh, subtitle: null, content: news.content_zh || news.content }
  if (displayMode === 'bilingual') return { title: news.title, subtitle: news.title_zh, content: news.content_zh || news.content }
  return { title: news.title, subtitle: null, content: news.content }
}

export default function NewsCard({ news, onRemoved }: NewsCardProps) {
  const { displayMode, t, lang } = useLanguage()
  const { user } = useAuth()
  const location = useLocation()
  const returnTo = `${location.pathname}${location.search}${location.hash}`
  const blockMutation = useBlockNews()
  const { title, subtitle, content } = resolveDisplay(news, displayMode)

  async function handleBlock(event: MouseEvent<HTMLButtonElement>) {
    event.preventDefault()
    event.stopPropagation()
    if (!user) return
    try {
      await blockMutation.mutateAsync(news.id)
      onRemoved?.(news.id)
    } catch {
      // Inline feedback below the control is sufficient for this action.
    }
  }

  return (
    <article className="group relative overflow-hidden rounded-xl border border-gray-200 bg-white transition-all duration-200 hover:border-gray-300 hover:shadow-md">
      <Link to={`/news/${news.id}`} state={{ from: returnTo }} className="block">
        {news.cover_image && <div className="aspect-video overflow-hidden bg-gray-100"><img src={news.cover_image} alt="" className="h-full w-full object-cover" loading="lazy" /></div>}
        <div className="p-4">
          <div className="mb-2 flex items-start justify-between gap-2">
            <div className="min-w-0 flex-1">
              <h2 className="line-clamp-2 text-base font-semibold text-gray-900">{title}</h2>
              {subtitle && <p className="mt-0.5 line-clamp-1 text-xs leading-tight text-gray-400">{subtitle}</p>}
            </div>
            <TranslationStatus news={news} size="compact" />
          </div>
          <p className="mb-3 line-clamp-2 text-sm text-gray-500">{content?.slice(0, 120)}...</p>
          <div className="flex items-center justify-between text-xs text-gray-400">
            <Badge variant="blue" className="rounded px-2 py-0.5">{news.category_name}</Badge>
            <div className="flex items-center gap-2"><span>{news.source_name}</span><span>{formatRelativeTime(news.publish_time, t)}</span></div>
          </div>
        </div>
      </Link>
      {user && (
        <div className="absolute right-2 top-2 z-10">
          <button type="button" onClick={handleBlock} disabled={blockMutation.isPending} className="flex size-8 items-center justify-center rounded-full border border-gray-200 bg-white/90 text-gray-400 backdrop-blur-sm transition-colors hover:border-red-300 hover:bg-red-50 hover:text-red-500 disabled:opacity-50" aria-label={lang === 'en' ? 'Block this news' : '屏蔽此新闻'} title={lang === 'en' ? 'Block this news' : '屏蔽此新闻'}>
            <EyeOff size={13} />
          </button>
          {blockMutation.isError && <p className="absolute right-0 top-9 w-40 rounded bg-white p-2 text-xs text-red-700 shadow" role="alert">{lang === 'en' ? 'Could not block this news.' : '屏蔽失败，请重试。'}</p>}
        </div>
      )}
    </article>
  )
}
