import type { MouseEvent } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Link, useLocation } from 'react-router-dom'
import { EyeOff, FileText } from 'lucide-react'
import { useLanguage } from '@/context/useLanguage'
import { useAuth } from '@/context/AuthContext'
import { Badge } from '@/components/ui/badge'
import TranslationStatus from '@/components/news-detail/TranslationStatus'
import { useBlockNews } from '@/hooks/useNewsMutations'
import { newsDetailOptions } from '@/services/newsQueries'
import type { DisplayMode, NewsSummary } from '@/types/news'
import { formatUnverifiedNewsTime } from '@/utils/newsTime'
import { hasReadableFullContent, hasPendingFullContentTask } from '@/types/news'
import { useCapability } from '@/context/CapabilitiesContext'

interface NewsCardProps {
  news: NewsSummary
  onBlockStart?: (newsId: number, viewerId: number) => number
  onBlocked?: (target: BlockedNewsTarget) => void
}

export interface BlockedNewsTarget {
  newsId: number
  viewerId: number
  version: number
}

function ContentStatus({ news, lang }: { news: NewsSummary; lang: 'zh' | 'en' }) {
  if (hasReadableFullContent(news)) {
    return <Badge variant="outline" className="border-border bg-secondary text-muted-foreground rounded-full"><FileText aria-hidden="true" />{lang === 'en' ? 'Full article' : '有全文'}</Badge>
  }
  if (hasPendingFullContentTask(news)) {
    return <Badge variant="outline" className="border-border bg-secondary text-muted-foreground rounded-full">{lang === 'en' ? 'Fetching' : '获取全文中'}</Badge>
  }
  return <Badge variant="outline" className="border-border bg-secondary text-muted-foreground rounded-full">{lang === 'en' ? 'Summary' : '摘要'}</Badge>
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
  if (!hasChineseTranslation) return { title: news.title, subtitle: null, content: news.summary }
  if (displayMode === 'zh') return { title: news.title_zh, subtitle: null, content: news.summary_zh || news.summary }
  if (displayMode === 'bilingual') return { title: news.title, subtitle: news.title_zh, content: news.summary_zh || news.summary }
  return { title: news.title, subtitle: null, content: news.summary }
}

function cleanSummary(rawText: string): string {
  if (!rawText) return ''
  return rawText
    .replace(/&nbsp;/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/HN Score:\s*\d+\s*\|\s*Comments:\s*\d+/g, '')
    .replace(/\|\s*Total Stars:\s*\d+/g, '')
    .trim()
}

export default function NewsCard({ news, onBlockStart, onBlocked }: NewsCardProps) {
  const { displayMode, t, lang } = useLanguage()
  const { user } = useAuth()
  const { enabled: blockedNewsEnabled } = useCapability('blocked_news')
  const queryClient = useQueryClient()
  const location = useLocation()
  const returnTo = `${location.pathname}${location.search}${location.hash}`
  const blockMutation = useBlockNews()
  const { title, subtitle, content } = resolveDisplay(news, displayMode)
  const cleanedContent = content ? cleanSummary(content) : ''
  const viewerId: number | string = user?.id ?? 'anonymous'

  function prefetchDetail() {
    void queryClient.prefetchQuery(newsDetailOptions(news.id, lang, viewerId))
  }

  async function handleBlock(event: MouseEvent<HTMLButtonElement>) {
    event.preventDefault()
    event.stopPropagation()
    if (!user || !blockedNewsEnabled) return
    const version = onBlockStart?.(news.id, user.id) ?? 0
    try {
      await blockMutation.mutateAsync({ newsId: news.id, viewerId: user.id })
      onBlocked?.({ newsId: news.id, viewerId: user.id, version })
    } catch {
      // Inline feedback below the control is sufficient for this action.
    }
  }

  return (
    <article className={`news-card-render group relative overflow-hidden rounded-2xl border border-border bg-card transition-[border-color,box-shadow,transform] duration-200 hover:-translate-y-0.5 hover:border-primary/30 hover:shadow-md ${news.cover_image ? 'news-card-has-image' : 'news-card-no-image'}`}>
      <Link id={`news-card-${news.id}`} to={`/news/${news.id}`} state={{ from: returnTo }} className="block focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary" onMouseEnter={prefetchDetail} onFocus={prefetchDetail}>
        {news.cover_image && <div className="news-card-image aspect-video overflow-hidden bg-muted"><img src={news.cover_image} alt="" className="h-full w-full object-cover" loading="lazy" /></div>}
        <div className={`news-card-body p-4 ${user && blockedNewsEnabled ? 'pr-12' : ''}`}>
          <div className="news-card-meta mb-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
            <span className="max-w-48 truncate font-semibold text-primary">{news.source_name}</span>
            <span aria-hidden="true">·</span>
            <span>{news.publish_time_inferred ? formatUnverifiedNewsTime(news.publish_time, 'compact') : formatRelativeTime(news.publish_time, t)}</span>
          </div>
          <div className="mb-2 flex items-start justify-between gap-3">
            <div className="min-w-0 flex-1">
              <h2 className="line-clamp-2 text-base font-semibold leading-snug text-foreground transition-colors group-hover:text-primary ">{title}</h2>
              {subtitle && <p className="mt-0.5 line-clamp-1 text-xs leading-tight text-muted-foreground">{subtitle}</p>}
            </div>
          </div>
          {!cleanedContent && <p className="news-card-summary mb-3 text-xs text-muted-foreground">来源未提供摘要</p>}
          {news.is_medical && <p className="mb-2 text-xs text-muted-foreground">新闻资讯，不构成医疗建议</p>}
          {(news.channel_names?.filter(name => name !== news.source_name).length ?? 0) > 0 && <p className="mb-2 text-xs text-muted-foreground">同时收录于 {news.channel_names?.filter(name => name !== news.source_name).join('、')}</p>}
          {cleanedContent && <p className="news-card-summary mb-4 line-clamp-3 text-sm leading-relaxed text-muted-foreground">{cleanedContent.slice(0, 180)}{cleanedContent.length > 180 ? '…' : ''}</p>}
          <div className="news-card-footer flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <Badge variant="outline" className="border-border bg-secondary text-muted-foreground rounded-full px-2 py-0.5">{news.category_name}</Badge>
            <span className="news-card-content-status"><ContentStatus news={news} lang={lang} /></span>
            <span className="ml-auto"><TranslationStatus news={news} size="compact" /></span>
          </div>
        </div>
      </Link>
      {user && blockedNewsEnabled && (
        <div className="absolute right-2 top-2 z-10">
          <button type="button" onClick={handleBlock} disabled={blockMutation.isPending} className="flex size-8 items-center justify-center rounded-full border border-border bg-card/90 text-muted-foreground backdrop-blur-sm transition-colors hover:border-destructive/30 hover:bg-destructive/10 hover:text-destructive disabled:opacity-50" aria-label={lang === 'en' ? 'Block this news' : '屏蔽此新闻'} title={lang === 'en' ? 'Block this news' : '屏蔽此新闻'}>
            <EyeOff size={13} />
          </button>
          {blockMutation.isError && <p className="absolute right-0 top-9 w-40 rounded bg-card p-2 text-xs text-destructive shadow" role="alert">{lang === 'en' ? 'Could not block this news.' : '屏蔽失败，请重试。'}</p>}
        </div>
      )}
    </article>
  )
}
