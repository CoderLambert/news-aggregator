import { useState, useEffect, useRef } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { Search, Loader2, FileText, ExternalLink, Globe, Clock, Star, SlidersHorizontal } from 'lucide-react'
import { fetchNews } from '../services/api'
import { Pagination } from '../components/Pagination'

const MODES = [
  { key: 'keyword', label: '关键词' },
  { key: 'semantic', label: '语义' },
  { key: 'hybrid', label: '混合' },
]

const MODE_HINTS = {
  keyword: '按关键词精确匹配标题和摘要',
  semantic: '按语义相似度理解你的意图',
  hybrid: '关键词 + 语义混合排序',
}

const PLACEHOLDERS = [
  '搜索本地新闻文章…',
  '输入话题、关键词或完整句子…',
]

const SOURCE_TYPES = [
  { key: 'news', label: '新闻' },
  { key: 'aggregator', label: '聚合' },
  { key: 'discussion', label: '讨论' },
]

const TIME_RANGES = [
  { key: '', label: '全部' },
  { key: '7', label: '近 7 天' },
  { key: '30', label: '近 30 天' },
  { key: '90', label: '近 90 天' },
]

const ORDER_BY_OPTIONS = [
  { key: 'relevance', label: '相关性' },
  { key: 'time', label: '最新发布' },
]

/** Reusable pill-button group for filters */
function PillGroup({ options, value, onChange }) {
  return (
    <div className="flex gap-1">
      {options.map(opt => (
        <button
          key={opt.key}
          type="button"
          onClick={() => onChange(opt.key)}
          className={`px-2.5 py-1 rounded-full text-xs font-medium transition-all cursor-pointer
            ${value === opt.key
              ? 'bg-violet-500 text-white shadow-sm'
              : 'bg-white border border-neutral-200 text-neutral-600 hover:border-violet-300 hover:bg-violet-50/50'
            }`}
        >
          {opt.label}
        </button>
      ))}
    </div>
  )
}

export default function LocalSearch() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [query, setQuery] = useState(searchParams.get('q') || '')
  const [mode, setMode] = useState(searchParams.get('mode') || 'semantic')
  const [results, setResults] = useState([])
  const [totalCount, setTotalCount] = useState(0)
  const [page, setPage] = useState(parseInt(searchParams.get('page') || '1', 10))
  const [loading, setLoading] = useState(false)
  const [hasSearched, setHasSearched] = useState(!!searchParams.get('q'))

  // Filter state
  const [orderBy, setOrderBy] = useState(searchParams.get('order_by') || 'relevance')
  const [fullContentOnly, setFullContentOnly] = useState(searchParams.get('full_content') === 'true')
  const [days, setDays] = useState(searchParams.get('days') || '')
  const [sourceTypeFilters, setSourceTypeFilters] = useState(
    searchParams.get('source_types') ? searchParams.get('source_types').split(',') : []
  )
  const [showFilters, setShowFilters] = useState(false)

  const inputRef = useRef(null)

  // Sync URL params to state on initial mount
  useEffect(() => {
    const q = searchParams.get('q') || ''
    const m = searchParams.get('mode') || 'semantic'
    const p = parseInt(searchParams.get('page') || '1', 10)
    const ob = searchParams.get('order_by') || 'relevance'
    const fc = searchParams.get('full_content') === 'true'
    const d = searchParams.get('days') || ''
    const st = searchParams.get('source_types') ? searchParams.get('source_types').split(',') : []
    setQuery(q)
    setMode(m)
    setPage(p)
    setOrderBy(ob)
    setFullContentOnly(fc)
    setDays(d)
    setSourceTypeFilters(st)
    if (q) {
      setHasSearched(true)
      doSearch(q, m, p, { orderBy: ob, fullContentOnly: fc, days: d, sourceTypeFilters: st })
    }
  }, [])

  // Ref: track latest state values so doSearch always reads fresh filters
  const filtersRef = useRef({ orderBy, fullContentOnly, days, sourceTypeFilters })
  useEffect(() => {
    filtersRef.current = { orderBy, fullContentOnly, days, sourceTypeFilters }
  })

  async function doSearch(searchQuery, searchMode, searchPage, overrides) {
    if (!searchQuery.trim()) return
    setLoading(true)
    setPage(searchPage)

    const base = filtersRef.current
    const ob = overrides?.orderBy ?? base.orderBy
    const fc = overrides?.fullContentOnly ?? base.fullContentOnly
    const d = overrides?.days ?? base.days
    const st = overrides?.sourceTypeFilters ?? base.sourceTypeFilters

    try {
      const params = {
        search: searchQuery,
        mode: searchMode,
        page: searchPage,
        page_size: 20,
        order_by: ob,
      }

      if (fc) params.full_content = 'true'
      if (d) {
        const afterDate = new Date()
        afterDate.setDate(afterDate.getDate() - parseInt(d, 10))
        params.publish_time_after = afterDate.toISOString().split('T')[0]
      }
      if (st.length > 0) {
        params.source__source_type = st[0]
      }

      const data = await fetchNews(params)
      setResults(data.results || [])
      setTotalCount(data.count || 0)
    } catch (err) {
      console.error('Search failed:', err)
      setResults([])
      setTotalCount(0)
    } finally {
      setLoading(false)
    }
  }

  function handleSubmit(e) {
    e.preventDefault()
    if (!query.trim() || loading) return
    const params = new URLSearchParams()
    params.set('q', query.trim())
    params.set('mode', mode)
    params.set('page', '1')
    params.set('order_by', orderBy)
    if (fullContentOnly) params.set('full_content', 'true')
    if (days) params.set('days', days)
    if (sourceTypeFilters.length > 0) params.set('source_types', sourceTypeFilters.join(','))
    setSearchParams(params)
    setHasSearched(true)
    doSearch(query.trim(), mode, 1)
  }

  function handlePageChange(newPage) {
    const params = new URLSearchParams(searchParams)
    params.set('page', String(newPage))
    setSearchParams(params)
    doSearch(query.trim(), mode, newPage)
  }

  function toggleSourceType(key) {
    const next = sourceTypeFilters.includes(key)
      ? sourceTypeFilters.filter(k => k !== key)
      : [...sourceTypeFilters, key]
    setSourceTypeFilters(next)
    const params = new URLSearchParams(searchParams)
    if (next.length > 0) params.set('source_types', next.join(','))
    else params.delete('source_types')
    params.set('page', '1')
    setSearchParams(params)
    setHasSearched(true)
    doSearch(query.trim(), mode, 1)
  }

  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  const pageSize = 20
  const totalPages = Math.ceil(totalCount / pageSize)

  const hasActiveFilters = orderBy !== 'relevance' || fullContentOnly || days || sourceTypeFilters.length > 0
  const activeFilterCount = [
    orderBy !== 'relevance',
    fullContentOnly,
    !!days,
    sourceTypeFilters.length > 0,
  ].filter(Boolean).length

  return (
    <div className="max-w-6xl mx-auto px-4 py-6">
      {/* Header */}
      <div className="mb-4">
        <h1 className="text-2xl font-bold text-neutral-900">本地搜索</h1>
        <p className="mt-1 text-sm text-neutral-500">
          在本地新闻数据库中搜索相关文章
        </p>
      </div>

      {/* Search bar */}
      <form onSubmit={handleSubmit} className="mb-3">
        <div className="flex flex-col sm:flex-row gap-2">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-neutral-400 pointer-events-none" />
            <input
              ref={inputRef}
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={PLACEHOLDERS[Math.floor(Math.random() * PLACEHOLDERS.length)]}
              className="w-full pl-10 pr-4 py-2.5 rounded-xl border border-neutral-200
                         bg-white text-sm text-neutral-900 placeholder-neutral-400
                         focus:outline-none focus:ring-2 focus:ring-violet-400/50 focus:border-violet-400
                         transition-all shadow-sm"
            />
          </div>
          <button
            type="submit"
            disabled={loading || !query.trim()}
            className="px-6 py-2.5 rounded-xl bg-gradient-to-r from-violet-500 to-violet-600
                       text-white text-sm font-medium shadow-sm shadow-violet-200/50
                       hover:shadow-md hover:shadow-violet-300/50 hover:scale-[1.02]
                       active:scale-[0.98] transition-all
                       disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:scale-100
                       flex items-center justify-center gap-2"
          >
            {loading ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Search className="w-4 h-4" />
            )}
            {loading ? '搜索中…' : '搜索'}
          </button>
        </div>

        {/* Mode toggle */}
        <div className="mt-2 flex items-center gap-2">
          <span className="text-xs text-neutral-500">模式:</span>
          <PillGroup options={MODES} value={mode} onChange={(v) => {
            setMode(v)
            const params = new URLSearchParams(searchParams)
            params.set('mode', v)
            params.set('page', '1')
            setSearchParams(params)
            setHasSearched(true)
            doSearch(query.trim(), v, 1)
          }} />
          <span className="text-xs text-neutral-400">
            {MODE_HINTS[mode]}
          </span>
        </div>
      </form>

      {/* Filter controls */}
      <div className="mb-4 p-3 rounded-xl bg-neutral-50/80 border border-neutral-100">
        <div className="flex items-center gap-4 flex-wrap">
          {/* Sort order */}
          <div className="flex items-center gap-2">
            <span className="text-xs text-neutral-500 font-medium">排序</span>
            <PillGroup options={ORDER_BY_OPTIONS} value={orderBy} onChange={(v) => {
              setOrderBy(v)
              const params = new URLSearchParams(searchParams)
              params.set('order_by', v)
              params.set('page', '1')
              setSearchParams(params)
              setHasSearched(true)
              doSearch(query.trim(), mode, 1)
            }} />
          </div>

          {/* Full content toggle */}
          <button
            type="button"
            onClick={() => {
              const next = !fullContentOnly
              setFullContentOnly(next)
              const params = new URLSearchParams(searchParams)
              if (next) params.set('full_content', 'true')
              else params.delete('full_content')
              params.set('page', '1')
              setSearchParams(params)
              setHasSearched(true)
              doSearch(query.trim(), mode, 1)
            }}
            className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium
                         transition-all cursor-pointer border
                         ${fullContentOnly
                           ? 'bg-violet-500 border-violet-500 text-white shadow-sm'
                           : 'bg-white border-neutral-200 text-neutral-500 hover:border-violet-300 hover:bg-violet-50/50'
                         }`}
          >
            <span className={`w-3.5 h-3.5 rounded-sm border flex items-center justify-center transition-colors
              ${fullContentOnly ? 'bg-white/30 border-white/50' : 'border-neutral-300'}`}>
              {fullContentOnly && (
                <svg className="w-2.5 h-2.5 text-white" viewBox="0 0 12 12" fill="none">
                  <path d="M2 6l3 3 5-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                </svg>
              )}
            </span>
            仅全文
          </button>

          {/* Time range */}
          <div className="flex items-center gap-2">
            <span className="text-xs text-neutral-500 font-medium">时间</span>
            <PillGroup options={TIME_RANGES} value={days} onChange={(v) => {
              setDays(v)
              const params = new URLSearchParams(searchParams)
              if (v) params.set('days', v)
              else params.delete('days')
              params.set('page', '1')
              setSearchParams(params)
              setHasSearched(true)
              doSearch(query.trim(), mode, 1)
            }} />
          </div>

          {/* Filter toggle button */}
          <button
            type="button"
            onClick={() => setShowFilters(!showFilters)}
            className={`ml-auto inline-flex items-center gap-1 px-2 py-1 rounded-full
                         text-xs font-medium transition-colors cursor-pointer
                         ${hasActiveFilters
                           ? 'bg-violet-100 text-violet-700'
                           : 'text-neutral-400 hover:text-neutral-600 hover:bg-neutral-100'
                         }`}
          >
            <SlidersHorizontal className="w-3.5 h-3.5" />
            <span className="hidden sm:inline">筛选</span>
            {hasActiveFilters && (
              <span className="w-4 h-4 rounded-full bg-violet-500 text-white text-[10px] flex items-center justify-center">
                {activeFilterCount}
              </span>
            )}
          </button>
        </div>

        {/* Expanded filter panel */}
        {showFilters && (
          <div className="mt-3 pt-3 border-t border-neutral-200">
            <p className="text-xs text-neutral-500 mb-2 font-medium">来源类型:</p>
            <div className="flex gap-1.5">
              {SOURCE_TYPES.map(st => {
                const active = sourceTypeFilters.includes(st.key)
                return (
                  <button
                    key={st.key}
                    type="button"
                    onClick={() => toggleSourceType(st.key)}
                    className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all cursor-pointer
                      ${active
                        ? 'bg-violet-500 text-white shadow-sm'
                        : 'bg-white border border-neutral-200 text-neutral-600 hover:border-violet-300 hover:bg-violet-50/50'
                      }`}
                  >
                    {st.label}
                  </button>
                )
              })}
            </div>
          </div>
        )}
      </div>

      {/* Results area */}
      {loading ? (
        <div className="flex flex-col items-center justify-center py-16">
          <Loader2 className="w-8 h-8 text-violet-400 animate-spin mb-3" />
          <p className="text-sm text-neutral-500">正在搜索本地文章…</p>
        </div>
      ) : !hasSearched ? (
        <div className="flex flex-col items-center justify-center py-20 text-center">
          <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-violet-100 to-orange-50 flex items-center justify-center shadow-lg shadow-violet-100/50 mb-4">
            <FileText className="w-7 h-7 text-violet-500" />
          </div>
          <p className="text-lg font-bold text-neutral-900">本地文章搜索</p>
          <p className="mt-1.5 text-sm text-neutral-400 max-w-[320px] leading-relaxed">
            输入关键词或自然语言查询，搜索已收录的本地新闻文章
          </p>
          <div className="mt-4 flex flex-wrap gap-2 justify-center">
            {['AI 芯片', '开源项目', '技术趋势', '市场竞争'].map(suggestion => (
              <button
                key={suggestion}
                type="button"
                onClick={() => {
                  setQuery(suggestion)
                  const params = new URLSearchParams()
                  params.set('q', suggestion)
                  params.set('mode', mode)
                  params.set('page', '1')
                  params.set('order_by', orderBy)
                  if (fullContentOnly) params.set('full_content', 'true')
                  if (days) params.set('days', days)
                  if (sourceTypeFilters.length > 0) params.set('source_types', sourceTypeFilters.join(','))
                  setSearchParams(params)
                  setHasSearched(true)
                  doSearch(suggestion, mode, 1)
                }}
                className="px-3 py-1.5 rounded-full bg-white border border-neutral-200
                           text-xs text-neutral-600 hover:border-violet-300 hover:bg-violet-50/50
                           hover:text-violet-700 transition-all cursor-pointer"
              >
                {suggestion}
              </button>
            ))}
          </div>
        </div>
      ) : results.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <div className="w-14 h-14 rounded-2xl bg-neutral-100 flex items-center justify-center mb-3">
            <Search className="w-6 h-6 text-neutral-400" />
          </div>
          <p className="text-base font-medium text-neutral-700">未找到相关文章</p>
          <p className="mt-1 text-sm text-neutral-400">
            尝试更换关键词或切换搜索模式
          </p>
        </div>
      ) : (
        <>
          <p className="text-xs text-neutral-400 mb-3">
            找到 <span className="font-medium text-neutral-600">{totalCount}</span> 篇相关文章
            {orderBy === 'time' && '（按最新发布排序）'}
            {orderBy === 'relevance' && mode === 'semantic' && '（按语义相似度排序）'}
            {orderBy === 'relevance' && mode === 'hybrid' && '（混合排序）'}
            {orderBy === 'relevance' && mode === 'keyword' && '（关键词匹配）'}
            {fullContentOnly && ' · 仅全文'}
            {days && ` · 近 ${days} 天`}
          </p>

          <div className="space-y-2">
            {results.map(article => (
              <ArticleCard key={article.id} article={article} />
            ))}
          </div>

          {totalPages > 1 && (
            <Pagination
              currentPage={page}
              totalPages={totalPages}
              totalCount={totalCount}
              onPageChange={handlePageChange}
            />
          )}
        </>
      )}
    </div>
  )
}

/* ── Article Card ──────────────────────────────────────────────────── */

function ArticleCard({ article }) {
  const title = article.title_zh || article.title
  const snippet = article.content_zh || article.content || ''
  const sourceTypeLabels = { news: '新闻', aggregator: '聚合', discussion: '讨论' }
  const sourceTypeColors = {
    news: 'bg-blue-50 text-blue-600',
    aggregator: 'bg-amber-50 text-amber-600',
    discussion: 'bg-green-50 text-green-600',
  }

  return (
    <Link
      to={`/news/${article.id}`}
      className="group block p-4 rounded-xl bg-white border border-neutral-100
                 hover:border-violet-200 hover:bg-violet-50/30 hover:shadow-md
                 transition-all duration-150"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <h3 className="text-sm font-semibold text-neutral-900 group-hover:text-violet-800
                         transition-colors line-clamp-2">
            {title}
          </h3>
          {snippet && (
            <p className="mt-1 text-xs text-neutral-500 line-clamp-2 leading-relaxed">
              {snippet}
            </p>
          )}
        </div>
        {article.url && (
          <a
            href={article.url}
            target="_blank"
            rel="noopener noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="p-1 rounded-md text-neutral-400 hover:text-violet-500
                       hover:bg-violet-50 transition-colors"
            aria-label="打开原文"
          >
            <ExternalLink className="w-3.5 h-3.5" />
          </a>
        )}
      </div>

      <div className="mt-2.5 flex flex-wrap items-center gap-2">
        {article.source && (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-neutral-50 text-[11px] font-medium text-neutral-600">
            <Globe className="w-3 h-3" />
            {article.source.name}
          </span>
        )}
        {article.source?.source_type && (
          <span className={`px-2 py-0.5 rounded-md text-[11px] font-medium ${sourceTypeColors[article.source.source_type] || 'bg-neutral-50 text-neutral-600'}`}>
            {sourceTypeLabels[article.source.source_type] || article.source.source_type}
          </span>
        )}
        {article.category && (
          <span className="px-2 py-0.5 rounded-md bg-purple-50 text-[11px] font-medium text-purple-600">
            {article.category.name}
          </span>
        )}
        {article.publish_time && (
          <span className="inline-flex items-center gap-1 text-[11px] text-neutral-400">
            <Clock className="w-3 h-3" />
            {new Date(article.publish_time).toLocaleDateString('zh-CN', {
              year: 'numeric', month: 'short', day: 'numeric',
            })}
          </span>
        )}
        {article.full_content_fetch_status === 'success' && (
          <span className="inline-flex items-center gap-1 text-[11px] text-amber-500">
            <Star className="w-3 h-3" />
            全文可用
          </span>
        )}
      </div>
    </Link>
  )
}
