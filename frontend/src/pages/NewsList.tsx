import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useLocation, useNavigationType, useSearchParams } from 'react-router-dom'
import { useAuth } from '@/context/AuthContext'
import { useLanguage } from '@/context/useLanguage'
import { categoryOptions, newsListOptions, newsListPlaceholderData, sourceOptions } from '@/services/newsQueries'
import type { NewsListParams, NewsSummary, SearchMode } from '@/types/news'
import NewsCard from '@/components/NewsCard'
import type { BlockedNewsTarget } from '@/components/NewsCard'
import SearchBar from '@/components/SearchBar'
import NewsFilters from '@/components/NewsFilters'
import LoadingSpinner from '@/components/LoadingSpinner'
import { Pagination } from '@/components/Pagination'
import { Button } from '@/components/ui/button'
import { useUnblockNews } from '@/hooks/useNewsMutations'

const PAGE_SIZE = 20
const LEGACY_FILTERS_KEY = 'news-aggregator-filters'
const modes: SearchMode[] = ['keyword', 'semantic', 'hybrid']

function selectedIds(value: string | null): number[] {
  return value?.split(',').map((id) => Number(id.trim())).filter((id) => Number.isSafeInteger(id) && id > 0) ?? []
}

function positiveInteger(value: string | null, fallback: number): number {
  if (!value) return fallback
  const parsed = Number(value)
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : fallback
}

interface LegacyFilters {
  search: string
  mode: SearchMode
  categories: number[]
  sources: number[]
}

function readLegacyFilters(): LegacyFilters | null {
  try {
    const raw = localStorage.getItem(LEGACY_FILTERS_KEY)
    if (!raw) return null
    const value: unknown = JSON.parse(raw)
    if (typeof value !== 'object' || value === null || Array.isArray(value)) return null
    const saved = value as Record<string, unknown>
    const search = typeof saved.search === 'string' ? saved.search.trim() : ''
    const rawMode = saved.searchMode
    const mode = modes.includes(rawMode as SearchMode) ? rawMode as SearchMode : 'hybrid'
    const numericIds = (ids: unknown) => Array.isArray(ids)
      ? ids.map(Number).filter((id) => Number.isSafeInteger(id) && id > 0)
      : []
    const categories = numericIds(saved.categories)
    const sources = numericIds(saved.sources)
    if (!search && categories.length === 0 && sources.length === 0) return null
    return { search, mode, categories, sources }
  } catch {
    return null
  }
}

export default function NewsList() {
  const { lang } = useLanguage()
  const { user, loading: authLoading } = useAuth()
  const location = useLocation()
  const navigationType = useNavigationType()
  const historyNavigationKey = navigationType === 'POP' ? location.key : null
  const [searchParams, setSearchParams] = useSearchParams()
  const search = searchParams.get('search') ?? ''
  const rawMode = searchParams.get('mode')
  const mode: SearchMode = modes.includes(rawMode as SearchMode) ? rawMode as SearchMode : 'hybrid'
  const categories = selectedIds(searchParams.get('category'))
  const sources = selectedIds(searchParams.get('source'))
  const page = positiveInteger(searchParams.get('page'), 1)
  const hasUrlFilters = ['search', 'mode', 'category', 'source', 'page'].some((key) => searchParams.has(key))
  const legacySignature = hasUrlFilters ? null : JSON.stringify(readLegacyFilters())
  const legacyToMigrate = legacySignature && legacySignature !== 'null'

  useEffect(() => {
    if (!legacyToMigrate || !legacySignature) return
    const saved = JSON.parse(legacySignature) as LegacyFilters
    const next = new URLSearchParams(searchParams)
    if (saved.search) next.set('search', saved.search)
    if (saved.search && saved.mode !== 'hybrid') next.set('mode', saved.mode)
    if (saved.categories.length) next.set('category', saved.categories.join(','))
    if (saved.sources.length) next.set('source', saved.sources.join(','))
    setSearchParams(next, { replace: true })
    try { localStorage.removeItem(LEGACY_FILTERS_KEY) } catch { /* private browsing can disable storage */ }
  }, [legacySignature, legacyToMigrate, searchParams, setSearchParams])

  const query: NewsListParams = {
    page,
    page_size: PAGE_SIZE,
    ...(search.trim() ? { search: search.trim(), mode } : {}),
    ...(categories.length ? { category: categories.join(',') } : {}),
    ...(sources.length ? { source: sources.join(',') } : {}),
  }
  const viewerId: number | string = user?.id ?? 'anonymous'
  const newsQuery = useQuery({
    ...newsListOptions(query, lang, viewerId),
    enabled: !authLoading && !legacyToMigrate,
    placeholderData: newsListPlaceholderData(viewerId, lang),
  })
  const categoriesQuery = useQuery(categoryOptions(lang))
  const sourcesQuery = useQuery(sourceOptions(lang))
  const currentViewerId = user?.id ?? null

  function updateParams(changes: Record<string, string | null>, replace = false) {
    const next = new URLSearchParams(searchParams)
    for (const [key, value] of Object.entries(changes)) {
      if (value === null || value === '') next.delete(key)
      else next.set(key, value)
    }
    setSearchParams(next, { replace })
  }

  function updateFilter(key: 'category' | 'source', values: number[]) {
    updateParams({ [key]: values.length ? values.join(',') : null, page: null })
  }

  const data = newsQuery.data
  const totalPages = Math.ceil((data?.count ?? 0) / PAGE_SIZE)
  const initialLoading = authLoading || newsQuery.isPending
  const activeFilterCount = categories.length + sources.length + (search.trim() ? 1 : 0)

  return (
    <div className="mx-auto max-w-6xl px-4 py-6">
      <header className="mb-6">
        <p className="text-xs font-semibold uppercase tracking-[0.18em] text-emerald-800 dark:text-emerald-400 font-mono">{lang === 'en' ? 'Your news feed' : '你的资讯流'}</p>
        <div className="mt-1 flex flex-wrap items-end justify-between gap-2">
          <div>
            <h1 id="news-list-title" tabIndex={-1} className="rounded-sm text-2xl font-bold tracking-tight text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary font-serif">{lang === 'en' ? 'Latest news' : '最新资讯'}</h1>
            <p className="mt-1 text-xs text-muted-foreground">{lang === 'en' ? 'Scan summaries, then open the stories worth your time.' : '先快速浏览摘要，再打开值得深入阅读的内容。'}</p>
          </div>
          {!initialLoading && data && <p className="text-xs text-muted-foreground"><span className="font-semibold text-foreground font-mono">{data.count}</span> {lang === 'en' ? 'stories' : '篇内容'}</p>}
        </div>
      </header>

      <div className="mb-3">
        <SearchBar
          value={search}
          mode={mode}
          historyNavigationKey={historyNavigationKey}
          onChange={(value) => updateParams({ search: value.trim() || null, page: null }, true)}
          onModeChange={(value) => updateParams({ mode: value, page: null })}
        />
      </div>

      <NewsFilters
        categories={categoriesQuery.data ?? []}
        sources={sourcesQuery.data ?? []}
        activeCategories={categories}
        activeSources={sources}
        onCategoriesChange={(values) => updateFilter('category', values)}
        onSourcesChange={(values) => updateFilter('source', values)}
        onClear={() => updateParams({ category: null, source: null, page: null })}
      />

      {activeFilterCount > 0 && (
        <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-xs text-neutral-500" role="status">
          <span>{lang === 'en' ? `${activeFilterCount} active condition${activeFilterCount === 1 ? '' : 's'}` : `已启用 ${activeFilterCount} 个条件`}</span>
          <Button type="button" variant="ghost" size="sm" onClick={() => updateParams({ search: null, mode: null, category: null, source: null, page: null })} className="h-7 rounded-full px-2 text-xs">
            {lang === 'en' ? 'Clear all' : '清除全部条件'}
          </Button>
        </div>
      )}

      {(categoriesQuery.isError || sourcesQuery.isError) && (
        <div role="alert" className="mb-4 flex items-center gap-3 text-sm text-red-700">
          <span>{lang === 'en' ? 'Filters could not be loaded.' : '筛选项加载失败。'}</span>
          {categoriesQuery.isError && <button type="button" className="underline" onClick={() => void categoriesQuery.refetch()}>{lang === 'en' ? 'Retry categories' : '重试分类'}</button>}
          {sourcesQuery.isError && <button type="button" className="underline" onClick={() => void sourcesQuery.refetch()}>{lang === 'en' ? 'Retry sources' : '重试来源'}</button>}
        </div>
      )}

      {newsQuery.isError && !data && (
        <div role="alert" className="my-10 text-center text-sm text-red-700">
          <p>{lang === 'en' ? 'News could not be loaded.' : '新闻加载失败。'}</p>
          <button type="button" className="mt-2 underline" onClick={() => void newsQuery.refetch()}>{lang === 'en' ? 'Retry' : '重试'}</button>
        </div>
      )}

      {initialLoading && <LoadingSpinner />}
      {!initialLoading && !newsQuery.isError && data?.results.length === 0 && (
        <div className="py-20 text-center text-gray-400">
          <p className="text-lg">{lang === 'en' ? 'No results found' : '未找到结果'}</p>
          {!search.trim() && categories.length === 0 && sources.length === 0 && (
            <p className="mt-1 text-sm">{lang === 'en' ? 'Run crawler first: python manage.py crawl' : '请先运行爬虫: python manage.py crawl'}</p>
          )}
        </div>
      )}

      <NewsResults
        key={viewerId}
        results={data?.results ?? []}
        viewerId={currentViewerId}
        lang={lang}
        fetching={newsQuery.isFetching}
      />

      {newsQuery.isFetching && !initialLoading && <div className="py-3 text-center text-sm text-gray-400" role="status">{lang === 'en' ? 'Updating…' : '正在更新…'}</div>}
      {!initialLoading && totalPages > 1 && (
        <Pagination
          currentPage={page}
          totalPages={totalPages}
          totalCount={data?.count ?? 0}
          onPageChange={(nextPage) => {
            updateParams({ page: nextPage === 1 ? null : String(nextPage) })
            window.scrollTo({ top: 0, behavior: 'smooth' })
          }}
          lang={lang}
        />
      )}

    </div>
  )
}

function NewsResults({ results, viewerId, lang, fetching }: {
  results: NewsSummary[]
  viewerId: number | null
  lang: 'zh' | 'en'
  fetching: boolean
}) {
  const unblockMutation = useUnblockNews()
  const blockVersionRef = useRef(0)
  const latestSuccessfulBlockVersionRef = useRef(0)
  const undoTargetRef = useRef<BlockedNewsTarget | null>(null)
  const undoButtonRef = useRef<HTMLButtonElement | null>(null)
  const [hiddenBlockedIds, setHiddenBlockedIds] = useState<Set<number>>(() => new Set())
  const [undoTarget, setUndoTarget] = useState<BlockedNewsTarget | null>(null)
  const [undoPendingVersion, setUndoPendingVersion] = useState<number | null>(null)
  const [undoErrorVersion, setUndoErrorVersion] = useState<number | null>(null)
  const visibleResults = results.filter((item) => !hiddenBlockedIds.has(item.id))

  function startBlock(_newsId: number, initiatingViewerId: number) {
    if (initiatingViewerId !== viewerId) return -1
    blockVersionRef.current += 1
    return blockVersionRef.current
  }

  function finishBlock(target: BlockedNewsTarget) {
    if (target.version < 0 || target.viewerId !== viewerId) return
    setHiddenBlockedIds((current) => new Set(current).add(target.newsId))
    if (target.version < latestSuccessfulBlockVersionRef.current) return
    latestSuccessfulBlockVersionRef.current = target.version
    undoTargetRef.current = target
    setUndoErrorVersion(null)
    setUndoTarget(target)
    requestAnimationFrame(() => undoButtonRef.current?.focus())
  }

  function targetIsCurrent(target: BlockedNewsTarget) {
    const current = undoTargetRef.current
    return current?.viewerId === target.viewerId
      && current.newsId === target.newsId
      && current.version === target.version
  }

  async function undoBlock() {
    const target = undoTargetRef.current
    if (!target || target.viewerId !== viewerId) return
    setUndoPendingVersion(target.version)
    setUndoErrorVersion(null)
    try {
      await unblockMutation.mutateAsync({ newsId: target.newsId, viewerId: target.viewerId })
      setHiddenBlockedIds((current) => {
        const next = new Set(current)
        next.delete(target.newsId)
        return next
      })
      if (targetIsCurrent(target)) {
        undoTargetRef.current = null
        setUndoTarget(null)
      }
      requestAnimationFrame(() => {
        const restoredLink = document.getElementById(`news-card-${target.newsId}`)
        const fallbackHeading = document.getElementById('news-list-title')
        ;(restoredLink ?? fallbackHeading)?.focus()
      })
    } catch {
      if (targetIsCurrent(target)) setUndoErrorVersion(target.version)
    } finally {
      setUndoPendingVersion((current) => current === target.version ? null : current)
    }
  }

  function dismissUndo() {
    undoTargetRef.current = null
    setUndoTarget(null)
    setUndoErrorVersion(null)
  }

  return (
    <>
      <div className="mt-5 grid grid-cols-1 gap-5 md:grid-cols-2" aria-busy={fetching}>
        {visibleResults.map((item) => (
          <NewsCard key={item.id} news={item} onBlockStart={startBlock} onBlocked={finishBlock} />
        ))}
      </div>

      {undoTarget !== null && (
        <div className="fixed bottom-5 left-1/2 z-50 flex w-[min(92vw,28rem)] -translate-x-1/2 items-center gap-3 rounded-2xl bg-neutral-900 px-4 py-3 text-sm text-white shadow-2xl" role="status" aria-live="polite">
          <span className="min-w-0 flex-1">{lang === 'en' ? 'News hidden from your feed.' : '已从资讯流中屏蔽这篇新闻。'}</span>
          <button ref={undoButtonRef} type="button" onClick={() => void undoBlock()} disabled={undoPendingVersion === undoTarget.version} className="min-h-11 shrink-0 rounded-lg px-3 py-1 font-semibold text-amber-300 hover:bg-white/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-300 disabled:opacity-50 sm:min-h-8">
            {undoPendingVersion === undoTarget.version ? (lang === 'en' ? 'Restoring…' : '恢复中…') : (lang === 'en' ? 'Undo' : '撤销')}
          </button>
          <button type="button" aria-label={lang === 'en' ? 'Dismiss' : '关闭提示'} onClick={dismissUndo} className="flex size-11 shrink-0 items-center justify-center rounded-lg text-neutral-300 hover:bg-white/10 hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white sm:size-8">×</button>
        </div>
      )}
      {undoTarget && undoErrorVersion === undoTarget.version && <p role="alert" className="fixed bottom-20 left-1/2 z-50 -translate-x-1/2 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700 shadow">{lang === 'en' ? 'Could not restore this news.' : '恢复失败，请重试。'}</p>}
    </>
  )
}
