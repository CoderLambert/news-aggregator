import { useState } from 'react'
import { Link } from 'react-router-dom'
import {
  Search, Globe, FileText, BarChart3, FileCheck, ShieldCheck,
  Loader2, Check, ExternalLink, ChevronDown, ChevronRight,
  ArrowUpRight, Newspaper, MessageSquare,
} from 'lucide-react'

const TOOL_ICONS = {
  search_news: Search,
  fetch_article: FileText,
  search_web: Globe,
  fetch_webpage: Globe,
  analyze_topic: BarChart3,
  generate_report: FileCheck,
  cross_verify: ShieldCheck,
}

const TOOL_LABELS = {
  search_news: '搜索新闻库',
  fetch_article: '获取全文',
  search_web: '联网搜索',
  fetch_webpage: '抓取网页',
  analyze_topic: '话题分析',
  generate_report: '生成报告',
  cross_verify: '交叉验证',
}

const SOURCE_TYPE_MAP = {
  news: { label: '新闻', color: 'bg-violet-50 text-violet-600' },
  aggregator: { label: '聚合', color: 'bg-amber-50 text-amber-600' },
  discussion: { label: '讨论', color: 'bg-sky-50 text-sky-600' },
}

const WEB_SOURCE_MAP = {
  jina: { label: 'Jina', color: 'bg-emerald-50 text-emerald-600' },
  wikipedia_en: { label: 'Wiki EN', color: 'bg-blue-50 text-blue-600' },
  wikipedia_zh: { label: 'Wiki', color: 'bg-blue-50 text-blue-600' },
  duckduckgo: { label: 'DDG', color: 'bg-orange-50 text-orange-600' },
}

/**
 * Vertical timeline showing each tool call in the agent loop.
 * Each step has a dot + icon + label + result.
 * search_news results render as clickable news cards with external links.
 *
 * When searchResults (from the ResearchSearchResult API) is provided,
 * it is used as a supplemental data source — the full result_data is
 * available there even for historical sessions where SSE fields may be absent.
 */
export default function ProcessTimeline({ toolCalls, searchResults }) {
  if (!toolCalls || toolCalls.length === 0) return null

  // Build a lookup: tool_name → [results] for enriching tool call display
  const resultsByTool = {}
  if (searchResults && searchResults.length > 0) {
    for (const sr of searchResults) {
      if (!resultsByTool[sr.tool_name]) resultsByTool[sr.tool_name] = []
      resultsByTool[sr.tool_name].push(sr)
    }
  }

  return (
    <div className="relative pl-4 space-y-2">
      {/* Vertical line */}
      <div className="absolute left-[11px] top-3 bottom-3 w-px bg-gradient-to-b from-violet-200 via-violet-100 to-transparent" />

      {toolCalls.map((tc, i) => {
        const isRunning = tc.status === 'running'
        const isDone = tc.status === 'done'

        return (
          <div key={tc.callId} className="relative flex items-start gap-3 animate-message-pop-in">
            {/* Node */}
            <div className={`
              relative z-10 flex-shrink-0 w-6 h-6 rounded-full flex items-center justify-center
              border-2 transition-all
              ${isRunning
                ? 'border-violet-400 bg-violet-100 shadow-[0_0_0_4px_rgba(139,92,246,0.15)]'
                : isDone
                  ? 'border-emerald-400 bg-emerald-50'
                  : 'border-neutral-300 bg-neutral-50'
              }
            `}>
              {isRunning ? (
                <Loader2 className="w-3 h-3 text-violet-500 animate-spin" />
              ) : isDone ? (
                <Check className="w-3 h-3 text-emerald-500" />
              ) : (
                <div className="w-1.5 h-1.5 rounded-full bg-neutral-300" />
              )}
            </div>

            {/* Content */}
            <div className="flex-1 min-w-0 pt-0.5">
              <div className="flex items-center gap-1.5">
                {(() => {
                  const Icon = TOOL_ICONS[tc.name] || FileText
                  return (
                    <>
                      <Icon className="w-3.5 h-3.5 text-neutral-400 flex-shrink-0" />
                      <span className="text-[11px] font-medium text-neutral-500">
                        {TOOL_LABELS[tc.name] || tc.name}
                      </span>
                      {tc.args?.query && (
                        <span className="text-[11px] text-neutral-400 truncate">
                          · {truncate(tc.args.query, 35)}
                        </span>
                      )}
                    </>
                  )
                })()}
              </div>

              {/* Result */}
              {isDone && (
                <div className="mt-1">
                  <ToolResult
                    name={tc.name}
                    args={tc.args}
                    summary={tc.summary}
                    articles={tc.articles}
                    webResults={tc.webResults}
                    articleTitle={tc.articleTitle}
                    articleId={tc.articleId}
                    articleSource={tc.articleSource}
                    articleUrl={tc.articleUrl}
                    contentTruncated={tc.contentTruncated}
                    originalLength={tc.originalLength}
                    contentLength={tc.contentLength}
                    persistedResults={resultsByTool[tc.name] || []}
                  />
                </div>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}

// ── Tool Result Renderers ────────────────────────────────────────────────────

function ToolResult({
  name, args, summary,
  articles, webResults,
  articleTitle, articleId, articleSource, articleUrl,
  contentTruncated, originalLength, contentLength,
  persistedResults,
}) {
  let articleList = articles || args?.articles || []
  let webList = webResults || args?.results || []

  // Supplement from persisted search results (from the DB API) when SSE fields are empty
  // This is common for historical sessions where tool results are loaded from messages
  if (articleList.length === 0 && persistedResults?.length > 0) {
    const latest = persistedResults[persistedResults.length - 1]
    if (latest?.result_data?.articles) {
      articleList = latest.result_data.articles
    }
  }
  if (webList.length === 0 && persistedResults?.length > 0) {
    const latest = persistedResults[persistedResults.length - 1]
    if (latest?.result_data?.results) {
      webList = latest.result_data.results
    }
  }

  if (name === 'search_news' && articleList.length > 0) {
    return <SearchNewsResult articles={articleList} />
  }

  if (name === 'search_web' && webList.length > 0) {
    return <SearchWebResult results={webList} />
  }

  if (name === 'fetch_article') {
    // Try persisted result first (has richer data for historical sessions)
    const persisted = persistedResults?.length > 0 ? persistedResults[persistedResults.length - 1] : null
    const rd = persisted?.result_data || {}
    const title = articleTitle || args?.title || rd.title_zh || rd.title || ''
    const id = articleId || args?.id || rd.id
    const source = articleSource || args?.source || rd.source || ''
    const url = articleUrl || args?.url || rd.url || ''
    const truncated = contentTruncated || args?.content_truncated || rd.content_truncated || false
    const origLen = originalLength || args?.original_length || rd.original_length || 0
    return (
      <FetchArticleResult title={title} id={id} source={source} url={url}
        truncated={truncated} originalLength={origLen} />
    )
  }

  if (name === 'fetch_webpage') {
    const persisted = persistedResults?.length > 0 ? persistedResults[persistedResults.length - 1] : null
    const rd = persisted?.result_data || {}
    const url = articleUrl || args?.url || rd.url || ''
    const len = contentLength || args?.length || rd.length || 0
    return <FetchWebpageResult url={url} length={len} />
  }

  if (name === 'generate_report') {
    return <GenerateReportResult args={args} summary={summary} />
  }

  // Fallback: show summary text or error
  if (name === 'search_web' && summary) {
    return <p className="text-[11px] text-amber-600">{summary}</p>
  }
  if (summary) {
    return <p className="text-[11px] text-neutral-400">{summary}</p>
  }

  return null
}

// ── search_news: Article cards with external link ────────────────────────────

function SearchNewsResult({ articles }) {
  const [expanded, setExpanded] = useState(false)
  const visible = expanded ? articles : articles.slice(0, 3)

  return (
    <div className="mt-1 space-y-1.5">
      {visible.map(art => (
        <div
          key={art.id}
          className="group relative bg-white rounded-lg border border-neutral-100
                     hover:border-violet-200 hover:shadow-sm
                     transition-all duration-150 overflow-hidden"
        >
          {/* Left accent on hover */}
          <div className="absolute left-0 top-0 bottom-0 w-0.5 bg-violet-400 opacity-0
                         group-hover:opacity-100 transition-opacity duration-150" />

          <div className="flex items-start gap-2 px-3 py-2">
            {/* Main content: link to local detail */}
            <Link
              to={`/news/${art.id}`}
              className="flex-1 min-w-0"
            >
              <p className="text-[13px] font-medium text-neutral-800 group-hover:text-violet-800 line-clamp-2 leading-snug">
                {art.title}
              </p>
              <div className="flex items-center gap-1.5 mt-1 flex-wrap">
                <span className="inline-flex items-center px-1.5 py-0.5 rounded-md bg-violet-50 text-[10px] font-medium text-violet-600">
                  {art.source}
                </span>
                {art.source_type && SOURCE_TYPE_MAP[art.source_type] && (
                  <span className={`inline-flex items-center gap-0.5 px-1 py-0.5 rounded text-[9px] font-medium ${SOURCE_TYPE_MAP[art.source_type].color}`}>
                    {art.source_type === 'news' && <Newspaper className="w-2.5 h-2.5" />}
                    {art.source_type === 'discussion' && <MessageSquare className="w-2.5 h-2.5" />}
                    {SOURCE_TYPE_MAP[art.source_type].label}
                  </span>
                )}
                {art.publish_time && (
                  <span className="text-[10px] text-neutral-400">
                    {formatDate(art.publish_time)}
                  </span>
                )}
              </div>
              {art.snippet && (
                <p className="text-[11px] text-neutral-400 line-clamp-2 mt-1 leading-relaxed">
                  {art.snippet}
                </p>
              )}
            </Link>

            {/* External link button */}
            {art.url && (
              <a
                href={art.url}
                target="_blank"
                rel="noopener noreferrer"
                title="查看原文"
                onClick={e => e.stopPropagation()}
                className="flex-shrink-0 mt-0.5 p-1.5 rounded-md text-neutral-300
                           hover:text-violet-500 hover:bg-violet-50
                           transition-colors duration-150"
              >
                <ArrowUpRight className="w-3.5 h-3.5" />
              </a>
            )}
          </div>
        </div>
      ))}

      {articles.length > 3 && (
        <button
          type="button"
          onClick={() => setExpanded(!expanded)}
          className="flex items-center gap-1 text-[11px] text-violet-500 hover:text-violet-600
                     font-medium transition-colors"
        >
          {expanded
            ? <><ChevronDown className="w-3 h-3" /> 收起</>
            : <><ChevronRight className="w-3 h-3" /> 还有 {articles.length - 3} 篇</>
          }
        </button>
      )}
    </div>
  )
}

// ── search_web: Web results with snippets ───────────────────────────────────

function SearchWebResult({ results }) {
  const [expanded, setExpanded] = useState(false)
  const visible = expanded ? results : results.slice(0, 3)

  return (
    <div className="mt-1 space-y-1">
      {visible.map((r, i) => {
        const sourceKey = (r.source || '').replace('wikipedia_', 'wikipedia_')
        const sourceInfo = WEB_SOURCE_MAP[sourceKey] || null
        const domain = extractDomain(r.url)

        return (
          <a
            key={i}
            href={r.url}
            target="_blank"
            rel="noopener noreferrer"
            className="group block rounded-lg border border-transparent
                       hover:border-blue-200 hover:bg-blue-50/30
                       px-2.5 py-2 transition-all duration-150"
          >
            <div className="flex items-start gap-1.5">
              <ExternalLink className="w-3 h-3 text-neutral-400 mt-0.5 flex-shrink-0 group-hover:text-blue-500" />
              <div className="min-w-0 flex-1">
                <p className="text-[12px] font-medium text-neutral-700 group-hover:text-blue-700 line-clamp-1">
                  {r.title}
                </p>
                <div className="flex items-center gap-1.5 mt-0.5">
                  {sourceInfo ? (
                    <span className={`inline-flex items-center px-1 py-0.5 rounded text-[9px] font-medium ${sourceInfo.color}`}>
                      {sourceInfo.label}
                    </span>
                  ) : (
                    <span className="inline-flex items-center px-1 py-0.5 rounded bg-neutral-100 text-[9px] font-medium text-neutral-500">
                      Web
                    </span>
                  )}
                  {domain && (
                    <span className="text-[10px] text-neutral-400 truncate">
                      {domain}
                    </span>
                  )}
                </div>
                {r.snippet && (
                  <p className="text-[11px] text-neutral-400 line-clamp-2 mt-1 leading-relaxed">
                    {r.snippet}
                  </p>
                )}
              </div>
            </div>
          </a>
        )
      })}

      {results.length > 3 && (
        <button
          type="button"
          onClick={() => setExpanded(!expanded)}
          className="flex items-center gap-1 text-[11px] text-violet-500 hover:text-violet-600
                     font-medium transition-colors"
        >
          {expanded ? <><ChevronDown className="w-3 h-3" /> 收起</> : `+${results.length - 3} 更多结果`}
        </button>
      )}
    </div>
  )
}

// ── fetch_article: Article detail badge ──────────────────────────────────────

function FetchArticleResult({ title, id, source, url, truncated, originalLength }) {
  return (
    <div className="mt-1 inline-flex flex-wrap items-center gap-1.5">
      {/* Internal link to article detail */}
      <Link
        to={`/news/${id}`}
        className="inline-flex items-center gap-1.5 bg-white rounded-lg border border-neutral-100
                   px-2.5 py-1.5 hover:border-violet-200 hover:bg-violet-50/50 transition-all group"
      >
        <FileText className="w-3 h-3 text-neutral-400 group-hover:text-violet-400" />
        <span className="text-[12px] font-medium text-neutral-700 group-hover:text-violet-700 line-clamp-1 max-w-[200px]">
          {title}
        </span>
      </Link>

      {/* Source tag */}
      {source && (
        <span className="inline-flex items-center px-1.5 py-1 rounded-md bg-violet-50 text-[10px] font-medium text-violet-600">
          {source}
        </span>
      )}

      {/* External original link */}
      {url && (
        <a
          href={url}
          target="_blank"
          rel="noopener noreferrer"
          title="查看原文"
          className="inline-flex items-center gap-1 px-2 py-1 rounded-md border border-neutral-100
                     text-[10px] text-neutral-400 hover:text-violet-500 hover:border-violet-200
                     hover:bg-violet-50 transition-all"
        >
          <ArrowUpRight className="w-3 h-3" />
          原文
        </a>
      )}

      {/* Truncation notice */}
      {truncated && (
        <span className="inline-flex items-center px-1.5 py-1 rounded bg-amber-50 text-[9px] text-amber-600">
          内容已截断 ({formatCharCount(originalLength)})
        </span>
      )}
    </div>
  )
}

// ── fetch_webpage: Scraped page card ────────────────────────────────────────

function FetchWebpageResult({ url, length }) {
  if (!url) return null
  const domain = extractDomain(url)

  return (
    <div className="mt-1 inline-flex items-center gap-2 bg-white rounded-lg border border-neutral-100
                    px-2.5 py-1.5 group hover:border-blue-200 hover:bg-blue-50/30 transition-all">
      <Globe className="w-3 h-3 text-neutral-400 group-hover:text-blue-500" />
      <a
        href={url}
        target="_blank"
        rel="noopener noreferrer"
        className="text-[12px] font-medium text-neutral-700 group-hover:text-blue-700 truncate max-w-[180px]"
      >
        {domain || url}
      </a>
      {length > 0 && (
        <span className="text-[10px] text-neutral-400">
          {formatCharCount(length)} 字符
        </span>
      )}
      <a
        href={url}
        target="_blank"
        rel="noopener noreferrer"
        title="访问原网页"
        className="p-1 rounded text-neutral-300 hover:text-blue-500 hover:bg-blue-50 transition-colors"
      >
        <ArrowUpRight className="w-3 h-3" />
      </a>
    </div>
  )
}

// ── generate_report: Report structure with quality checklist ────────────────

function GenerateReportResult({ args, summary }) {
  const sections = args?.suggested_sections || summary?.match(/(\d+) 个章节/)?.[1]
  const qualityItems = args?.quality_checklist || []

  return (
    <div className="mt-1 space-y-1">
      {sections && (
        <p className="text-[11px] text-neutral-400">
          {typeof sections === 'number'
            ? `报告结构: ${sections} 个章节`
            : `报告结构: ${Array.isArray(sections) ? sections.length : sections} 个章节`}
        </p>
      )}
      {qualityItems.length > 0 && (
        <div className="p-2 bg-emerald-50 rounded border border-emerald-100">
          <p className="text-[11px] font-medium text-emerald-700 mb-1">质量检查清单：</p>
          {qualityItems.map((item, i) => (
            <p key={i} className="text-[10px] text-emerald-600 flex items-center gap-1">
              <Check className="w-2.5 h-2.5 flex-shrink-0" /> {item.replace('✓ ', '')}
            </p>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Utilities ───────────────────────────────────────────────────────────────

function truncate(str, max) {
  if (!str) return ''
  return str.length > max ? str.slice(0, max) + '…' : str
}

function formatDate(dateStr) {
  if (!dateStr) return ''
  try {
    const d = new Date(dateStr)
    const now = new Date()
    const diff = now - d
    const days = Math.floor(diff / 86400000)
    if (days === 0) return '今天'
    if (days === 1) return '昨天'
    if (days < 7) return `${days}天前`
    return d.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })
  } catch {
    return ''
  }
}

function extractDomain(url) {
  if (!url) return ''
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return url.slice(0, 30)
  }
}

function formatCharCount(n) {
  if (n < 1000) return String(n)
  return `${(n / 1000).toFixed(1)}k`
}
