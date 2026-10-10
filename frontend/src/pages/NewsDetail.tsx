import { useCallback, useEffect, useRef, useState } from 'react'
import type { KeyboardEvent, MouseEvent } from 'react'
import { Link, useLocation, useParams } from 'react-router-dom'
import { ArrowLeft, MessageCircle, Search, Sparkles } from 'lucide-react'
import { useAuth } from '@/context/AuthContext'
import { useLanguage } from '@/context/useLanguage'
import { useSpeechPlayerActions, useSpeechPlayerCapabilities } from '@/context/SpeechPlayerContext'
import LoadingSpinner from '@/components/LoadingSpinner'
import AuthModal from '@/components/AuthModal'
import ChatBubbleButton from '@/components/chat/ChatBubbleButton'
import LazyNewsChatAssistant from '@/components/chat/LazyNewsChatAssistant'
import { prefetchNewsChatAssistant } from '@/components/chat/newsChatAssistantLoader'
import TranslationStatus from '@/components/news-detail/TranslationStatus'
import ErrorBanner from '@/components/news-detail/ErrorBanner'
import FullContentSection from '@/components/news-detail/FullContentSection'
import MarkdownContent from '@/components/news-detail/MarkdownContent'
import FullContentFetchStatus from '@/components/news-detail/FullContentFetchStatus'
import ArticleSearchBar from '@/components/news-detail/ArticleSearchBar'
import ArticleToc from '@/components/news-detail/ArticleToc'
import ScrollToTop from '@/components/news-detail/ScrollToTop'
import FavoriteButtons from '@/components/news-detail/FavoriteButtons'
import SpeechStartMenu from '@/components/speech/SpeechStartMenu'
import { useNewsDetail } from '@/hooks/useNewsDetail'
import { useFullArticle } from '@/hooks/useFullArticle'
import { useTranslation } from '@/hooks/useTranslation'
import { useArticleSearch } from '@/hooks/useArticleSearch'
import { useArticleToc } from '@/hooks/useArticleToc'
import type { NewsDetail as NewsDetailRecord } from '@/types/news'
import type { SpeechLanguage, SpeechScope } from '@/constants/tts'
import { useCapabilities } from '@/context/CapabilitiesContext'

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
  const { capabilities } = useCapabilities()
  const chatEnabled = capabilities.features.chat.enabled
  const fetchFullEnabled = capabilities.features.fetch_full.enabled
  const translationEnabled = capabilities.features.translation.enabled
  const ttsEnabled = capabilities.features.tts.enabled
  const { news, setNews, loading, error, refetch } = useNewsDetail(id)
  const { articleLoading, articleError, handleFetchFullArticle, resumeExistingFetch, cancelFetch } = useFullArticle(id ?? '', setNews, news)
  const [authModalOpen, setAuthModalOpen] = useState(false)
  const [assistantOpen, setAssistantOpen] = useState(false)
  const assistantOpenerRef = useRef<HTMLButtonElement | null>(null)
  const restoreAssistantFocusRef = useRef(false)
  const openAssistant = useCallback((event: MouseEvent<HTMLButtonElement>) => {
    if (!chatEnabled) return
    prefetchNewsChatAssistant()
    assistantOpenerRef.current = event.currentTarget
    setAssistantOpen(true)
  }, [chatEnabled])
  const handleAssistantOpenChange = useCallback((open: boolean) => {
    setAssistantOpen(open)
    if (open) return
    restoreAssistantFocusRef.current = true
  }, [])
  useEffect(() => {
    if (assistantOpen || !restoreAssistantFocusRef.current) return
    restoreAssistantFocusRef.current = false
    const opener = assistantOpenerRef.current
    assistantOpenerRef.current = null
    opener?.focus()
  }, [assistantOpen])
  const requestFullArticle = useCallback((force = false) => {
    if (!fetchFullEnabled) return
    if (!user) {
      setAuthModalOpen(true)
      return
    }
    if (force) void handleFetchFullArticle(true)
    else void handleFetchFullArticle()
  }, [fetchFullEnabled, handleFetchFullArticle, user])
  const retryFullArticle = useCallback(() => requestFullArticle(), [requestFullArticle])
  const {
    translating,
    translationWaitingShared,
    translationPaused,
    translateError,
    translationProgress,
    showOriginal,
    setShowOriginal,
    handleTranslate,
    cancelTranslation,
  } = useTranslation(id ?? '', news, setNews, loading)

  const speechPlayer = useSpeechPlayerActions()
  const { supported: speechSupported } = useSpeechPlayerCapabilities()
  const pendingSpeechScopeRef = useRef<SpeechScope | null>(null)
  const handleSpeak = useCallback((language: SpeechLanguage, scope: SpeechScope) => {
    if (!ttsEnabled || !news) return
    const speechTitle = language === 'zh' ? (news.title_zh || news.title) : news.title
    speechPlayer.speak(news.id, speechTitle, { language, scope })
  }, [news, speechPlayer, ttsEnabled])
  const handleTranslateAndPlay = useCallback((scope: SpeechScope) => {
    if (!ttsEnabled || !translationEnabled) return
    if (!user) {
      setAuthModalOpen(true)
      return
    }
    pendingSpeechScopeRef.current = scope
    void handleTranslate(false).then((completed) => {
      const pendingScope = pendingSpeechScopeRef.current
      if (!completed || !pendingScope) return
      pendingSpeechScopeRef.current = null
      handleSpeak('zh', pendingScope)
    })
  }, [handleSpeak, handleTranslate, translationEnabled, ttsEnabled, user])
  useEffect(() => {
    const pendingScope = pendingSpeechScopeRef.current
    if (!pendingScope || !news?.full_content_zh) return
    pendingSpeechScopeRef.current = null
    handleSpeak('zh', pendingScope)
  }, [handleSpeak, news?.full_content_zh])
  useEffect(() => {
    if (translateError) pendingSpeechScopeRef.current = null
  }, [translateError])
  const handleStopTranslation = useCallback(() => {
    pendingSpeechScopeRef.current = null
    cancelTranslation()
  }, [cancelTranslation])

  const [searchOpen, setSearchOpen] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const articleRef = useRef<HTMLElement | null>(null)
  const { matchCount, currentIndex, goNext, goPrev } = useArticleSearch(articleRef, searchQuery)
  const { headings, activeId } = useArticleToc(articleRef, [news?.full_content, news?.full_content_zh, showOriginal])

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
              {chatEnabled && <button
                type="button"
                onClick={openAssistant}
                onMouseEnter={prefetchNewsChatAssistant}
                onFocus={prefetchNewsChatAssistant}
                onPointerDown={prefetchNewsChatAssistant}
                aria-label="询问 AI 助手小闻"
                className="inline-flex h-10 items-center gap-1.5 rounded-xl px-2.5 text-xs font-medium text-neutral-500 transition-colors hover:bg-orange-50 hover:text-orange-700 active:bg-orange-100"
              >
                <MessageCircle aria-hidden="true" className="size-4" />
                <span className="hidden sm:inline">问小闻</span>
              </button>}
              {speechSupported && ttsEnabled && (
                <SpeechStartMenu
                  isEnglishSource={isEnglishSource}
                  hasOriginalFull={Boolean(news.full_content)}
                  hasChineseFull={isEnglishSource ? Boolean(news.full_content_zh) : Boolean(news.full_content)}
                  hasChineseSummary={isEnglishSource ? Boolean(news.content_zh) : Boolean(news.content)}
                  translating={translating}
                  onPlay={handleSpeak}
                  onTranslateAndPlay={handleTranslateAndPlay}
                />
              )}
              <button type="button" onClick={() => setSearchOpen(true)} aria-label="搜索文章内容" className="-mr-2 flex size-10 items-center justify-center rounded-xl transition-colors hover:bg-neutral-100 active:bg-neutral-200">
                <Search className="size-[18px] text-neutral-400" />
              </button>
            </div>
          )}
        </nav>

        <article ref={articleRef} className="w-full min-w-0 break-words">
          <ArticleHeader news={news} displayTitle={displayTitle} displaySubtitle={displaySubtitle} isEnglishSource={isEnglishSource} />

          <FavoriteButtons newsId={news.id} className="mb-6 mt-4" onAuthRequired={() => setAuthModalOpen(true)} />

          {news.cover_image && <img src={news.cover_image} alt={displayTitle} className="mb-8 w-full rounded-2xl shadow-sm" />}

          {fetchFullEnabled && <FullContentFetchStatus news={news} articleLoading={articleLoading} onFetch={retryFullArticle} onResume={resumeExistingFetch} onCancel={cancelFetch} />}
          {fetchFullEnabled && articleError && !hasTerminalFetchFailure && <ErrorBanner message={articleError} onRetry={retryFullArticle} />}

          {news.full_content && (
            <FullContentSection
              news={news}
              translating={translating}
              translationWaitingShared={translationWaitingShared}
              translationPaused={translationPaused}
              translateError={translateError}
              translationProgress={translationProgress}
              showOriginal={showOriginal}
              onToggleOriginal={setShowOriginal}
              onTranslate={() => handleTranslate(Boolean(news.full_content_zh))}
              onRetryTranslate={() => handleTranslate(Boolean(news.full_content_zh))}
              onResumeTranslation={() => handleTranslate(false)}
              onStopTranslation={handleStopTranslation}
              onRefetch={() => requestFullArticle(true)}
              refetching={articleLoading}
              onCancelRefetch={cancelFetch}
              allowFetch={fetchFullEnabled}
              allowTranslation={translationEnabled}
            />
          )}

          {!news.full_content && displayContent ? (
            <SummarySection content={displayContent} onAskAssistant={chatEnabled ? openAssistant : undefined} />
          ) : null}

          <div className="mt-10 border-t border-neutral-100 pt-6">
            <a href={news.url} target="_blank" rel="noreferrer" className="text-sm text-neutral-400 transition-colors hover:text-neutral-600">{t.readOriginal} →</a>
          </div>
        </article>
        {chatEnabled && <div hidden={assistantOpen}>
          <ChatBubbleButton onOpen={openAssistant} onIntent={prefetchNewsChatAssistant} />
        </div>}
        {chatEnabled && <LazyNewsChatAssistant
          newsId={id ?? String(news.id)}
          open={assistantOpen}
          onOpenChange={handleAssistantOpenChange}
          articleContext={{
            hasFullContent: Boolean(news.full_content),
            wordCount: news.full_content ? news.full_content.length : (news.content ? news.content.length : 0),
            title: news.title,
          }}
        />}
      </div>

      <ArticleToc headings={headings} activeId={activeId} />
      <ScrollToTop />
      {authModalOpen && <AuthModal onClose={() => setAuthModalOpen(false)} />}
    </div>
  )
}

function SummarySection({ content, onAskAssistant }: { content: string; onAskAssistant?: (event: MouseEvent<HTMLButtonElement>) => void }) {
  return (
    <section aria-labelledby="article-summary-heading" className="article-section-render w-full overflow-x-hidden rounded-3xl border border-neutral-200 bg-white px-5 py-6 shadow-[0_18px_50px_rgba(15,23,42,0.06)] sm:px-8 sm:py-8">
      <div className="mb-6 flex flex-wrap items-start justify-between gap-3 border-b border-neutral-100 pb-5">
        <div>
          <div className="mb-2 flex items-center gap-2">
            <span className="inline-flex rounded-full bg-amber-50 px-2.5 py-1 text-[11px] font-semibold tracking-wide text-amber-700">摘要模式</span>
            <span className="text-xs text-neutral-400">尚未保存完整原文</span>
          </div>
          <h2 id="article-summary-heading" data-article-toc="ignore" className="text-lg font-semibold tracking-tight text-neutral-900">内容摘要</h2>
          <p className="mt-1 text-sm leading-6 text-neutral-500">快速了解文章要点；获取原文后可阅读完整段落、列表与代码。</p>
        </div>
        {onAskAssistant && <button
          type="button"
          onClick={onAskAssistant}
          onMouseEnter={prefetchNewsChatAssistant}
          onFocus={prefetchNewsChatAssistant}
          onPointerDown={prefetchNewsChatAssistant}
          className="inline-flex h-10 items-center gap-2 rounded-full border border-orange-200 bg-orange-50 px-4 text-sm font-medium text-orange-700 transition-colors hover:bg-orange-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-orange-500 focus-visible:ring-offset-2"
        >
          <Sparkles aria-hidden="true" className="size-4" />
          基于摘要提问
        </button>}
      </div>
      <div className="summary-markdown w-full max-w-full overflow-hidden text-neutral-700">
        <MarkdownContent content={content} legacySummarySpacing />
      </div>
    </section>
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
