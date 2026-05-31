import { useParams, Link } from 'react-router-dom'
import { useLanguage } from '../context/useLanguage'
import LoadingSpinner from '../components/LoadingSpinner'
import NodeRenderer from 'markstream-react'
import NewsChatAssistant from '../components/NewsChatAssistant'
import MarkdownContent from '../components/news-detail/MarkdownContent'
import TranslationStatus from '../components/news-detail/TranslationStatus'
import { useNewsDetail } from '../hooks/useNewsDetail'
import { useFullArticle } from '../hooks/useFullArticle'
import { useTranslation } from '../hooks/useTranslation'
import 'markstream-react/index.css'

export default function NewsDetail() {
  const { id } = useParams()
  const { lang, t } = useLanguage()
  const { news, setNews, loading } = useNewsDetail(id)
  const { articleLoading, articleError, handleFetchFullArticle } = useFullArticle(id, setNews)
  const {
    translating, translateError, translationProgress,
    showOriginal, setShowOriginal, handleTranslate,
  } = useTranslation(id, news, setNews, loading)

  if (loading) return <LoadingSpinner />
  if (!news) return (
    <div className="text-center py-20 text-gray-400">
      <p>{t.notFound}</p>
      <Link to="/" className="text-blue-600 mt-2 inline-block">{t.backHome}</Link>
    </div>
  )

  const displayTitle = (lang === 'zh' && news.source_language === 'en' && news.title_zh)
    ? news.title_zh : news.title
  const displayContent = (lang === 'zh' && news.source_language === 'en' && news.content_zh)
    ? news.content_zh : news.content

  return (
    <div className="max-w-3xl mx-auto px-4 py-6 sm:py-8 w-full overflow-x-hidden">
      <Link to="/" className="text-sm text-blue-600 hover:underline mb-6 inline-block">
        {t.backToList}
      </Link>

      <article className="w-full break-words min-w-0">
        {/* ---- Header ---- */}
        <header className="mb-6">
          <div className="flex items-center gap-2 mb-3">
            <span className="inline-block bg-blue-50 text-blue-600 text-xs px-2 py-1 rounded">
              {news.category_name}
            </span>
            {news.source_language === 'en' && <TranslationStatus news={news} />}
          </div>
          <h1 className="text-2xl md:text-3xl font-bold text-gray-900 leading-tight mb-4">
            {displayTitle}
          </h1>
          {lang === 'zh' && news.source_language === 'en' && news.title_zh && (
            <p className="text-sm text-gray-400 italic mb-4">{news.title}</p>
          )}
          <div className="flex flex-wrap items-center gap-3 text-sm text-gray-500">
            {news.author && <span>{t.author}: {news.author}</span>}
            <span>{t.source}: {news.source_name}</span>
            <span>{new Date(news.publish_time).toLocaleString('zh-CN')}</span>
          </div>
        </header>

        {news.cover_image && (
          <img src={news.cover_image} alt={displayTitle} className="w-full rounded-xl mb-6" />
        )}

        {/* ---- Fetch full article ---- */}
        {news.source_language === 'en' && !news.full_content && !articleLoading && (
          <FetchArticleCard onFetch={handleFetchFullArticle} />
        )}
        {articleLoading && <FetchArticleSpinner />}
        {articleError && (
          <ErrorBanner message={articleError} onRetry={handleFetchFullArticle} />
        )}

        {/* ---- Full content + translation ---- */}
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

        {/* ---- Summary content (NodeRenderer) ---- */}
        <div className="text-gray-700 leading-relaxed w-full overflow-x-hidden">
          <div className="w-full max-w-full overflow-hidden">
            <NodeRenderer
              content={displayContent || ''}
              codeBlockProps={{
                showHeader: true, showCopyButton: true,
                showCollapseButton: false, showFontSizeButtons: false, showTooltips: true,
              }}
              codeBlockThemes={{
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
              }}
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
  )
}

/* ── Inline sub-components ─────────────────────────────────────────────── */

function FetchArticleCard({ onFetch }) {
  return (
    <div className="mb-6 p-4 bg-gradient-to-r from-indigo-50 to-blue-50 rounded-xl border border-indigo-100">
      <div className="flex items-center gap-3 mb-3">
        <svg className="w-5 h-5 text-indigo-500 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 20H5a2 2 0 01-2-2V6a2 2 0 012-2h10a2 2 0 012 2v1m2 13a2 2 0 01-2-2V7m2 13a2 2 0 002-2V9a2 2 0 00-2-2h-2m-4-3H9M7 16h6M7 8h6v4H7V8z" />
        </svg>
        <div>
          <p className="text-sm font-medium text-gray-900">获取完整原文</p>
          <p className="text-xs text-gray-500">通过 Jina Reader 自动提取正文内容</p>
        </div>
      </div>
      <button
        onClick={onFetch}
        aria-label="加载原文"
        className="inline-flex items-center gap-2 px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-full hover:bg-indigo-700 active:scale-95 transition-all duration-200 shadow-sm hover:shadow"
      >
        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m0 0v8" />
        </svg>
        加载原文
      </button>
    </div>
  )
}

function FetchArticleSpinner() {
  return (
    <div className="mb-6 p-8 bg-gray-50 rounded-xl border border-gray-200 text-center">
      <svg className="w-8 h-8 mx-auto text-indigo-500 animate-spin mb-3" fill="none" viewBox="0 0 24 24">
        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
      </svg>
      <p className="text-sm text-gray-500">正在获取原文内容...</p>
    </div>
  )
}

function ErrorBanner({ message, onRetry }) {
  return (
    <div className="mb-6 p-4 bg-red-50 rounded-xl border border-red-200">
      <div className="flex items-center gap-2 text-red-600 text-sm">
        <svg className="w-4 h-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        <span>{message}</span>
        <button onClick={onRetry} className="ml-auto text-xs underline hover:no-underline">重试</button>
      </div>
    </div>
  )
}

function FullContentSection({
  news, translating, translateError, translationProgress,
  showOriginal, onToggleOriginal, onTranslate, onRetryTranslate,
}) {
  return (
    <div className="mb-6">
      {/* Toolbar */}
      <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <span className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded-full bg-green-50 text-green-700 border border-green-200">
            <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
            </svg>
            原文已加载
          </span>
          {news.full_content_zh && (
            <span className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded-full bg-violet-50 text-violet-700 border border-violet-200">
              <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M3 5h12M9 3v2m1.048 9.5A18.022 18.022 0 016.412 9m6.088 9h7M11 21l5-10 5 10M12.751 5C11.783 10.77 8.07 15.61 3 18.129" />
              </svg>
              已翻译
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {news.full_content_zh && (
            <LangToggle showOriginal={showOriginal} onToggle={onToggleOriginal} />
          )}
          {!translating && !translateError && (
            <TranslateButton hasTranslation={!!news.full_content_zh} onClick={onTranslate} />
          )}
        </div>
      </div>

      {/* Translating spinner / progress */}
      {translating && (
        <TranslationProgressUI progress={translationProgress} />
      )}

      {/* Translate error */}
      {translateError && (
        <ErrorBanner message={translateError} onRetry={onRetryTranslate} />
      )}

      {/* Content */}
      <div className="bg-white rounded-xl border border-gray-200 p-5 shadow-sm">
        <MarkdownContent content={showOriginal ? news.full_content : (news.full_content_zh || news.full_content)} />
      </div>
    </div>
  )
}

function LangToggle({ showOriginal, onToggle }) {
  return (
    <div className="flex bg-gray-100 rounded-full p-0.5">
      <button
        onClick={() => onToggle(false)}
        aria-label="切换中文"
        className={`px-3 py-1 text-xs rounded-full transition-all ${
          !showOriginal ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-700'
        }`}
      >中文</button>
      <button
        onClick={() => onToggle(true)}
        aria-label="切换英文"
        className={`px-3 py-1 text-xs rounded-full transition-all ${
          showOriginal ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-700'
        }`}
      >English</button>
    </div>
  )
}

function TranslateButton({ hasTranslation, onClick }) {
  return (
    <button
      onClick={onClick}
      aria-label={hasTranslation ? '重新翻译' : '翻译为中文'}
      className={`inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-full transition-all duration-200 shadow-sm hover:shadow
        ${hasTranslation
          ? 'bg-gray-100 text-gray-600 hover:bg-gray-200 border border-gray-200'
          : 'bg-violet-600 text-white hover:bg-violet-700'
        }`}
    >
      <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M3 5h12M9 3v2m1.048 9.5A18.022 18.022 0 016.412 9m6.088 9h7M11 21l5-10 5 10M12.751 5C11.783 10.77 8.07 15.61 3 18.129" />
      </svg>
      {hasTranslation ? '重新翻译' : '翻译为中文'}
    </button>
  )
}

function TranslationProgressUI({ progress }) {
  if (!progress) {
    return (
      <div className="mb-6">
        <div className="p-8 bg-violet-50 rounded-xl border border-violet-200 text-center mb-4">
          <svg className="w-8 h-8 mx-auto text-violet-500 animate-spin mb-3" fill="none" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
          <p className="text-sm text-violet-600 font-medium">正在使用 AI 翻译...</p>
          <p className="text-xs text-violet-400 mt-1">通义千问大模型，翻译准确自然</p>
        </div>
      </div>
    )
  }
  return (
    <div className="mb-6">
      <div className="flex items-center gap-2 mb-3">
        <svg className="w-4 h-4 text-violet-500 animate-spin" fill="none" viewBox="0 0 24 24">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
        </svg>
        <span className="text-xs text-violet-500 font-medium">AI 正在翻译...</span>
      </div>
      <div className="bg-white rounded-xl border border-violet-200 p-5 shadow-sm opacity-80">
        <div className="article-markdown prose prose-gray max-w-none">
          <MarkdownContent content={progress} />
        </div>
      </div>
    </div>
  )
}
