import { useCallback, useRef, useState } from 'react'
import type { KeyboardEvent } from 'react'
import { Link, useLocation, useParams } from 'react-router-dom'
import { ArrowLeft, Headphones, Search } from 'lucide-react'
import { useAuth } from '@/context/AuthContext'
import { useLanguage } from '@/context/useLanguage'
import { useSpeechPlayerActions, useSpeechPlayerCapabilities } from '@/context/SpeechPlayerContext'
import LoadingSpinner from '@/components/LoadingSpinner'
import AuthModal from '@/components/AuthModal'
import NewsChatAssistant from '@/components/NewsChatAssistant'
import TranslationStatus from '@/components/news-detail/TranslationStatus'
import ErrorBanner from '@/components/news-detail/ErrorBanner'
import FullContentSection from '@/components/news-detail/FullContentSection'
import MarkdownContent from '@/components/news-detail/MarkdownContent'
import FullContentFetchStatus from '@/components/news-detail/FullContentFetchStatus'
import ArticleSearchBar from '@/components/news-detail/ArticleSearchBar'
import ArticleToc from '@/components/news-detail/ArticleToc'
import ScrollToTop from '@/components/news-detail/ScrollToTop'
import FavoriteButtons from '@/components/news-detail/FavoriteButtons'
import { useNewsDetail } from '@/hooks/useNewsDetail'
import { useFullArticle } from '@/hooks/useFullArticle'
import { useTranslation } from '@/hooks/useTranslation'
import { useArticleSearch } from '@/hooks/useArticleSearch'
import { useArticleToc } from '@/hooks/useArticleToc'
import type { NewsDetail as NewsDetailRecord } from '@/types/news'

function safeReturnPath(value: unknown): string {
  if (typeof value !== 'string' || !value.startsWith('/') || value.startsWith('//')) return '/'
  return value
}

export default function NewsDetail() {
  const { id } = useParams()
  const location = useLocation()
  const locationState = location.state
  const requestedReturnTo = typeof locationState === 'object' && locationState !== null && 'from' in locationState
    ? locationState.from
    : undefined
  const returnTo = safeReturnPath(requestedReturnTo)
  const { displayMode, t } = useLanguage()
  const { user } = useAuth()
  const { news, setNews, loading, error, refetch } = useNewsDetail(id)
  const { articleLoading, articleError, handleFetchFullArticle, resumeExistingFetch, cancelFetch } = useFullArticle(id ?? '', setNews, news)
  const [authModalOpen, setAuthModalOpen] = useState(false)
  const requestFullArticle = useCallback((force = false) => {
    if (!user) {
      setAuthModalOpen(true)
      return
    }
    if (force) void handleFetchFullArticle(true)
    else void handleFetchFullArticle()
  }, [handleFetchFullArticle, user])
  const retryFullArticle = useCallback(() => requestFullArticle(), [requestFullArticle])
  const {
    translating,
    translationPaused,
    translateError,
    translationProgress,
    showOriginal,
    setShowOriginal,
    handleTranslate,
    stopTranslationWait,
  } = useTranslation(id ?? '', news, setNews, loading)

  const speechPlayer = useSpeechPlayerActions()
  const { supported: speechSupported } = useSpeechPlayerCapabilities()
  const handleSpeak = useCallback(() => {
    if (!news) return
    const isEnglishSource = news.source_language === 'en'
    const hasChineseTitle = isEnglishSource && Boolean(news.title_zh)
    const speechTitle = hasChineseTitle && displayMode === 'zh' ? news.title_zh : news.title
    speechPlayer.speak(news.id, speechTitle, displayMode)
  }, [news, displayMode, speechPlayer])

  const [searchOpen, setSearchOpen] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const articleRef = useRef<HTMLElement | null>(null)
  const { matchCount, currentIndex, goNext, goPrev } = useArticleSearch(articleRef, searchQuery)
  const { headings, activeId } = useArticleToc(articleRef, [news?.full_content_zh, showOriginal])

  function handleGlobalKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if ((event.metaKey || event.ctrlKey) && event.key === 'f') {
      event.preventDefault()
      setSearchOpen(true)
    }
  }

  if (loading) return <LoadingSpinner />

  if (!news) {
    return (
      <div className="py-20 text-center text-gray-400">
        {error ? (
          <>
            <p role="alert" className="text-red-700">新闻加载失败，请重试。</p>
            <button type="button" className="mt-2 text-blue-600 underline" onClick={() => void refetch()}>重试</button>
          </>
        ) : (
          <p>{t.notFound}</p>
        )}
        <Link to={returnTo} className="mt-2 inline-block text-blue-600">{t.backHome}</Link>
      </div>
    )
  }

  const isEnglishSource = news.source_language === 'en'
  const hasTerminalFetchFailure = ['network_error', 'validation_failed', 'failed'].includes(news.full_content_fetch_status || '')
  const hasChineseTitle = isEnglishSource && Boolean(news.title_zh)
  let displayTitle: string
  let displayContent: string
  let displaySubtitle: string | null

  if (!hasChineseTitle) {
    displayTitle = news.title
    displayContent = news.content
    displaySubtitle = null
  } else if (displayMode === 'zh') {
    displayTitle = news.title_zh
    displayContent = news.content_zh || news.content
    displaySubtitle = null
  } else if (displayMode === 'bilingual') {
    displayTitle = news.title
    displayContent = news.content_zh || news.content
    displaySubtitle = news.title_zh
  } else {
    displayTitle = news.title
    displayContent = news.content
    displaySubtitle = null
  }

  return (
    <div onKeyDown={handleGlobalKeyDown}>
      {searchOpen && (
        <ArticleSearchBar
          query={searchQuery}
          onQueryChange={setSearchQuery}
          matchCount={matchCount}
          currentIndex={currentIndex}
          onGoNext={goNext}
          onGoPrev={goPrev}
          onClose={() => { setSearchOpen(false); setSearchQuery('') }}
        />
      )}

      <div className={`mx-auto w-full max-w-3xl overflow-x-hidden px-4 pb-28 pt-4 sm:pb-10 sm:pt-6 ${searchOpen ? 'pt-16' : ''}`}>
        <nav className="mb-8 flex items-center justify-between">
          <Link to={returnTo} className="inline-flex items-center gap-1.5 text-sm text-neutral-500 transition-colors hover:text-neutral-900">
            <ArrowLeft className="size-3.5" />{t.backToList}
          </Link>
          {!searchOpen && (
            <div className="flex items-center gap-1">
              {speechSupported && (
                <button type="button" onClick={handleSpeak} aria-label="语音播报" className="rounded-xl p-2 transition-colors hover:bg-neutral-100 active:bg-neutral-200">
                  <Headphones className="size-4.5 text-neutral-400" />
                </button>
              )}
              <button type="button" onClick={() => setSearchOpen(true)} aria-label="搜索文章内容" className="-mr-2 rounded-xl p-2 transition-colors hover:bg-neutral-100 active:bg-neutral-200">
                <Search className="size-[18px] text-neutral-400" />
              </button>
            </div>
          )}
        </nav>

        <article ref={articleRef} className="w-full min-w-0 break-words">
          <ArticleHeader news={news} displayTitle={displayTitle} displaySubtitle={displaySubtitle} isEnglishSource={isEnglishSource} />

          <FavoriteButtons newsId={news.id} className="mb-6 mt-4" onAuthRequired={() => setAuthModalOpen(true)} />

          {news.cover_image && <img src={news.cover_image} alt={displayTitle} className="mb-8 w-full rounded-2xl shadow-sm" />}

          <FullContentFetchStatus news={news} articleLoading={articleLoading} onFetch={retryFullArticle} onResume={resumeExistingFetch} onCancel={cancelFetch} />
          {articleError && !hasTerminalFetchFailure && <ErrorBanner message={articleError} onRetry={retryFullArticle} />}

          {news.full_content && (
            <FullContentSection
              news={news}
              translating={translating}
              translationPaused={translationPaused}
              translateError={translateError}
              translationProgress={translationProgress}
              showOriginal={showOriginal}
              onToggleOriginal={setShowOriginal}
              onTranslate={() => handleTranslate(Boolean(news.full_content_zh))}
              onRetryTranslate={() => handleTranslate(true)}
              onResumeTranslation={() => handleTranslate(false)}
              onStopTranslation={stopTranslationWait}
              onRefetch={() => requestFullArticle(true)}
              refetching={articleLoading}
              onCancelRefetch={cancelFetch}
            />
          )}

          <div className="w-full overflow-x-hidden leading-relaxed text-gray-700">
            <div className="w-full max-w-full overflow-hidden"><MarkdownContent content={displayContent || ''} legacySummarySpacing /></div>
          </div>

          <div className="mt-10 border-t border-neutral-100 pt-6">
            <a href={news.url} target="_blank" rel="noreferrer" className="text-sm text-neutral-400 transition-colors hover:text-neutral-600">{t.readOriginal} →</a>
          </div>
        </article>
        <NewsChatAssistant newsId={id ?? String(news.id)} />
      </div>

      <ArticleToc headings={headings} activeId={activeId} />
      <ScrollToTop />
      {authModalOpen && <AuthModal onClose={() => setAuthModalOpen(false)} />}
    </div>
  )
}

function ArticleHeader({ news, displayTitle, displaySubtitle, isEnglishSource }: {
  news: NewsDetailRecord
  displayTitle: string
  displaySubtitle: string | null
  isEnglishSource: boolean
}) {
  const author = news.author?.trim()
  const sourceName = news.source_name?.trim()

  return (
    <header className="mb-8">
      <div className="mb-4 flex flex-wrap items-center gap-1.5">
        <span className="inline-flex h-6 items-center rounded-full bg-neutral-100 px-2.5 text-[11px] font-medium uppercase tracking-wide text-neutral-600">{news.category_name}</span>
        {isEnglishSource && <TranslationStatus news={news} />}
      </div>

      <h1 className="mb-3 text-[1.625rem] font-bold leading-snug tracking-tight text-neutral-900 sm:text-3xl">{displayTitle}</h1>
      {displaySubtitle && <p className="mb-4 text-[13px] leading-relaxed text-neutral-400">{displaySubtitle}</p>}

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[13px] text-neutral-500">
        {author && author !== sourceName && <span className="flex items-center gap-1"><span className="text-neutral-700">{author}</span></span>}
        {sourceName && <span>{sourceName}</span>}
        <span className="flex items-center gap-1">
          <time>{new Date(news.publish_time).toLocaleDateString('zh-CN', { year: 'numeric', month: 'long', day: 'numeric' })}</time>
        </span>
      </div>
    </header>
  )
}
