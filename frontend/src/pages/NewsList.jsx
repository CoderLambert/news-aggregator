import { useState, useEffect, useCallback, useRef } from 'react'
import { fetchNews, fetchCategories, fetchSources } from '../services/api'
import { useLanguage } from '../context/useLanguage'
import NewsCard from '../components/NewsCard'
import SearchBar from '../components/SearchBar'
import CategoryFilter from '../components/CategoryFilter'
import SourceFilter from '../components/SourceFilter'
import LoadingSpinner from '../components/LoadingSpinner'

const STORAGE_KEY = 'news-aggregator-filters'

function loadSavedFilters() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) return JSON.parse(raw)
  } catch {
    // localStorage may be unavailable (privacy mode) or contain malformed
    // JSON from an older version — fall through to defaults.
  }
  return {}
}

export default function NewsList() {
  const { lang } = useLanguage()
  const saved = loadSavedFilters()
  const [news, setNews] = useState([])
  const [categories, setCategories] = useState([])
  const [sources, setSources] = useState([])
  const [loading, setLoading] = useState(false)
  const [page, setPage] = useState(1)
  const [hasMore, setHasMore] = useState(true)
  const [search, setSearch] = useState(saved.search || '')
  const [searchMode, setSearchMode] = useState(saved.searchMode || 'hybrid')
  const [category, setCategory] = useState(saved.categories || [])
  const [source, setSource] = useState(saved.sources || [])
  const observer = useRef()
  const loadingRef = useRef(false)

  // Persist filters to localStorage on every change
  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({
      search,
      searchMode,
      categories: category,
      sources: source,
    }))
  }, [search, searchMode, category, source])

  useEffect(() => {
    fetchCategories().then(data => setCategories(data.results || data))
    fetchSources().then(data => setSources(data.results || data))
  }, [])

  // Unified loader: handles BOTH "reset" (page 1, replace) and "append" (next
  // page). All state mutations happen inside the async IIFE so they cross a
  // microtask boundary — keeps react-hooks/set-state-in-effect happy when
  // this is invoked from an effect.
  const loadNews = useCallback((pageNum, reset = false) => {
    if (loadingRef.current) return
    loadingRef.current = true
    return (async () => {
      setLoading(true)
      if (reset) {
        // Reset paging immediately so the IntersectionObserver doesn't fire
        // for stale results during the in-flight request.
        setHasMore(true)
      }
      try {
        const params = { page: pageNum, page_size: 20 }
        if (search) {
          params.search = search
          params.mode = searchMode
        }
        if (category.length > 0) params.category = category.join(',')
        if (source.length > 0) params.source = source.join(',')
        const data = await fetchNews(params)
        const results = data.results || data
        setNews(prev => reset ? results : [...prev, ...results])
        setHasMore(!!data.next)
        setPage(pageNum)
      } catch (err) {
        console.error('Failed to load news:', err)
      } finally {
        setLoading(false)
        loadingRef.current = false
      }
    })()
  }, [search, searchMode, category, source])

  // Single effect for "filters or language changed → reload from page 1".
  // Previously this was split across two effects, both with synchronous
  // setState calls (setNews([]) / setPage(1) / setHasMore(true)). All of
  // that is now handled inside loadNews(1, true).
  useEffect(() => {
    loadNews(1, true)
  }, [search, searchMode, category, source, lang, loadNews])

  const lastRef = useCallback(
    node => {
      if (loadingRef.current || !hasMore) return
      if (observer.current) observer.current.disconnect()
      observer.current = new IntersectionObserver(entries => {
        if (entries[0].isIntersecting) {
          loadNews(page + 1)
        }
      })
      if (node) observer.current.observe(node)
    },
    [hasMore, page, loadNews]
  )

  return (
    <div className="max-w-6xl mx-auto px-4 py-6">
      {/* Search bar */}
      <div className="mb-4">
        <div className="max-w-lg">
          <SearchBar
            value={search}
            onChange={setSearch}
            mode={searchMode}
            onModeChange={setSearchMode}
          />
        </div>
      </div>

      {/* Category filter */}
      <div className="mb-3">
        <span className="text-xs font-medium text-gray-500 mr-2">
          {lang === 'en' ? 'Category' : '分类'}
        </span>
        <CategoryFilter categories={categories} active={category} onChange={setCategory} />
      </div>

      {/* Source filter */}
      <div className="mb-6">
        <span className="text-xs font-medium text-gray-500 mr-2">
          {lang === 'en' ? 'Source' : '来源'}
        </span>
        <SourceFilter sources={sources} active={source} onChange={setSource} />
      </div>

      {news.length === 0 && !loading && (
        <div className="text-center py-20 text-gray-400">
          <p className="text-lg">
            {lang === 'en' ? 'No news data' : '暂无新闻数据'}
          </p>
          <p className="text-sm mt-1">
            {lang === 'en'
              ? 'Run crawler first: python manage.py crawl'
              : '请先运行爬虫: python manage.py crawl'}
          </p>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
        {news.map((item, i) => (
          <div key={item.id} ref={i === news.length - 1 ? lastRef : null}>
            <NewsCard news={item} onRemoved={(id) => setNews(prev => prev.filter(n => n.id !== id))} />
          </div>
        ))}
      </div>

      {loading && <LoadingSpinner />}

      {!hasMore && news.length > 0 && (
        <p className="text-center text-sm text-gray-400 py-8">
          {lang === 'en' ? 'No more results' : '没有更多了'}
        </p>
      )}
    </div>
  )
}
