import { useState, useRef } from 'react'
import { useParams, Link } from 'react-router-dom'
import { Search } from 'lucide-react'
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
  const { headings, activeId } = useArticleToc(articleRef)

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

      <div className={`max-w-3xl mx-auto px-4 py-6 sm:py-8 w-full overflow-x-hidden ${searchOpen ? 'pt-14' : ''}`}>
        <div className="flex items-center justify-between mb-6">
          <Link to="/" className="text-sm text-blue-600 hover:underline">
            {t.backToList}
          </Link>
          {/* Search trigger button — only when search bar is closed */}
          {!searchOpen && (
            <button
              type="button"
              onClick={() => setSearchOpen(true)}
              aria-label="搜索文章内容"
              className="p-2 rounded-lg hover:bg-neutral-100 transition-colors"
            >
              <Search className="size-4 text-neutral-500" />
            </button>
          )}
        </div>

        <article ref={articleRef} className="w-full break-words min-w-0">
          <ArticleHeader
            news={news}
            displayTitle={displayTitle}
            showOriginalTitleHint={showZh && !!news.title_zh}
            isEnglishSource={isEnglishSource}
            t={t}
          />

          {news.cover_image && (
            <img src={news.cover_image} alt={displayTitle} className="w-full rounded-xl mb-6" />
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

          <div className="mt-8 pt-6 border-t border-gray-200">
            <a href={news.url} target="_blank" rel="noreferrer" className="text-blue-600 hover:underline text-sm">
              {t.readOriginal}
            </a>
          </div>
        </article>
        <NewsChatAssistant newsId={id} />
      </div>

      {/* TOC sidebar / mobile sheet */}
      <ArticleToc headings={headings} activeId={activeId} />
    </div>
  )
}

/* ── Inline header (only used here) ───────────────────────────────────── */

function ArticleHeader({ news, displayTitle, showOriginalTitleHint, isEnglishSource, t }) {
  return (
    <header className="mb-6">
      <div className="flex items-center gap-2 mb-3">
        <span className="inline-block bg-blue-50 text-blue-600 text-xs px-2 py-1 rounded">
          {news.category_name}
        </span>
        {isEnglishSource && <TranslationStatus news={news} />}
      </div>
      <h1 className="text-2xl md:text-3xl font-bold text-gray-900 leading-tight mb-4">
        {displayTitle}
      </h1>
      {showOriginalTitleHint && (
        <p className="text-sm text-gray-400 italic mb-4">{news.title}</p>
      )}
      <div className="flex flex-wrap items-center gap-3 text-sm text-gray-500">
        {news.author && <span>{t.author}: {news.author}</span>}
        <span>{t.source}: {news.source_name}</span>
        <span>{new Date(news.publish_time).toLocaleString('zh-CN')}</span>
      </div>
    </header>
  )
}
