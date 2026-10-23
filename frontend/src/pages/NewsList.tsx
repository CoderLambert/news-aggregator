import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useLocation, useNavigationType, useSearchParams } from 'react-router-dom'
import { useAuth } from '@/context/AuthContext'
import { useLanguage } from '@/context/useLanguage'
import { categoryOptions, newsListOptions, sourceOptions } from '@/services/newsQueries'
import type { NewsListParams, NewsSummary, SearchMode } from '@/types/news'
import NewsCard from '@/components/NewsCard'
import type { BlockedNewsTarget } from '@/components/NewsCard'
import SearchBar from '@/components/SearchBar'
import NewsFilters from '@/components/NewsFilters'
import LoadingSpinner from '@/components/LoadingSpinner'
import { Pagination } from '@/components/Pagination'
import { Button } from '@/components/ui/button'
import { useUnblockNews } from '@/hooks/useNewsMutations'
import { useNewsScope } from '@/hooks/useNewsScope'
import NewsScopeBar from '@/components/NewsScopeBar'
import AuthModal from '@/components/AuthModal'
import { useCapability } from '@/context/CapabilitiesContext'

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
  const semanticSearchEnabled = useCapability('semantic_search').enabled
  const blockedNewsEnabled = useCapability('blocked_news').enabled
  const location = useLocation()
  const navigationType = useNavigationType()
  const historyNavigationKey = navigationType === 'POP' ? location.key : null
  const [searchParams, setSearchParams] = useSearchParams()
  const invalidRegion = searchParams.has('region') && !['domestic', 'international'].includes(searchParams.get('region') ?? '')
  const region = searchParams.get('region') === 'domestic' ? 'domestic' : searchParams.get('region') === 'international' ? 'international' : 'all'
  const search = searchParams.get('search') ?? ''
  const rawMode = searchParams.get('mode')
  const requestedMode: SearchMode = modes.includes(rawMode as SearchMode) ? rawMode as SearchMode : 'hybrid'
  const mode: SearchMode = semanticSearchEnabled ? requestedMode : 'keyword'
  const categories = selectedIds(searchParams.get('category'))
  const sources = selectedIds(searchParams.get('source'))
  const page = positiveInteger(searchParams.get('page'), 1)
  const hasUrlFilters = ['search', 'mode', 'category', 'source', 'page', 'scope', 'region'].some((key) => searchParams.has(key))
  const legacySignature = hasUrlFilters ? null : JSON.stringify(readLegacyFilters())
  const [showLogin, setShowLogin] = useState(false)
  const legacyToMigrate = legacySignature && legacySignature !== 'null'

  const reading = useNewsScope(searchParams, setSearchParams, Boolean(legacyToMigrate))

  useEffect(() => {
    if (semanticSearchEnabled || !rawMode || rawMode === 'keyword') return
    const next = new URLSearchParams(searchParams)
    next.set('mode', 'keyword')
    setSearchParams(next, { replace: true })
  }, [rawMode, searchParams, semanticSearchEnabled, setSearchParams])

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
    ...(region !== 'all' ? { region } : {}),
    ...(reading.enabled || reading.scope !== 'all' ? { scope: reading.scope, ...(reading.groupId !== undefined ? { group_id: reading.groupId } : {}) } : {}),
    ...(search.trim() ? { search: search.trim(), mode } : {}),
    ...(categories.length ? { category: categories.join(',') } : {}),
    ...(sources.length ? { source: sources.join(',') } : {}),
  }
  const viewerId: number | string = user?.id ?? 'anonymous'
  const newsQuery = useQuery({
    ...newsListOptions(query, lang, viewerId, reading.sourceIds),
    enabled: !invalidRegion && !authLoading && reading.ready && !reading.configError,
    // Changing reading conditions clears old results and aborts their requests.
    placeholderData: undefined,
  })
  const categoriesQuery = useQuery(categoryOptions(lang))
  const sourcesQuery = useQuery(sourceOptions(lang, viewerId, 'history'))
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

  const data = !invalidRegion && reading.ready && !reading.configError && !authLoading ? newsQuery.data : undefined
  const totalPages = Math.ceil((data?.count ?? 0) / PAGE_SIZE)
  const initialLoading = !invalidRegion && !reading.configError && !reading.needsLogin && !reading.invalidScope && (authLoading || newsQuery.isPending)
  const activeFilterCount = categories.length + sources.length + (search.trim() ? 1 : 0) + (region !== 'all' ? 1 : 0)

  return (
    <div className="mx-auto max-w-6xl px-4 py-6">
      <h1 id="news-list-title" tabIndex={-1} className="sr-only">{lang === 'en' ? 'Latest news' : '最新资讯'}</h1>

      <NewsScopeBar scope={reading.scope} groupId={reading.groupId} groups={reading.groups.data ?? []}
        personal={reading.enabled} accounts={reading.accounts} onChange={reading.select}
        resultCount={!initialLoading && data ? data.count : undefined}
        region={region} onRegionChange={value => updateParams({ region: value === 'all' ? null : value, source: null, page: null })} />
      {invalidRegion && <p role="alert">无效的频道地区，请选择全部、国内或国际。</p>}
      {reading.notice && <p role="status" className="mb-3 text-sm text-muted-foreground">{reading.notice}</p>}
      {reading.configError && <div role="alert" className="mb-3 text-sm text-destructive">个人频道配置加载失败，筛选尚未应用。 <button className="underline" onClick={() => void reading.retry()}>重试</button></div>}
      {reading.saveError && <div role="alert" className="mb-3 text-sm text-destructive">上次查看范围保存失败。 <button className="underline" onClick={reading.retrySave}>重试保存</button></div>}
      {reading.invalidScope && <div role="alert">无效的资讯范围。 <button className="underline" onClick={() => reading.select('all')}>全部资讯</button></div>}
      {reading.needsLogin && <p role="status" className="mb-3">登录后查看个人频道范围。 <button className="underline" onClick={() => setShowLogin(true)}>登录</button></p>}
      {showLogin && <AuthModal onClose={() => setShowLogin(false)} />}

      <div className="mt-3 rounded-2xl border border-border bg-card p-3 sm:p-4">
        <div className="mb-2">
        <SearchBar
          value={search}
          mode={mode}
          allowSemantic={semanticSearchEnabled}
          historyNavigationKey={historyNavigationKey}
          onChange={(value) => updateParams({ search: value.trim() || null, page: null }, true)}
          onModeChange={(value) => updateParams({ mode: value, page: null })}
        />
        <p className="mt-2 break-words text-xs text-muted-foreground" aria-label="当前搜索范围">搜索范围：{reading.scope === 'group'
          ? (reading.groups.data?.find(group => group.id === reading.groupId)?.name ?? '当前分组')
          : reading.scope === 'subscribed' ? '我的订阅' : reading.scope === 'ungrouped' ? '未加入分组' : '全部资讯'}</p>
        {!semanticSearchEnabled && <p className="mt-1 text-xs text-muted-foreground" role="status">当前仅支持关键词搜索。</p>}
      </div>

      <NewsFilters embedded
        categories={categoriesQuery.data ?? []}
        sources={(sourcesQuery.data ?? []).filter(s => (reading.sourceIds === null || reading.sourceIds.includes(s.id)) && (region === 'all' || s.region === region))}
        activeCategories={categories}
        activeSources={sources}
        onCategoriesChange={(values) => updateFilter('category', values)}
        onSourcesChange={(values) => updateFilter('source', values)}
        onClear={() => updateParams({ category: null, source: null, page: null })}
      />

      {(Boolean(search.trim()) || region !== 'all') && activeFilterCount > 0 && (
        <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground" role="status">
          <span>{lang === 'en' ? `${activeFilterCount} active condition${activeFilterCount === 1 ? '' : 's'}` : `已启用 ${activeFilterCount} 个条件`}</span>
          <Button type="button" variant="ghost" size="sm" onClick={() => updateParams({ search: null, mode: null, region: null, category: null, source: null, page: null })} className="h-7 rounded-full px-2 text-xs">
            {lang === 'en' ? 'Clear all' : '清除全部条件'}
          </Button>
        </div>
      )}

      </div>

      {(categoriesQuery.isError || sourcesQuery.isError) && (
        <div role="alert" className="mb-4 flex items-center gap-3 text-sm text-destructive">
          <span>{lang === 'en' ? 'Filters could not be loaded.' : '筛选项加载失败。'}</span>
          {categoriesQuery.isError && <button type="button" className="underline" onClick={() => void categoriesQuery.refetch()}>{lang === 'en' ? 'Retry categories' : '重试分类'}</button>}
          {sourcesQuery.isError && <button type="button" className="underline" onClick={() => void sourcesQuery.refetch()}>{lang === 'en' ? 'Retry sources' : '重试来源'}</button>}
        </div>
      )}

      {newsQuery.isError && !data && (
        <div role="alert" className="my-10 text-center text-sm text-destructive">
          <p>{lang === 'en' ? 'News could not be loaded.' : '新闻加载失败。'}</p>
          <button type="button" className="mt-2 underline" onClick={() => void newsQuery.refetch()}>{lang === 'en' ? 'Retry' : '重试'}</button>
        </div>
      )}

      {initialLoading && <LoadingSpinner />}
      {!initialLoading && !newsQuery.isError && data?.results.length === 0 && (
        <div className="py-20 text-center text-muted-foreground">
          <p className="text-lg">{lang === 'en' ? 'No results found' : '未找到结果'}</p>
          {reading.enabled && reading.scope === 'group' && search.trim() && <Button type="button" variant="outline" className="mt-3"
            onClick={() => updateParams({ scope: 'subscribed', group_id: null, page: null })}>搜索全部订阅</Button>}
          {reading.scope !== 'all' && reading.sourceIds?.length === 0 ? (
            <Link to="/channels" className="mt-3 inline-block text-primary underline">{reading.scope === 'group' ? '添加频道' : '选择频道'}</Link>
          ) : activeFilterCount > 0 ? (
            <button type="button" className="mt-3 text-primary underline" onClick={() => updateParams({ search: null, region: null, category: null, source: null, page: null })}>清除筛选</button>
          ) : (
            <Link to="/channels" className="mt-3 inline-block text-primary underline">选择频道</Link>
          )}
          {reading.scope === 'all' && !search.trim() && categories.length === 0 && sources.length === 0 && (
            <p className="mt-1 text-sm">{lang === 'en' ? 'Subscribe to a source to see articles after syncing.' : '订阅来源后，文章会在同步完成后显示。'}</p>
          )}
        </div>
      )}

      <NewsResults
        key={String(viewerId) + ':' + String(blockedNewsEnabled)}
        results={data?.results ?? []}
        viewerId={currentViewerId}
        lang={lang}
        fetching={newsQuery.isFetching}
      />

      {newsQuery.isFetching && !initialLoading && <div className="py-3 text-center text-sm text-muted-foreground" role="status">{lang === 'en' ? 'Updating…' : '正在更新…'}</div>}
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
  const blockedNewsEnabled = useCapability('blocked_news').enabled
  const unblockMutation = useUnblockNews()
  const blockVersionRef = useRef(0)
  const latestSuccessfulBlockVersionRef = useRef(0)
  const undoTargetRef = useRef<BlockedNewsTarget | null>(null)
  const undoButtonRef = useRef<HTMLButtonElement | null>(null)
  const [hiddenBlockedIds, setHiddenBlockedIds] = useState<Set<number>>(() => new Set())
  const [undoTarget, setUndoTarget] = useState<BlockedNewsTarget | null>(null)
  const [undoPendingVersion, setUndoPendingVersion] = useState<number | null>(null)
  const [undoErrorVersion, setUndoErrorVersion] = useState<number | null>(null)
  const visibleResults = blockedNewsEnabled ? results.filter((item) => !hiddenBlockedIds.has(item.id)) : results

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
    if (!blockedNewsEnabled || !target || target.viewerId !== viewerId) return
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

      {blockedNewsEnabled && undoTarget !== null && (
        <div className="fixed bottom-5 left-1/2 z-50 flex w-[min(92vw,28rem)] -translate-x-1/2 items-center gap-3 rounded-2xl bg-primary px-4 py-3 text-sm text-primary-foreground shadow-2xl" role="status" aria-live="polite">
          <span className="min-w-0 flex-1">{lang === 'en' ? 'News hidden from your feed.' : '已从资讯流中屏蔽这篇新闻。'}</span>
          <button ref={undoButtonRef} type="button" onClick={() => void undoBlock()} disabled={undoPendingVersion === undoTarget.version} className="min-h-11 shrink-0 rounded-lg px-3 py-1 font-semibold text-primary-foreground hover:bg-primary-foreground/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50 sm:min-h-8">
            {undoPendingVersion === undoTarget.version ? (lang === 'en' ? 'Restoring…' : '恢复中…') : (lang === 'en' ? 'Undo' : '撤销')}
          </button>
          <button type="button" aria-label={lang === 'en' ? 'Dismiss' : '关闭提示'} onClick={dismissUndo} className="flex size-11 shrink-0 items-center justify-center rounded-lg text-primary-foreground hover:bg-primary-foreground/10 hover:text-primary-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-foreground sm:size-8">×</button>
        </div>
      )}
      {blockedNewsEnabled && undoTarget && undoErrorVersion === undoTarget.version && <p role="alert" className="fixed bottom-20 left-1/2 z-50 -translate-x-1/2 rounded-lg bg-destructive/10 px-3 py-2 text-sm text-destructive shadow">{lang === 'en' ? 'Could not restore this news.' : '恢复失败，请重试。'}</p>}
    </>
  )
}
