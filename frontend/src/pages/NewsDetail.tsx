import { contentCompletenessLabel } from '@/lib/contentCompleteness'
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
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
import PrivateTranslationPanel from '@/components/news-detail/PrivateTranslationPanel'
import type { PrivateTranslationTask } from '@/services/privateTranslationApi'
import TranslationStatus from '@/components/news-detail/TranslationStatus'
import ErrorBanner from '@/components/news-detail/ErrorBanner'
import FullContentSection from '@/components/news-detail/FullContentSection'
import MarkdownContent from '@/components/news-detail/MarkdownContent'
import FullContentFetchStatus from '@/components/news-detail/FullContentFetchStatus'
import ArticleSearchBar from '@/components/news-detail/ArticleSearchBar'
import ArticleToc from '@/components/news-detail/ArticleToc'
import ScrollToTop from '@/components/news-detail/ScrollToTop'
import FavoriteButtons from '@/components/news-detail/FavoriteButtons'
import ReadStateButton from '@/components/news-detail/ReadStateButton'
import SpeechStartMenu from '@/components/speech/SpeechStartMenu'
import { useNewsDetail } from '@/hooks/useNewsDetail'
import { useFullArticle } from '@/hooks/useFullArticle'
import { hasReadableFullContent, hasPendingFullContentTask } from '@/types/news'
import { useDefaultAIModel } from '@/hooks/useDefaultAIModel'
import { useTranslation } from '@/hooks/useTranslation'
import { useArticleSearch } from '@/hooks/useArticleSearch'
import { useArticleToc } from '@/hooks/useArticleToc'
import type { NewsDetail as NewsDetailRecord } from '@/types/news'
import { formatUnverifiedNewsTime } from '@/utils/newsTime'
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
  const privateSelectionKey = `${id ?? ''}:${user?.id ?? 'anonymous'}`
  const [privateSelection, setPrivateSelection] = useState<{ key: string; resultId: number | null } | null>(null)
  const selectedPrivateResultId = privateSelection?.key === privateSelectionKey ? privateSelection.resultId : null
  const toggleOriginal = (showOriginal: boolean) => {
    if (showOriginal) setPrivateSelection({ key: privateSelectionKey, resultId: null })
    setShowOriginal(showOriginal)
  }
  const { capabilities } = useCapabilities()
  const chatEnabled = capabilities.features.chat.enabled
  const fetchFullEnabled = capabilities.features.fetch_full.enabled
  const translationEnabled = capabilities.features.translation.enabled
  const ttsEnabled = capabilities.features.tts.enabled
  const translationModel = useDefaultAIModel(user?.id ?? null, 'full_translation', translationEnabled)
  // A selected personal binding (even stale) must never enter the legacy provider path.
  const personalTranslation = Boolean(user && (translationModel.isPending || translationModel.isError
    || translationModel.data?.preferences.some(item => ['default', 'full_translation'].includes(item.task_kind) && item.model_config_id)))
  const translationButtonRef = useRef<HTMLDivElement>(null)
  const openPrivateTranslation = useCallback(() => {
    translationButtonRef.current?.querySelector<HTMLButtonElement>('button')?.click()
  }, [])
  const { news, setNews, loading, error, refetch } = useNewsDetail(id)
  const privateTaskKey = `${privateSelectionKey}:${news?.full_content_revision ?? 0}`
  const [privateTaskState, setPrivateTaskState] = useState<{ key: string; task: PrivateTranslationTask | null } | null>(null)
  const privateTask = privateTaskState?.key === privateTaskKey ? privateTaskState.task : null
  const receivePrivateTask = useCallback((task: PrivateTranslationTask | null) => {
    setPrivateTaskState({ key: privateTaskKey, task })
  }, [privateTaskKey])
  const speechContextRef = useRef<object | null>(null)
  const pendingSpeechRef = useRef<{ context: object; scope: SpeechScope } | null>(null)
  // Only the committed viewer/article version may consume its waiting speech action.
  useLayoutEffect(() => {
    speechContextRef.current = {}
    return () => {
      speechContextRef.current = null
      pendingSpeechRef.current = null
    }
  }, [privateSelectionKey, news?.id, news?.full_content_revision, news?.full_content,
    news?.full_content_state, news?.body_access_granted, news?.title, news?.source_language,
    translationEnabled, ttsEnabled])

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
  }, [fetchFullEnabled, handleFetchFullArticle, setAuthModalOpen, user])
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
  } = useTranslation(id ?? '', news, setNews, loading, !personalTranslation)
  const selectPrivateResult = useCallback((resultId: number | null) => {
    pendingSpeechRef.current = null
    setPrivateSelection({ key: privateSelectionKey, resultId })
    if (resultId !== null) setShowOriginal(false)
  }, [privateSelectionKey, setShowOriginal])
  const selectedPrivateResult = selectedPrivateResultId === null
    ? undefined
    : news?.full_content_zh_private_history?.find((item) => item.result_id === selectedPrivateResultId)
  const chatTranslationMode = showOriginal ? 'original' : selectedPrivateResultId !== null ? 'result' : 'current'
  const chatTranslationLabel = showOriginal
    ? '基于原文'
    : selectedPrivateResult
      ? '基于' + (selectedPrivateResult.current_match ? '当前个人译文' : '历史个人译文（' + (selectedPrivateResult.source_title || '旧版') + '）')
      : news?.full_content_zh ? '基于当前中文译文' : '基于原文'

  const speechPlayer = useSpeechPlayerActions()
  const { supported: speechSupported } = useSpeechPlayerCapabilities()
  const handleSpeak = useCallback((language: SpeechLanguage, scope: SpeechScope, resultId: number | null = selectedPrivateResultId) => {
    if (!ttsEnabled || !news) return
    const selected = language === 'zh' && scope === 'full' && resultId !== null
      ? news.full_content_zh_private_history?.find((item) => item.result_id === resultId)
      : undefined
    const speechTitle = selected && !selected.current_match
      ? `${selected.source_title || news.title}（旧版${selected.model}译文）`
      : selected
        ? `${news.title_zh || news.title}（${selected.model}个人译文）`
        : language === 'zh' ? (news.title_zh || news.title) : news.title
    speechPlayer.speak(news.id, speechTitle, {
      language, scope,
      ...(selected ? { translationResultId: selected.result_id } : {}),
    })
  }, [news, selectedPrivateResultId, speechPlayer, ttsEnabled])
  const handleTranslateAndPlay = useCallback((scope: SpeechScope) => {
    if (!ttsEnabled || !translationEnabled) return
    if (!user) {
      setAuthModalOpen(true)
      return
    }
    if (personalTranslation) { openPrivateTranslation(); return }
    selectPrivateResult(null)
    const context = speechContextRef.current
    if (!context) return
    const pending = { context, scope }
    pendingSpeechRef.current = pending
    void handleTranslate(false).then((completed) => {
      if (!completed || pendingSpeechRef.current !== pending || speechContextRef.current !== context) return
      pendingSpeechRef.current = null
      handleSpeak('zh', pending.scope, null)
    })
  }, [handleSpeak, handleTranslate, openPrivateTranslation, personalTranslation, selectPrivateResult, setAuthModalOpen, translationEnabled, ttsEnabled, user])
  useEffect(() => {
    const pending = pendingSpeechRef.current
    if (!pending || pending.context !== speechContextRef.current || !news?.full_content_zh) return
    pendingSpeechRef.current = null
    handleSpeak('zh', pending.scope, null)
  }, [handleSpeak, news?.full_content_zh])
  useEffect(() => {
    if (translateError) pendingSpeechRef.current = null
  }, [translateError])
  const handleStopTranslation = useCallback(() => {
    pendingSpeechRef.current = null
    cancelTranslation()
  }, [cancelTranslation])

  const [searchOpen, setSearchOpen] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const searchTriggerRef = useRef<HTMLButtonElement | null>(null)
  const returnSearchFocusRef = useRef(false)
  const closeSearch = useCallback(() => {
    returnSearchFocusRef.current = true
    setSearchOpen(false)
    setSearchQuery('')
  }, [])
  useEffect(() => {
    if (searchOpen || !returnSearchFocusRef.current) return
    returnSearchFocusRef.current = false
    searchTriggerRef.current?.focus()
  }, [searchOpen])
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
      <div className="py-20 text-center text-muted-foreground">
        {error ? (
          <>
            <p role="alert" className="text-destructive">新闻加载失败，请重试。</p>
            <button type="button" className="mt-2 text-primary underline" onClick={() => void refetch()}>重试</button>
          </>
        ) : (
          <p>{t.notFound}</p>
        )}
        <Link to={returnTo} className="mt-2 inline-block text-primary">{t.backHome}</Link>
      </div>
    )
  }

  const readableBody = hasReadableFullContent(news)
  const isEnglishSource = news.source_language === 'en'
  const canRetryPolicyBlockedBody = news.full_content_fetch_status === 'unsupported' && news.body_access_granted && news.can_fetch_full_content
  const hasTerminalFetchFailure = !canRetryPolicyBlockedBody && !hasPendingFullContentTask(news) && ['network_error', 'validation_failed', 'failed', 'blocked', 'unsupported'].includes(news.full_content_fetch_status || '')
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
    <div className="article-detail" onKeyDown={handleGlobalKeyDown}>
      {searchOpen && (
        <ArticleSearchBar
          query={searchQuery}
          onQueryChange={setSearchQuery}
          matchCount={matchCount}
          currentIndex={currentIndex}
          onGoNext={goNext}
          onGoPrev={goPrev}
          onClose={closeSearch}
        />
      )}

      <div className={`mx-auto w-full max-w-5xl overflow-x-hidden px-4 pb-28 pt-4 sm:px-6 sm:pb-10 sm:pt-6 ${searchOpen ? 'pt-16' : ''}`}>
        <nav className="mb-8 flex items-center justify-between">
          <Link to={returnTo} state={{ restoreArticleId: news.id }} className="inline-flex items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground">
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
                className="inline-flex h-10 items-center gap-1.5 rounded-xl px-2.5 text-xs font-medium text-muted-foreground transition-colors hover:bg-primary/10 hover:text-primary active:bg-primary/10"
              >
                <MessageCircle aria-hidden="true" className="size-4" />
                <span className="hidden sm:inline">问小闻</span>
              </button>}
              {speechSupported && ttsEnabled && (
                <SpeechStartMenu
                  isEnglishSource={isEnglishSource}
                  hasOriginalFull={readableBody}
                  hasChineseFull={readableBody && (isEnglishSource ? Boolean(news.full_content_zh) : true)}
                  hasChineseSummary={isEnglishSource ? Boolean(news.content_zh) : Boolean(news.content)}
                  translating={translating}
                  onPlay={handleSpeak}
                  onTranslateAndPlay={handleTranslateAndPlay}
                />
              )}
              <button ref={searchTriggerRef} type="button" onClick={() => setSearchOpen(true)} aria-label="搜索文章内容" className="-mr-2 flex size-10 items-center justify-center rounded-xl transition-colors hover:bg-secondary active:bg-secondary">
                <Search className="size-[18px] text-muted-foreground" />
              </button>
            </div>
          )}
        </nav>

        <article ref={articleRef} className="w-full min-w-0 break-words">
          <p className="mb-3 text-xs text-muted-foreground">{contentCompletenessLabel(readableBody, news.full_content_completeness)}</p>
          <ArticleHeader news={news} displayTitle={displayTitle} displaySubtitle={displaySubtitle} isEnglishSource={isEnglishSource} />

          <div className="mb-6 mt-4 flex flex-wrap items-center gap-3">
            <FavoriteButtons newsId={news.id} onAuthRequired={() => setAuthModalOpen(true)} />
            <ReadStateButton key={news.id} newsId={news.id} />
          </div>


          {news.is_medical && <p role="note" className="mb-4 text-sm text-muted-foreground">新闻资讯，不构成医疗建议。</p>}
          {fetchFullEnabled && <FullContentFetchStatus news={news} articleLoading={articleLoading} onFetch={retryFullArticle} onResume={resumeExistingFetch} onCancel={cancelFetch} />}
          {fetchFullEnabled && articleError && !hasTerminalFetchFailure && <ErrorBanner message={articleError} onRetry={retryFullArticle} />}

          {readableBody && (
            <FullContentSection
              news={news}
              translating={translating}
              translationWaitingShared={translationWaitingShared}
              translationPaused={translationPaused}
              translateError={personalTranslation && translateError === '个人 AI 连接已保存；请等待模型与用途配置完成。' ? '' : translateError}
              translationProgress={translationProgress}
              privateTask={personalTranslation ? privateTask : null}
              translationControls={personalTranslation && translationEnabled && user ? <div ref={translationButtonRef}><PrivateTranslationPanel
                viewer={user.id} newsId={news.id} sourceRevision={news.full_content_revision ?? 0}
                sourceMarkdown={news.full_content} onTaskChange={receivePrivateTask} onStart={() => { selectPrivateResult(null); setShowOriginal(false) }} /></div> : undefined}
              showOriginal={showOriginal}
              onToggleOriginal={toggleOriginal}
              selectedPrivateResultId={selectedPrivateResultId}
              onSelectPrivateResult={selectPrivateResult}
              onTranslate={() => { selectPrivateResult(null); return personalTranslation ? openPrivateTranslation() : handleTranslate(Boolean(news.full_content_zh)) }}
              onRetryTranslate={() => { selectPrivateResult(null); return personalTranslation ? openPrivateTranslation() : handleTranslate(Boolean(news.full_content_zh)) }}
              onResumeTranslation={() => handleTranslate(false)}
              onStopTranslation={handleStopTranslation}
              onRefetch={() => requestFullArticle(true)}
              refetching={articleLoading}
              onCancelRefetch={cancelFetch}
              allowFetch={fetchFullEnabled && news.can_fetch_full_content !== false}
              allowTranslation={translationEnabled}
            />
          )}



          {!readableBody && displayContent ? (
            <SummarySection content={displayContent} readingPolicy={news.body_access_granted ? 'standard' : news.reading_policy} onAskAssistant={chatEnabled ? openAssistant : undefined} />
          ) : null}

          <div className="mt-10 border-t border-border pt-6">
            <>{news.full_content_error_code === 'invalid_identity' ? <span className="text-sm text-muted-foreground">链接待核验</span> : <a href={news.url} target="_blank" rel="noreferrer" className="text-sm text-muted-foreground transition-colors hover:text-muted-foreground">{t.readOriginal}</a>}</>
          </div>
        </article>
        {chatEnabled && <div hidden={assistantOpen}>
          <ChatBubbleButton onOpen={openAssistant} onIntent={prefetchNewsChatAssistant} />
        </div>}
        {chatEnabled && <LazyNewsChatAssistant
          newsId={id ?? String(news.id)}
          open={assistantOpen}
          onOpenChange={handleAssistantOpenChange}
          translationResultId={selectedPrivateResultId}
          translationMode={chatTranslationMode}
          translationLabel={chatTranslationLabel}
          articleContext={{
            hasFullContent: readableBody,
            completeness: news.full_content_completeness,
            wordCount: readableBody ? news.full_content.length : (news.content ? news.content.length : 0),
            contentRevision: news.full_content_revision ?? 0,
            title: news.title,
            isMedical: news.is_medical,
            sourceUrl: news.url,
          }}
        />}
      </div>

      <ArticleToc headings={headings} activeId={activeId} />
      <ScrollToTop />
      {authModalOpen && <AuthModal onClose={() => setAuthModalOpen(false)} />}
    </div>
  )
}

function SummarySection({ content, onAskAssistant, readingPolicy }: { content: string; readingPolicy?: import('@/types/news').ReadingPolicy; onAskAssistant?: (event: MouseEvent<HTMLButtonElement>) => void }) {
  return (
    <section aria-labelledby="article-summary-heading" className="article-section-render w-full overflow-x-hidden rounded-3xl border border-border bg-card px-5 py-6 shadow-none sm:px-8 sm:py-8">
      <div className="mb-6 flex flex-wrap items-start justify-between gap-3 border-b border-border pb-5">
        <div>
          <div className="mb-2 flex items-center gap-2">
            <span className="inline-flex rounded-full bg-primary/10 px-2.5 py-1 text-[11px] font-semibold tracking-wide text-primary">摘要模式</span>
            <span className="text-xs text-muted-foreground">{readingPolicy === 'rss_summary_only' ? '来源仅提供标题和摘要' : '尚未保存完整原文'}</span>
          </div>
          <h2 id="article-summary-heading" data-article-toc="ignore" className="text-lg font-semibold tracking-tight text-foreground">内容摘要</h2>
          <p className="mt-1 text-sm leading-6 text-muted-foreground">{readingPolicy && readingPolicy !== 'standard' ? '以下是 RSS 来源提供的公开摘要；更多内容请通过原文链接阅读。' : '快速了解文章要点；获取原文后可阅读完整段落、列表与代码。'}</p>
        </div>
        {onAskAssistant && <button
          type="button"
          onClick={onAskAssistant}
          onMouseEnter={prefetchNewsChatAssistant}
          onFocus={prefetchNewsChatAssistant}
          onPointerDown={prefetchNewsChatAssistant}
          className="inline-flex h-10 items-center gap-2 rounded-full border border-border bg-primary/10 px-4 text-sm font-medium text-primary transition-colors hover:bg-primary/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
        >
          <Sparkles aria-hidden="true" className="size-4" />
          基于摘要提问
        </button>}
      </div>
      <div className="summary-markdown w-full max-w-full overflow-hidden text-foreground">
        {content.trim() ? <MarkdownContent content={content} legacySummarySpacing /> : <p>来源未提供摘要，请前往来源网站阅读。</p>}
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
        <span className="inline-flex h-6 items-center rounded-full bg-secondary px-2.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">{news.category_name}</span>
        {isEnglishSource && <TranslationStatus news={news} />}
      </div>

      <h1 className="mb-3 text-[1.625rem] font-bold leading-snug tracking-tight text-foreground sm:text-3xl">{displayTitle}</h1>
      {displaySubtitle && <p className="mb-4 text-[13px] leading-relaxed text-muted-foreground">{displaySubtitle}</p>}

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[13px] text-muted-foreground">
        {author && author !== sourceName && <span className="flex items-center gap-1"><span className="text-foreground">{author}</span></span>}
        {sourceName && <span>{sourceName}</span>}
        <span className="flex items-center gap-1">
          <time dateTime={news.publish_time}>{news.publish_time_inferred
            ? formatUnverifiedNewsTime(news.publish_time, 'full')
            : new Date(news.publish_time).toLocaleDateString('zh-CN', { year: 'numeric', month: 'long', day: 'numeric' })}</time>
        </span>
      </div>
    </header>
  )
}
