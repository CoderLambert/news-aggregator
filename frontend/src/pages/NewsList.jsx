import { useState, useEffect, useCallback, useRef } from 'react'
import { fetchNews, fetchCategories, fetchSources } from '../services/api'
import { useLanguage } from '../context/useLanguage'
import NewsCard from '../components/NewsCard'
import SearchBar from '../components/SearchBar'
import CategoryFilter from '../components/CategoryFilter'
import SourceFilter from '../components/SourceFilter'
import LoadingSpinner from '../components/LoadingSpinner'
import { Pagination } from '../components/Pagination'

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
  const [totalCount, setTotalCount] = useState(0)
  const [search, setSearch] = useState(saved.search || '')
  const [searchMode, setSearchMode] = useState(saved.searchMode || 'hybrid')
  const [category, setCategory] = useState(saved.categories || [])
  const [source, setSource] = useState(saved.sources || [])

  const PAGE_SIZE = 20

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

  // Unified loader — resets list on filter change, replaces on page change.
  const loadNews = useCallback((pageNum) => {
    setLoading(true)
    return (async () => {
      try {
        const params = { page: pageNum, page_size: PAGE_SIZE }
        if (search) {
          params.search = search
          params.mode = searchMode
        }
        if (category.length > 0) params.category = category.join(',')
        if (source.length > 0) params.source = source.join(',')
        const data = await fetchNews(params)
        const results = data.results || data
        setNews(results)
        setTotalCount(data.count || 0)
        setPage(pageNum)
      } catch (err) {
        console.error('Failed to load news:', err)
      } finally {
        setLoading(false)
      }
    })()
  }, [search, searchMode, category, source])

  // Filters or language changed → reload from page 1
  useEffect(() => {
    loadNews(1)
  }, [search, searchMode, category, source, lang, loadNews])

  function handlePageChange(newPage) {
    if (newPage < 1 || newPage > Math.ceil(totalCount / PAGE_SIZE)) return
    loadNews(newPage)
    // Scroll to top so user sees the new page
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  const totalPages = Math.ceil(totalCount / PAGE_SIZE)

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
        {news.map((item) => (
          <div key={item.id}>
            <NewsCard news={item} onRemoved={() => loadNews(page)} />
          </div>
        ))}
      </div>

      {loading && <LoadingSpinner />}

      {/* Pagination */}
      {!loading && totalPages > 1 && (
        <Pagination
          currentPage={page}
          totalPages={totalPages}
          totalCount={totalCount}
          onPageChange={handlePageChange}
          lang={lang}
        />
      )}

      {!loading && news.length > 0 && (
        <p className="text-center text-sm text-gray-400 py-4">
          {lang === 'en' ? `Showing page ${page} of ${totalPages}` : `共 ${totalCount} 条，第 ${page}/${totalPages} 页`}
        </p>
      )}
    </div>
  )
}
