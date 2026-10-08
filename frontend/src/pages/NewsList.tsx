import { useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useLocation, useNavigationType, useSearchParams } from 'react-router-dom'
import { useAuth } from '@/context/AuthContext'
import { useLanguage } from '@/context/useLanguage'
import { categoryOptions, newsListOptions, newsListPlaceholderData, sourceOptions } from '@/services/newsQueries'
import type { NewsListParams, SearchMode } from '@/types/news'
import NewsCard from '@/components/NewsCard'
import SearchBar from '@/components/SearchBar'
import CategoryFilter from '@/components/CategoryFilter'
import SourceFilter from '@/components/SourceFilter'
import LoadingSpinner from '@/components/LoadingSpinner'
import { Pagination } from '@/components/Pagination'

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

  return (
    <div className="mx-auto max-w-6xl px-4 py-6">
      <div className="mb-4 max-w-lg">
        <SearchBar
          value={search}
          mode={mode}
          historyNavigationKey={historyNavigationKey}
          onChange={(value) => updateParams({ search: value.trim() || null, page: null }, true)}
          onModeChange={(value) => updateParams({ mode: value, page: null })}
        />
      </div>

      <section className="mb-3" aria-label={lang === 'en' ? 'Categories' : '分类筛选'}>
        <span className="mr-2 text-xs font-medium text-gray-500">{lang === 'en' ? 'Category' : '分类'}</span>
        <CategoryFilter
          categories={categoriesQuery.data ?? []}
          active={categories}
          onChange={(values) => updateFilter('category', values)}
        />
      </section>

      <section className="mb-6" aria-label={lang === 'en' ? 'Sources' : '来源筛选'}>
        <span className="mr-2 text-xs font-medium text-gray-500">{lang === 'en' ? 'Source' : '来源'}</span>
        <SourceFilter
          sources={sourcesQuery.data ?? []}
          active={sources}
          onChange={(values) => updateFilter('source', values)}
        />
      </section>

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

      <div className="grid grid-cols-1 gap-5 md:grid-cols-2 lg:grid-cols-3" aria-busy={newsQuery.isFetching}>
        {data?.results.map((item) => <NewsCard key={item.id} news={item} />)}
      </div>

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
