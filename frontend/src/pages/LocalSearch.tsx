import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useLocation, useNavigationType, useSearchParams } from 'react-router-dom'
import { AlertCircle, Clock, ExternalLink, FileText, Globe, Loader2, Search, SlidersHorizontal, Star } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { useAuth } from '@/context/AuthContext'
import { useLanguage } from '@/context/useLanguage'
import { newsListOptions, newsListPlaceholderData } from '@/services/newsQueries'
import { Pagination } from '@/components/Pagination'
import type { NewsListParams, NewsSummary, SearchMode, SearchOrderBy, SourceType } from '@/types/news'

const PAGE_SIZE = 20
const MODES: { key: SearchMode; label: string }[] = [
  { key: 'keyword', label: '关键词' },
  { key: 'semantic', label: '语义' },
  { key: 'hybrid', label: '混合' },
]
const MODE_HINTS: Record<SearchMode, string> = {
  keyword: '按关键词精确匹配标题和摘要',
  semantic: '按语义相似度理解你的意图',
  hybrid: '关键词 + 语义混合排序',
}
const PLACEHOLDERS = ['搜索本地新闻文章…', '输入话题、关键词或完整句子…']
const SOURCE_TYPES: { key: SourceType; label: string }[] = [
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
const ORDER_BY_OPTIONS: { key: SearchOrderBy; label: string }[] = [
  { key: 'relevance', label: '相关性' },
  { key: 'time', label: '最新发布' },
]
const SOURCE_TYPE_LABELS: Record<SourceType, string> = {
  news: '新闻',
  aggregator: '聚合',
  discussion: '讨论',
}
const SOURCE_TYPE_COLORS: Record<SourceType, string> = {
  news: 'bg-blue-50 text-blue-600',
  aggregator: 'bg-amber-50 text-amber-600',
  discussion: 'bg-green-50 text-green-600',
}

interface PillOption {
  key: string
  label: string
}

function PillGroup({ options, value, onChange }: {
  options: PillOption[]
  value: string
  onChange: (key: string) => void
}) {
  return (
    <div className="flex gap-1">
      {options.map((option) => (
        <button
          key={option.key}
          type="button"
          onClick={() => onChange(option.key)}
          aria-pressed={value === option.key}
          className={`cursor-pointer rounded-full px-2.5 py-1 text-xs font-medium transition-all ${value === option.key
            ? 'bg-violet-500 text-white shadow-sm'
            : 'border border-neutral-200 bg-white text-neutral-600 hover:border-violet-300 hover:bg-violet-50/50'}`}
        >
          {option.label}
        </button>
      ))}
    </div>
  )
}

function positiveInteger(value: string | null, fallback: number): number {
  if (!value) return fallback
  const parsed = Number(value)
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : fallback
}

function resolveMode(value: string | null): SearchMode {
  return MODES.some((option) => option.key === value) ? value as SearchMode : 'semantic'
}

function resolveOrderBy(value: string | null): SearchOrderBy {
  return ORDER_BY_OPTIONS.some((option) => option.key === value) ? value as SearchOrderBy : 'relevance'
}

function resolveDays(value: string | null): '' | '7' | '30' | '90' {
  return value === '7' || value === '30' || value === '90' ? value : ''
}

function resolveSourceTypes(value: string | null): SourceType[] {
  if (!value) return []
  const allowed = new Set(SOURCE_TYPES.map((option) => option.key))
  return value.split(',').filter((item): item is SourceType => allowed.has(item as SourceType))
}

function updateQueryParams(
  current: URLSearchParams,
  changes: Record<string, string | null>,
): URLSearchParams {
  const next = new URLSearchParams(current)
  for (const [key, value] of Object.entries(changes)) {
    if (value === null || value === '') next.delete(key)
    else next.set(key, value)
  }
  return next
}

function dateAfterDays(days: string): string | undefined {
  if (!days) return undefined
  const after = new Date()
  after.setDate(after.getDate() - Number(days))
  return after.toISOString().slice(0, 10)
}

export default function LocalSearch() {
  const [searchParams, setSearchParams] = useSearchParams()
  const location = useLocation()
  const navigationType = useNavigationType()
  const historyNavigationKey = navigationType === 'POP' ? location.key : null
  const { user, loading: authLoading } = useAuth()
  const { lang } = useLanguage()
  const submittedQuery = (searchParams.get('q') ?? '').trim()
  const mode = resolveMode(searchParams.get('mode'))
  const page = positiveInteger(searchParams.get('page'), 1)
  const orderBy = resolveOrderBy(searchParams.get('order_by'))
  const fullContentOnly = searchParams.get('full_content') === 'true'
  const days = resolveDays(searchParams.get('days'))
  const sourceTypeFilters = resolveSourceTypes(searchParams.get('source_types'))
  const sourceType = sourceTypeFilters[0]
  const [showFilters, setShowFilters] = useState(false)

  const viewerId = user?.id ?? 'anonymous'
  const publishTimeAfter = dateAfterDays(days)
  const params: NewsListParams = {
    page,
    page_size: PAGE_SIZE,
    ...(submittedQuery ? { search: submittedQuery, mode } : {}),
    order_by: orderBy,
    ...(fullContentOnly ? { full_content: 'true' as const } : {}),
    ...(publishTimeAfter ? { publish_time_after: publishTimeAfter } : {}),
    ...(sourceType ? { source__source_type: sourceType } : {}),
  }
  const newsQuery = useQuery({
    ...newsListOptions(params, lang, viewerId),
    enabled: !authLoading && Boolean(submittedQuery),
    placeholderData: newsListPlaceholderData(viewerId, lang),
  })

  const data = newsQuery.data
  const totalCount = data?.count ?? 0
  const totalPages = Math.ceil(totalCount / PAGE_SIZE)
  const activeFilterCount = [orderBy !== 'relevance', fullContentOnly, Boolean(days), sourceTypeFilters.length > 0]
    .filter(Boolean).length
  const hasActiveFilters = activeFilterCount > 0
  const initialLoading = Boolean(submittedQuery) && (authLoading || (newsQuery.isPending && !data))

  function handleSubmit(draft: string) {
    const query = draft.trim()
    if (!query) return
    const next = new URLSearchParams()
    next.set('q', query)
    next.set('mode', mode)
    next.set('page', '1')
    next.set('order_by', orderBy)
    if (fullContentOnly) next.set('full_content', 'true')
    if (days) next.set('days', days)
    if (sourceTypeFilters.length) next.set('source_types', sourceTypeFilters.join(','))
    setSearchParams(next)
  }

  function updateFilters(changes: Record<string, string | null>, resetPage = true) {
    setSearchParams(updateQueryParams(searchParams, {
      ...changes,
      ...(resetPage ? { page: '1' } : {}),
    }))
  }

  function changeSourceType(type: SourceType) {
    const next = sourceTypeFilters.includes(type)
      ? sourceTypeFilters.filter((value) => value !== type)
      : [...sourceTypeFilters, type]
    updateFilters({ source_types: next.length ? next.join(',') : null })
  }

  function startSuggestedSearch(query: string) {
    const next = new URLSearchParams()
    next.set('q', query)
    next.set('mode', mode)
    next.set('page', '1')
    next.set('order_by', orderBy)
    if (fullContentOnly) next.set('full_content', 'true')
    if (days) next.set('days', days)
    if (sourceTypeFilters.length) next.set('source_types', sourceTypeFilters.join(','))
    setSearchParams(next)
  }

  const searchButtonLabel = newsQuery.isFetching ? '搜索中…' : '搜索'

  return (
    <div className="mx-auto max-w-6xl px-4 py-6">
      <header className="mb-4">
        <h1 className="text-2xl font-bold text-neutral-900">本地搜索</h1>
        <p className="mt-1 text-sm text-neutral-500">在本地新闻数据库中搜索相关文章</p>
      </header>

      <SearchControls
        initialQuery={submittedQuery}
        historyNavigationKey={historyNavigationKey}
        mode={mode}
        searching={newsQuery.isFetching}
        buttonLabel={searchButtonLabel}
        onSubmit={handleSubmit}
        onModeChange={(value) => updateFilters({ mode: value })}
      />

      <section aria-label="搜索筛选" className="mb-4 rounded-xl border border-neutral-100 bg-neutral-50/80 p-3">
        <div className="flex flex-wrap items-center gap-4">
          <div className="flex items-center gap-2">
            <span className="text-xs font-medium text-neutral-500">排序</span>
            <PillGroup options={ORDER_BY_OPTIONS} value={orderBy} onChange={(value) => updateFilters({ order_by: value })} />
          </div>

          <button
            type="button"
            aria-pressed={fullContentOnly}
            onClick={() => updateFilters({ full_content: fullContentOnly ? null : 'true' })}
            className={`inline-flex cursor-pointer items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium transition-all ${fullContentOnly
              ? 'border-violet-500 bg-violet-500 text-white shadow-sm'
              : 'border-neutral-200 bg-white text-neutral-500 hover:border-violet-300 hover:bg-violet-50/50'}`}
          >
            <span className={`flex size-3.5 items-center justify-center rounded-sm border transition-colors ${fullContentOnly ? 'border-white/50 bg-white/30' : 'border-neutral-300'}`}>
              {fullContentOnly && <span aria-hidden="true" className="text-[10px] leading-none">✓</span>}
            </span>
            仅全文
          </button>

          <div className="flex items-center gap-2">
            <span className="text-xs font-medium text-neutral-500">时间</span>
            <PillGroup options={TIME_RANGES} value={days} onChange={(value) => updateFilters({ days: value || null })} />
          </div>

          <button
            type="button"
            aria-expanded={showFilters}
            onClick={() => setShowFilters((current) => !current)}
            className={`ml-auto inline-flex items-center gap-1 rounded-full px-2 py-1 text-xs font-medium transition-colors ${hasActiveFilters ? 'bg-violet-100 text-violet-700' : 'text-neutral-400 hover:bg-neutral-100 hover:text-neutral-600'}`}
          >
            <SlidersHorizontal className="size-3.5" />
            <span className="hidden sm:inline">筛选</span>
            {hasActiveFilters && <span className="flex size-4 items-center justify-center rounded-full bg-violet-500 text-[10px] text-white">{activeFilterCount}</span>}
          </button>
        </div>

        {showFilters && (
          <div className="mt-3 border-t border-neutral-200 pt-3">
            <p className="mb-2 text-xs font-medium text-neutral-500">来源类型:</p>
            <div className="flex flex-wrap gap-1.5">
              {SOURCE_TYPES.map((source) => {
                const active = sourceTypeFilters.includes(source.key)
                return (
                  <button
                    key={source.key}
                    type="button"
                    aria-pressed={active}
                    onClick={() => changeSourceType(source.key)}
                    className={`cursor-pointer rounded-lg px-3 py-1.5 text-xs font-medium transition-all ${active
                      ? 'bg-violet-500 text-white shadow-sm'
                      : 'border border-neutral-200 bg-white text-neutral-600 hover:border-violet-300 hover:bg-violet-50/50'}`}
                  >
                    {source.label}
                  </button>
                )
              })}
            </div>
          </div>
        )}
      </section>

      {data?.searchWarning === 'semantic_index_unavailable' && (
        <div role="status" className="my-4 flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          <AlertCircle aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
          <span>语义索引正在恢复，当前显示关键词结果。</span>
        </div>
      )}

      {newsQuery.isError && (
        <div role="alert" className="my-4 flex items-center justify-center gap-3 text-center text-sm text-red-700">
          <span>搜索失败，请稍后重试。</span>
          <button type="button" className="underline" onClick={() => void newsQuery.refetch()}>重试</button>
        </div>
      )}

      {initialLoading ? (
        <div className="flex flex-col items-center justify-center py-16" role="status" aria-live="polite">
          <Loader2 className="mb-3 size-8 animate-spin text-violet-400" />
          <p className="text-sm text-neutral-500">正在搜索本地文章…</p>
        </div>
      ) : !submittedQuery ? (
        <div className="flex flex-col items-center justify-center py-20 text-center">
          <div className="mb-4 flex size-16 items-center justify-center rounded-2xl bg-gradient-to-br from-violet-100 to-orange-50 shadow-lg shadow-violet-100/50">
            <FileText className="size-7 text-violet-500" />
          </div>
          <p className="text-lg font-bold text-neutral-900">本地文章搜索</p>
          <p className="mt-1.5 max-w-[320px] text-sm leading-relaxed text-neutral-400">输入关键词或自然语言查询，搜索已收录的本地新闻文章</p>
          <div className="mt-4 flex flex-wrap justify-center gap-2">
            {['AI 芯片', '开源项目', '技术趋势', '市场竞争'].map((suggestion) => (
              <button key={suggestion} type="button" onClick={() => startSuggestedSearch(suggestion)} className="cursor-pointer rounded-full border border-neutral-200 bg-white px-3 py-1.5 text-xs text-neutral-600 transition-all hover:border-violet-300 hover:bg-violet-50/50 hover:text-violet-700">
                {suggestion}
              </button>
            ))}
          </div>
        </div>
      ) : !data?.results.length ? (
        !newsQuery.isError && !newsQuery.isFetching && (
          <div className="flex flex-col items-center justify-center py-16 text-center">
            <div className="mb-3 flex size-14 items-center justify-center rounded-2xl bg-neutral-100"><Search className="size-6 text-neutral-400" /></div>
            <p className="text-base font-medium text-neutral-700">未找到相关文章</p>
            <p className="mt-1 text-sm text-neutral-400">尝试更换关键词或切换搜索模式</p>
          </div>
        )
      ) : (
        <>
          <p className="mb-3 text-xs text-neutral-400">
            找到 <span className="font-medium text-neutral-600">{totalCount}</span> 篇相关文章
            {orderBy === 'time' && '（按最新发布排序）'}
            {orderBy === 'relevance' && mode === 'semantic' && '（按语义相似度排序）'}
            {orderBy === 'relevance' && mode === 'hybrid' && '（混合排序）'}
            {orderBy === 'relevance' && mode === 'keyword' && '（关键词匹配）'}
            {fullContentOnly && ' · 仅全文'}
            {days && ` · 近 ${days} 天`}
          </p>
          <div className="space-y-2" aria-busy={newsQuery.isFetching}>
            {data.results.map((article) => <ArticleCard key={article.id} article={article} returnTo={`${location.pathname}${location.search}${location.hash}`} />)}
          </div>
          {newsQuery.isFetching && <p role="status" className="py-3 text-center text-sm text-neutral-400">正在更新…</p>}
          {totalPages > 1 && (
            <Pagination
              currentPage={page}
              totalPages={totalPages}
              totalCount={totalCount}
              onPageChange={(nextPage) => {
                setSearchParams(updateQueryParams(searchParams, { page: nextPage === 1 ? null : String(nextPage) }))
                window.scrollTo({ top: 0, behavior: 'smooth' })
              }}
            />
          )}
        </>
      )}
    </div>
  )
}

function SearchControls({ initialQuery, historyNavigationKey, mode, searching, buttonLabel, onSubmit, onModeChange }: {
  initialQuery: string
  historyNavigationKey: string | null
  mode: SearchMode
  searching: boolean
  buttonLabel: string
  onSubmit: (query: string) => void
  onModeChange: (mode: SearchMode) => void
}) {
  const [draft, setDraft] = useState(initialQuery)
  const previousQueryRef = useRef(initialQuery)
  const previousHistoryNavigationKeyRef = useRef(historyNavigationKey)

  useEffect(() => {
    const queryChanged = previousQueryRef.current !== initialQuery
    const returnedFromHistory = historyNavigationKey !== null
      && historyNavigationKey !== previousHistoryNavigationKeyRef.current

    if (queryChanged || returnedFromHistory) setDraft(initialQuery)
    previousQueryRef.current = initialQuery
    previousHistoryNavigationKeyRef.current = historyNavigationKey
  }, [historyNavigationKey, initialQuery])

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    onSubmit(draft)
  }

  return (
    <form onSubmit={handleSubmit} className="mb-3">
      <div className="flex flex-col gap-2 sm:flex-row">
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-neutral-400" />
          <input
            type="search"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder={PLACEHOLDERS[0]}
            aria-label="搜索本地新闻文章"
            className="w-full rounded-xl border border-neutral-200 bg-white py-2.5 pl-10 pr-4 text-sm text-neutral-900 shadow-sm transition-all placeholder:text-neutral-400 focus:border-violet-400 focus:outline-none focus:ring-2 focus:ring-violet-400/50"
          />
        </div>
        <button
          type="submit"
          disabled={searching || !draft.trim()}
          className="flex items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-violet-500 to-violet-600 px-6 py-2.5 text-sm font-medium text-white shadow-sm shadow-violet-200/50 transition-all hover:scale-[1.02] hover:shadow-md hover:shadow-violet-300/50 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:scale-100"
        >
          {searching ? <Loader2 className="size-4 animate-spin" /> : <Search className="size-4" />}
          {buttonLabel}
        </button>
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-2">
        <span className="text-xs text-neutral-500">模式:</span>
        <PillGroup options={MODES} value={mode} onChange={(value) => onModeChange(resolveMode(value))} />
        <span className="text-xs text-neutral-400">{MODE_HINTS[mode]}</span>
      </div>
    </form>
  )
}

function ArticleCard({ article, returnTo }: { article: NewsSummary; returnTo: string }) {
  const title = article.title_zh || article.title
  const snippet = article.content_zh || article.content
  const sourceType = article.source_type as SourceType

  return (
    <article className="group block rounded-xl border border-neutral-100 bg-white p-4 transition-all duration-150 hover:border-violet-200 hover:bg-violet-50/30 hover:shadow-md">
      <div className="flex items-start justify-between gap-3">
        <Link to={`/news/${article.id}`} state={{ from: returnTo }} className="min-w-0 flex-1 rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500">
          <h2 className="line-clamp-2 text-sm font-semibold text-neutral-900 transition-colors group-hover:text-violet-800">{title}</h2>
          {snippet && <p className="mt-1 line-clamp-2 text-xs leading-relaxed text-neutral-500">{snippet}</p>}
        </Link>
        {article.url && (
          <a href={article.url} target="_blank" rel="noopener noreferrer" className="rounded-md p-1 text-neutral-400 transition-colors hover:bg-violet-50 hover:text-violet-500" aria-label="打开原文">
            <ExternalLink className="size-3.5" />
          </a>
        )}
      </div>

      <div className="mt-2.5 flex flex-wrap items-center gap-2">
        {article.source_name && <span className="inline-flex items-center gap-1 rounded-md bg-neutral-50 px-2 py-0.5 text-[11px] font-medium text-neutral-600"><Globe className="size-3" />{article.source_name}</span>}
        {sourceType in SOURCE_TYPE_LABELS && <span className={`rounded-md px-2 py-0.5 text-[11px] font-medium ${SOURCE_TYPE_COLORS[sourceType]}`}>{SOURCE_TYPE_LABELS[sourceType]}</span>}
        {article.category_name && <span className="rounded-md bg-purple-50 px-2 py-0.5 text-[11px] font-medium text-purple-600">{article.category_name}</span>}
        {article.publish_time && <span className="inline-flex items-center gap-1 text-[11px] text-neutral-400"><Clock className="size-3" />{new Date(article.publish_time).toLocaleDateString('zh-CN', { year: 'numeric', month: 'short', day: 'numeric' })}</span>}
        {article.full_content_fetch_status === 'success' && <span className="inline-flex items-center gap-1 text-[11px] text-amber-500"><Star className="size-3" />全文可用</span>}
      </div>
    </article>
  )
}
