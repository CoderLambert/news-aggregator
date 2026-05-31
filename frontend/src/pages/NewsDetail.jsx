import { useState, useEffect, useRef } from 'react'
import { useParams, Link } from 'react-router-dom'
import { fetchNewsDetail, fetchFullArticle } from '../services/api'
import { useLanguage } from '../context/LanguageContext'
import LoadingSpinner from '../components/LoadingSpinner'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import NodeRenderer from 'markstream-react'
import NewsChatAssistant from '../components/NewsChatAssistant'
import 'markstream-react/index.css'

// Custom components for optimized Markdown rendering
function MarkdownContent({ content }) {
  return (
    <div className="article-markdown prose prose-gray max-w-none w-full overflow-hidden">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          h1: ({ children }) => (
            <h1 className="text-2xl font-bold text-gray-900 mt-8 mb-4 pb-2 border-b border-gray-200 break-words">
              {children}
            </h1>
          ),
          h2: ({ children }) => (
            <h2 className="text-xl font-semibold text-gray-800 mt-7 mb-3 pb-1 border-b border-gray-100 break-words">
              {children}
            </h2>
          ),
          h3: ({ children }) => (
            <h3 className="text-lg font-semibold text-gray-800 mt-6 mb-2 break-words">
              {children}
            </h3>
          ),
          h4: ({ children }) => (
            <h4 className="text-base font-semibold text-gray-700 mt-5 mb-2 break-words">
              {children}
            </h4>
          ),
          p: ({ children }) => (
            <p className="text-[15px] leading-[1.8] text-gray-700 mb-4 text-justify break-words">
              {children}
            </p>
          ),
          a: ({ href, children }) => (
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              className="text-blue-600 hover:text-blue-800 underline decoration-blue-300 hover:decoration-blue-600 underline-offset-2 transition-colors break-all"
            >
              {children}
            </a>
          ),
          strong: ({ children }) => (
            <strong className="font-semibold text-gray-900">{children}</strong>
          ),
          em: ({ children }) => (
            <em className="text-gray-600 italic">{children}</em>
          ),
          blockquote: ({ children }) => (
            <blockquote className="border-l-4 border-violet-300 bg-violet-50/50 rounded-r-lg pl-4 py-3 pr-3 my-4 text-gray-600 break-words">
              {children}
            </blockquote>
          ),
          ul: ({ children }) => (
            <ul className="list-disc list-outside ml-5 mb-4 space-y-1.5 text-[15px] leading-[1.8] text-gray-700 break-words">
              {children}
            </ul>
          ),
          ol: ({ children }) => (
            <ol className="list-decimal list-outside ml-5 mb-4 space-y-1.5 text-[15px] leading-[1.8] text-gray-700 break-words">
              {children}
            </ol>
          ),
          li: ({ children }) => (
            <li className="pl-1 break-words">{children}</li>
          ),
          code: ({ className, children }) => {
            const isInline = !className
            return isInline ? (
              <code className="px-1.5 py-0.5 bg-gray-100 text-rose-600 rounded text-[0.85em] font-mono break-all">
                {children}
              </code>
            ) : (
              <code className={className}>{children}</code>
            )
          },
          pre: ({ children }) => (
            <pre className="bg-gray-50 rounded-xl p-4 mb-4 overflow-x-auto border border-gray-200 font-mono text-[13px] leading-[1.6]">
              {children}
            </pre>
          ),
          table: ({ children }) => (
            <div className="overflow-x-auto my-4 rounded-lg border border-gray-200">
              <table className="min-w-full text-[14px]">{children}</table>
            </div>
          ),
          thead: ({ children }) => (
            <thead className="bg-gray-50">{children}</thead>
          ),
          th: ({ children }) => (
            <th className="px-4 py-2.5 text-left font-semibold text-gray-700 border-b border-gray-200">
              {children}
            </th>
          ),
          td: ({ children }) => (
            <td className="px-4 py-2.5 text-gray-600 border-b border-gray-100">
              {children}
            </td>
          ),
          hr: () => (
            <hr className="my-6 border-gray-200" />
          ),
          img: ({ src, alt }) => (
            <figure className="my-6 text-center">
              <img
                src={src}
                alt={alt || ''}
                className="max-w-full h-auto rounded-lg mx-auto shadow-sm"
                style={{ maxHeight: '480px', objectFit: 'contain' }}
              />
              {alt && (
                <figcaption className="text-xs text-gray-400 mt-2">{alt}</figcaption>
              )}
            </figure>
          ),
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  )
}

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
  // Translation state
  const [translating, setTranslating] = useState(false)
  const [translateError, setTranslateError] = useState('')
  const [showOriginal, setShowOriginal] = useState(false)
  const [translationProgress, setTranslationProgress] = useState('')
  const autoResumedRef = useRef(false)
  const progressRef = useRef('')
  const lastProgressUpdateRef = useRef(0)

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

  // Auto-resume translation after page refresh if it was in progress
  // Only runs once per page load to avoid infinite loops
  useEffect(() => {
    if (loading || !news) return
    
    const markerKey = `translating_${id}`
    const marker = localStorage.getItem(markerKey)
    
    if (marker && news.full_content && !news.full_content_zh) {
      try {
        const { startedAt } = JSON.parse(marker)
        // Only auto-resume if translation started within last 5 minutes
        if (Date.now() - startedAt < 5 * 60 * 1000) {
          if (!autoResumedRef.current) {
            autoResumedRef.current = true
            console.log('Resuming translation after page refresh...')
            handleTranslate(true)
          }
        } else {
          // Marker is too old, clean it up
          localStorage.removeItem(markerKey)
        }
      } catch {
        localStorage.removeItem(markerKey)
      }
    } else if (marker && news.full_content_zh && news.full_content_zh.length > 50) {
      // Translation already completed but marker is stale — clean it up
      localStorage.removeItem(markerKey)
    }
  }, []) // Run only once on mount (after news loads)

  // Cleanup stale translating markers for this article on every page visit
  useEffect(() => {
    if (!news) return
    const markerKey = `translating_${id}`
    const marker = localStorage.getItem(markerKey)
    
    if (marker) {
      try {
        const { startedAt } = JSON.parse(marker)
        // If marker is older than 5 minutes, or translation is already done, remove it
        if (Date.now() - startedAt > 5 * 60 * 1000 || (news.full_content_zh && news.full_content_zh.length > 50)) {
          localStorage.removeItem(markerKey)
        }
      } catch {
        localStorage.removeItem(markerKey)
      }
    }
  }, [news]) // Runs whenever news data is loaded

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

  const handleTranslate = async (force = false) => {
    setTranslating(true)
    setTranslateError('')
    setTranslationProgress('')
    // Mark as translating in localStorage for recovery after page refresh
    localStorage.setItem(`translating_${id}`, JSON.stringify({ startedAt: Date.now() }))
    // Clear previous translation to show loading state
    setNews(prev => ({ ...prev, full_content_zh: '' }))

    try {
      const response = await fetch(`/api/news/${id}/translate/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ force: force }),
      })

      if (!response.ok) {
        const errText = await response.text().catch(() => response.statusText)
        throw new Error(errText || `HTTP ${response.status}`)
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const raw = line.slice(6)
            if (!raw.trim()) continue
            try {
              const data = JSON.parse(raw)
              if (data.error) throw new Error(data.error)
              
              if (data.full_content_zh) {
                // Finished
                setNews(prev => ({
                  ...prev,
                  full_content_zh: data.full_content_zh,
                  full_content_zh_fetched_at: data.full_content_zh_fetched_at
                }))
                setTranslationProgress('')
                setTranslating(false)
                // Clear translating marker from localStorage
                localStorage.removeItem(`translating_${id}`)
                return
              }
              
              if (data.progress !== undefined) {
                // Throttle progress updates to every 200ms to prevent UI jitter
                progressRef.current = data.progress
                const now = Date.now()
                if (now - lastProgressUpdateRef.current > 200) {
                  lastProgressUpdateRef.current = now
                  setTranslationProgress(data.progress)
                }
              }
            } catch (e) {
              if (e instanceof SyntaxError) {
                // Ignore malformed JSON lines (likely fragmentation)
              } else {
                throw e
              }
            }
          }
        }
      }
      
      // Flush any pending progress before marking complete
      if (progressRef.current) {
        setTranslationProgress(progressRef.current)
      }
      
      // Process remaining buffer if stream ended abruptly
      if (buffer.trim().startsWith('data: ')) {
        try {
          const data = JSON.parse(buffer.trim().slice(6))
          if (data.full_content_zh) {
             setNews(prev => ({
               ...prev,
               full_content_zh: data.full_content_zh,
               full_content_zh_fetched_at: data.full_content_zh_fetched_at
             }))
             setTranslationProgress('')
             setTranslating(false)
          } else if (data.progress !== undefined) {
             setTranslationProgress(data.progress)
             progressRef.current = data.progress
          }
        } catch (e) {}
      }

    } catch (err) {
      console.error('Translation failed:', err)
      setTranslateError(err.message || '翻译失败')
      setTranslating(false)
      // Keep translating marker so user can retry on page load
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
    <div className="max-w-3xl mx-auto px-4 py-6 sm:py-8 w-full overflow-x-hidden">
      <Link to="/" className="text-sm text-blue-600 hover:underline mb-6 inline-block">
        {t.backToList}
      </Link>

      <article className="w-full break-words min-w-0">
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
                {/* Language toggle */}
                {news.full_content_zh && (
                  <div className="flex bg-gray-100 rounded-full p-0.5">
                    <button
                      onClick={() => setShowOriginal(false)}
                      className={`px-3 py-1 text-xs rounded-full transition-all ${
                        !showOriginal
                          ? 'bg-white text-gray-900 shadow-sm'
                          : 'text-gray-500 hover:text-gray-700'
                      }`}
                    >
                      中文
                    </button>
                    <button
                      onClick={() => setShowOriginal(true)}
                      className={`px-3 py-1 text-xs rounded-full transition-all ${
                        showOriginal
                          ? 'bg-white text-gray-900 shadow-sm'
                          : 'text-gray-500 hover:text-gray-700'
                      }`}
                    >
                      English
                    </button>
                  </div>
                )}
            {/* Translate / Re-translate Button */}
            {!translating && !translateError && (
              <button
                onClick={() => handleTranslate(!!news.full_content_zh)}
                className={`inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-full transition-all duration-200 shadow-sm hover:shadow
                  ${news.full_content_zh 
                    ? 'bg-gray-100 text-gray-600 hover:bg-gray-200 border border-gray-200' 
                    : 'bg-violet-600 text-white hover:bg-violet-700'
                  }`}
              >
                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M3 5h12M9 3v2m1.048 9.5A18.022 18.022 0 016.412 9m6.088 9h7M11 21l5-10 5 10M12.751 5C11.783 10.77 8.07 15.61 3 18.129" />
                </svg>
                {news.full_content_zh ? '重新翻译' : '翻译为中文'}
              </button>
            )}
              </div>
            </div>

            {/* Translation UI (Unified for Spinner & Progress) */}
            {translating && (
              <div className="mb-6">
                {!translationProgress ? (
                  <div className="p-8 bg-violet-50 rounded-xl border border-violet-200 text-center mb-4">
                    <svg className="w-8 h-8 mx-auto text-violet-500 animate-spin mb-3" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                    </svg>
                    <p className="text-sm text-violet-600 font-medium">正在使用 AI 翻译...</p>
                    <p className="text-xs text-violet-400 mt-1">通义千问大模型，翻译准确自然</p>
                  </div>
                ) : (
                  <div>
                    <div className="flex items-center gap-2 mb-3">
                      <svg className="w-4 h-4 text-violet-500 animate-spin" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                      </svg>
                      <span className="text-xs text-violet-500 font-medium">AI 正在翻译...</span>
                    </div>
                    <div className="bg-white rounded-xl border border-violet-200 p-5 shadow-sm opacity-80">
                      <div className="article-markdown prose prose-gray max-w-none">
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>
                          {translationProgress}
                        </ReactMarkdown>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* Translate error */}
            {translateError && (
              <div className="mb-4 p-4 bg-red-50 rounded-xl border border-red-200">
                <div className="flex items-center gap-2 text-red-600 text-sm">
                  <svg className="w-4 h-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  <span>{translateError}</span>
                  <button
                    onClick={() => handleTranslate(true)}
                    className="ml-auto text-xs underline hover:no-underline"
                  >
                    重试
                  </button>
                </div>
              </div>
            )}

            <div className="bg-white rounded-xl border border-gray-200 p-5 shadow-sm">
              <MarkdownContent content={showOriginal ? news.full_content : (news.full_content_zh || news.full_content)} />
            </div>
          </div>
        )}

        <div className="text-gray-700 leading-relaxed w-full overflow-x-hidden">
          <div className="w-full max-w-full overflow-hidden">
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
      <NewsChatAssistant newsId={id} />
    </div>
  )
}
