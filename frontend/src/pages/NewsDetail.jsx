import { useState, useRef } from 'react'
import { useParams, Link } from 'react-router-dom'
import { Search, ArrowLeft } from 'lucide-react'
import { useLanguage } from '../context/useLanguage'
import LoadingSpinner from '../components/LoadingSpinner'
import NodeRenderer from 'markstream-react'
import NewsChatAssistant from '../components/NewsChatAssistant'
import TranslationStatus from '../components/news-detail/TranslationStatus'
import FetchArticleCard from '../components/news-detail/FetchArticleCard'
import FetchArticleSpinner from '../components/news-detail/FetchArticleSpinner'
import ErrorBanner from '../components/news-detail/ErrorBanner'
import FullContentSection from '../components/news-detail/FullContentSection'
import ArticleSearchBar from '../components/news-detail/ArticleSearchBar'
import ArticleToc from '../components/news-detail/ArticleToc'
import ScrollToTop from '../components/news-detail/ScrollToTop'
import { useNewsDetail } from '../hooks/useNewsDetail'
import { useFullArticle } from '../hooks/useFullArticle'
import { useTranslation } from '../hooks/useTranslation'
import { useArticleSearch } from '../hooks/useArticleSearch'
import { useArticleToc } from '../hooks/useArticleToc'
import 'markstream-react/index.css'

const CODE_BLOCK_PROPS = {
  showHeader: true, showCopyButton: true,
  showCollapseButton: false, showFontSizeButtons: false, showTooltips: true,
}

const CODE_BLOCK_THEMES = {
  themes: ['vitesse-light'],
  darkTheme: 'vitesse-light',
  lightTheme: 'vitesse-light',
  monacoOptions: {
    fontSize: 14,
    fontFamily: "'JetBrains Mono','Fira Code','Cascadia Code','Source Code Pro',Menlo,Consolas,monospace",
    padding: { top: 12, bottom: 12 },
    lineNumbers: 'on', wordWrap: 'on',
    minimap: { enabled: false },
    scrollbar: { vertical: 'hidden', horizontal: 'hidden' },
    scrollBeyondLastLine: false, overviewRulerLanes: 0,
    hideCursorInOverviewRuler: true, renderLineHighlight: 'none',
    renderLineHighlightOnlyWhenFocus: true,
    contextmenu: false, readOnly: true, domReadOnly: true,
    mouseWheelZoom: false, smoothScrolling: true,
    cursorBlinking: 'blink', cursorSmoothCaretAnimation: 'on',
  },
}

export default function NewsDetail() {
  const { id } = useParams()
  const { lang, t } = useLanguage()
  const { news, setNews, loading } = useNewsDetail(id)
  const { articleLoading, articleError, handleFetchFullArticle } = useFullArticle(id, setNews)
  const {
    translating, translateError, translationProgress,
    showOriginal, setShowOriginal, handleTranslate,
  } = useTranslation(id, news, setNews, loading)

  // Page-internal search
  const [searchOpen, setSearchOpen] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const articleRef = useRef(null)

  const { matchCount, currentIndex, goNext, goPrev } = useArticleSearch(
    articleRef,
    searchQuery,
  )

  // TOC
  const { headings, activeId } = useArticleToc(articleRef, [news?.full_content_zh, showOriginal])

  // Ctrl/Cmd+F interceptor — open our search bar instead of browser native
  function handleGlobalKeyDown(e) {
    if ((e.metaKey || e.ctrlKey) && e.key === 'f') {
      e.preventDefault()
      setSearchOpen(true)
    }
  }

  if (loading) return <LoadingSpinner />
  if (!news) {
    return (
      <div className="text-center py-20 text-gray-400">
        <p>{t.notFound}</p>
        <Link to="/" className="text-blue-600 mt-2 inline-block">{t.backHome}</Link>
      </div>
    )
  }

  const isEnglishSource = news.source_language === 'en'
  const showZh = lang === 'zh' && isEnglishSource
  const displayTitle   = showZh && news.title_zh   ? news.title_zh   : news.title
  const displayContent = showZh && news.content_zh ? news.content_zh : news.content

  return (
    <div onKeyDown={handleGlobalKeyDown}>
      {/* Search bar — sticky at top when open */}
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

      <div className={`max-w-3xl mx-auto px-4 pt-4 pb-8 sm:pt-6 sm:pb-10 w-full overflow-x-hidden ${searchOpen ? 'pt-16' : ''}`}>
        {/* ── Top nav bar ── */}
        <nav className="flex items-center justify-between mb-8">
          <Link
            to="/"
            className="inline-flex items-center gap-1.5 text-sm text-neutral-500 hover:text-neutral-900 transition-colors"
          >
            <ArrowLeft className="size-3.5" />
            {t.backToList}
          </Link>
          {!searchOpen && (
            <button
              type="button"
              onClick={() => setSearchOpen(true)}
              aria-label="搜索文章内容"
              className="p-2 -mr-2 rounded-xl hover:bg-neutral-100 active:bg-neutral-200 transition-colors"
            >
              <Search className="size-[18px] text-neutral-400" />
            </button>
          )}
        </nav>

        <article ref={articleRef} className="w-full break-words min-w-0">
          <ArticleHeader
            news={news}
            displayTitle={displayTitle}
            showOriginalTitleHint={showZh && !!news.title_zh}
            isEnglishSource={isEnglishSource}
          />

          {news.cover_image && (
            <img src={news.cover_image} alt={displayTitle} className="w-full rounded-2xl mb-8 shadow-sm" />
          )}

          {/* Fetch full article */}
          {isEnglishSource && !news.full_content && !articleLoading && (
            <FetchArticleCard onFetch={handleFetchFullArticle} />
          )}
          {articleLoading && <FetchArticleSpinner />}
          {articleError && (
            <ErrorBanner message={articleError} onRetry={handleFetchFullArticle} />
          )}

          {/* Full content + translation toolbar */}
          {news.full_content && (
            <FullContentSection
              news={news}
              translating={translating}
              translateError={translateError}
              translationProgress={translationProgress}
              showOriginal={showOriginal}
              onToggleOriginal={setShowOriginal}
              onTranslate={() => handleTranslate(!!news.full_content_zh)}
              onRetryTranslate={() => handleTranslate(true)}
            />
          )}

          {/* Summary content (NodeRenderer) */}
          <div className="text-gray-700 leading-relaxed w-full overflow-x-hidden">
            <div className="w-full max-w-full overflow-hidden">
              <NodeRenderer
                content={displayContent || ''}
                codeBlockProps={CODE_BLOCK_PROPS}
                codeBlockThemes={CODE_BLOCK_THEMES}
              />
            </div>
          </div>

          <div className="mt-10 pt-6 border-t border-neutral-100">
            <a href={news.url} target="_blank" rel="noreferrer" className="text-sm text-neutral-400 hover:text-neutral-600 transition-colors">
              {t.readOriginal} →
            </a>
          </div>
        </article>
        <NewsChatAssistant newsId={id} />
      </div>

      {/* TOC — fixed floating panel on right edge */}
      <ArticleToc headings={headings} activeId={activeId} />

      {/* Scroll-to-top — above chat assistant */}
      <ScrollToTop />
    </div>
  )
}

/* ── Article header ─────────────────────────────────────────────────── */

function ArticleHeader({ news, displayTitle, showOriginalTitleHint, isEnglishSource }) {
  return (
    <header className="mb-8">
      {/* Tags row */}
      <div className="flex items-center gap-1.5 mb-4 flex-wrap">
        <span className="inline-flex items-center h-6 px-2.5 rounded-full bg-neutral-100 text-neutral-600 text-[11px] font-medium tracking-wide uppercase">
          {news.category_name}
        </span>
        {isEnglishSource && <TranslationStatus news={news} />}
      </div>

      {/* Title */}
      <h1 className="text-[1.625rem] sm:text-3xl font-bold text-neutral-900 leading-snug tracking-tight mb-3">
        {displayTitle}
      </h1>

      {/* Original English subtitle hint */}
      {showOriginalTitleHint && (
        <p className="text-[13px] text-neutral-400 leading-relaxed mb-4">{news.title}</p>
      )}

      {/* Meta line */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[13px] text-neutral-400">
        {news.author && (
          <span className="flex items-center gap-1">
            <span className="text-neutral-600">{news.author}</span>
          </span>
        )}
        <span>{news.source_name}</span>
        <span className="flex items-center gap-1">
          <time>{new Date(news.publish_time).toLocaleDateString('zh-CN', { year: 'numeric', month: 'long', day: 'numeric' })}</time>
        </span>
      </div>
    </header>
  )
}
