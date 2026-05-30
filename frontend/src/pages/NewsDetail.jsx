import { useState, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'
import { fetchNewsDetail, fetchFullArticle } from '../services/api'
import { useLanguage } from '../context/LanguageContext'
import LoadingSpinner from '../components/LoadingSpinner'
import NodeRenderer from 'markstream-react'
import 'markstream-react/index.css'

function TranslationStatus({ news }) {
  const status = news.translation_status
  const retryCount = news.translation_retry_count || 0

  if (!status || status === 'success') return null

  if (status === 'pending') {
    return (
      <span className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded-full bg-amber-50 text-amber-600 border border-amber-200">
        <span className="w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse" />
        等待翻译
      </span>
    )
  }

  if (status === 'translating') {
    return (
      <span className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded-full bg-sky-50 text-sky-600 border border-sky-200">
        <svg className="w-3 h-3 animate-spin" fill="none" viewBox="0 0 24 24">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
        </svg>
        正在翻译...
      </span>
    )
  }

  if (status === 'network_error') {
    return (
      <span className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded-full bg-orange-50 text-orange-600 border border-orange-200">
        <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        翻译失败（网络错误）{retryCount > 0 && `· 已重试 ${retryCount} 次`}
      </span>
    )
  }

  if (status === 'failed') {
    return (
      <span
        className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded-full bg-red-50 text-red-600 border border-red-200"
        title={news.translation_error}
      >
        <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        翻译失败 {retryCount > 0 && `· 已重试 ${retryCount} 次`}
      </span>
    )
  }

  return null
}

export default function NewsDetail() {
  const { id } = useParams()
  const { lang, t } = useLanguage()
  const [news, setNews] = useState(null)
  const [loading, setLoading] = useState(true)
  // Article fetching state
  const [articleLoading, setArticleLoading] = useState(false)
  const [articleError, setArticleError] = useState('')

  useEffect(() => {
    fetchNewsDetail(id)
      .then(data => setNews(data))
      .catch(err => console.error(err))
      .finally(() => setLoading(false))
  }, [id])

  useEffect(() => {
    // Refetch when language changes to get translated content from API
    if (!loading && news) {
      fetchNewsDetail(id)
        .then(data => setNews(data))
        .catch(err => console.error(err))
    }
  }, [lang])

  const handleFetchFullArticle = async () => {
    if (!news?.url) return
    setArticleLoading(true)
    setArticleError('')
    try {
      const data = await fetchFullArticle(id)
      // Update news with full_content from response
      setNews(prev => ({ ...prev, full_content: data.full_content, full_content_fetched_at: data.full_content_fetched_at }))
    } catch (err) {
      const msg = err.response?.data?.error || err.message || '获取失败'
      setArticleError(msg)
    } finally {
      setArticleLoading(false)
    }
  }

  if (loading) return <LoadingSpinner />
  if (!news) return (
    <div className="text-center py-20 text-gray-400">
      <p>{t.notFound}</p>
      <Link to="/" className="text-blue-600 mt-2 inline-block">{t.backHome}</Link>
    </div>
  )

  const displayTitle = (lang === 'zh' && news.source_language === 'en' && news.title_zh)
    ? news.title_zh
    : news.title

  const displayContent = (lang === 'zh' && news.source_language === 'en' && news.content_zh)
    ? news.content_zh
    : news.content

  return (
    <div className="max-w-3xl mx-auto px-4 py-8">
      <Link to="/" className="text-sm text-blue-600 hover:underline mb-6 inline-block">
        {t.backToList}
      </Link>

      <article>
        <header className="mb-6">
          <div className="flex items-center gap-2 mb-3">
            <span className="inline-block bg-blue-50 text-blue-600 text-xs px-2 py-1 rounded">
              {news.category_name}
            </span>
            {news.source_language === 'en' && (
              <TranslationStatus news={news} />
            )}
          </div>
          <h1 className="text-2xl md:text-3xl font-bold text-gray-900 leading-tight mb-4">
            {displayTitle}
          </h1>
          {lang === 'zh' && news.source_language === 'en' && news.title_zh && (
            <p className="text-sm text-gray-400 italic mb-4">
              {news.title}
            </p>
          )}
          <div className="flex flex-wrap items-center gap-3 text-sm text-gray-500">
            {news.author && <span>{t.author}: {news.author}</span>}
            <span>{t.source}: {news.source_name}</span>
            <span>{new Date(news.publish_time).toLocaleString('zh-CN')}</span>
          </div>
        </header>

        {news.cover_image && (
          <img
            src={news.cover_image}
            alt={displayTitle}
            className="w-full rounded-xl mb-6"
          />
        )}

        {/* Fetch full article button */}
        {news.source_language === 'en' && !news.full_content && !articleLoading && (
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
              onClick={handleFetchFullArticle}
              className="inline-flex items-center gap-2 px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-full
                hover:bg-indigo-700 active:scale-95 transition-all duration-200 shadow-sm hover:shadow"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m0 0v8" />
              </svg>
              加载原文
            </button>
          </div>
        )}

        {/* Loading state */}
        {articleLoading && (
          <div className="mb-6 p-8 bg-gray-50 rounded-xl border border-gray-200 text-center">
            <svg className="w-8 h-8 mx-auto text-indigo-500 animate-spin mb-3" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
            <p className="text-sm text-gray-500">正在获取原文内容...</p>
          </div>
        )}

        {/* Error state */}
        {articleError && (
          <div className="mb-6 p-4 bg-red-50 rounded-xl border border-red-200">
            <div className="flex items-center gap-2 text-red-600 text-sm">
              <svg className="w-4 h-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              <span>{articleError}</span>
              <button
                onClick={handleFetchFullArticle}
                className="ml-auto text-xs underline hover:no-underline"
              >
                重试
              </button>
            </div>
          </div>
        )}

        {/* Fetched article content */}
        {news.full_content && (
          <div className="mb-6">
            <div className="flex items-center justify-between mb-3">
              <span className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded-full bg-green-50 text-green-700 border border-green-200">
                <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                </svg>
                已获取原文
                {news.full_content_fetched_at && (
                  <span className="text-green-500 ml-1">
                    · {new Date(news.full_content_fetched_at).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}
                  </span>
                )}
              </span>
            </div>
            <div className="bg-white rounded-xl border border-gray-200 p-5 shadow-sm">
              <div className="text-gray-700 leading-relaxed">
                <NodeRenderer
                  content={news.full_content}
                  codeBlockProps={{
                    showHeader: true,
                    showCopyButton: true,
                    showCollapseButton: false,
                    showFontSizeButtons: false,
                    showTooltips: true,
                  }}
                  codeBlockThemes={{
                    themes: ['vitesse-light'],
                    darkTheme: 'vitesse-light',
                    lightTheme: 'vitesse-light',
                    monacoOptions: {
                      fontSize: 14,
                      fontFamily: "'JetBrains Mono', 'Fira Code', 'Cascadia Code', 'Source Code Pro', Menlo, Consolas, monospace",
                      padding: { top: 12, bottom: 12 },
                      lineNumbers: 'on',
                      wordWrap: 'on',
                      minimap: { enabled: false },
                      scrollbar: { vertical: 'hidden', horizontal: 'hidden' },
                      scrollBeyondLastLine: false,
                      overviewRulerLanes: 0,
                      hideCursorInOverviewRuler: true,
                      renderLineHighlight: 'none',
                      renderLineHighlightOnlyWhenFocus: true,
                      contextmenu: false,
                      readOnly: true,
                      domReadOnly: true,
                      mouseWheelZoom: false,
                      smoothScrolling: true,
                      cursorBlinking: 'blink',
                      cursorSmoothCaretAnimation: 'on',
                    },
                  }}
                />
              </div>
            </div>
          </div>
        )}

        <div className="text-gray-700 leading-relaxed">
          <NodeRenderer
            content={displayContent || ''}
            codeBlockProps={{
              showHeader: true,
              showCopyButton: true,
              showCollapseButton: false,
              showFontSizeButtons: false,
              showTooltips: true,
            }}
            codeBlockThemes={{
              themes: ['vitesse-light'],
              darkTheme: 'vitesse-light',
              lightTheme: 'vitesse-light',
              monacoOptions: {
                fontSize: 14,
                fontFamily: "'JetBrains Mono', 'Fira Code', 'Cascadia Code', 'Source Code Pro', Menlo, Consolas, monospace",
                padding: { top: 12, bottom: 12 },
                lineNumbers: 'on',
                wordWrap: 'on',
                minimap: { enabled: false },
                scrollbar: { vertical: 'hidden', horizontal: 'hidden' },
                scrollBeyondLastLine: false,
                overviewRulerLanes: 0,
                hideCursorInOverviewRuler: true,
                renderLineHighlight: 'none',
                renderLineHighlightOnlyWhenFocus: true,
                contextmenu: false,
                readOnly: true,
                domReadOnly: true,
                mouseWheelZoom: false,
                smoothScrolling: true,
                cursorBlinking: 'blink',
                cursorSmoothCaretAnimation: 'on',
              },
            }}
          />
        </div>

        <div className="mt-8 pt-6 border-t border-gray-200">
          <a
            href={news.url}
            target="_blank"
            rel="noreferrer"
            className="text-blue-600 hover:underline text-sm"
          >
            {t.readOriginal}
          </a>
        </div>
      </article>
    </div>
  )
}
