import { useState, useEffect, useCallback, useRef } from 'react'
import { fetchNews, fetchCategories, fetchSources } from '../services/api'
import NewsCard from '../components/NewsCard'
import SearchBar from '../components/SearchBar'
import CategoryFilter from '../components/CategoryFilter'
import SourceFilter from '../components/SourceFilter'
import LoadingSpinner from '../components/LoadingSpinner'

export default function NewsList() {
  const [news, setNews] = useState([])
  const [categories, setCategories] = useState([])
  const [sources, setSources] = useState([])
  const [loading, setLoading] = useState(false)
  const [page, setPage] = useState(1)
  const [hasMore, setHasMore] = useState(true)
  const [search, setSearch] = useState('')
  const [searchMode, setSearchMode] = useState('hybrid')
  const [category, setCategory] = useState(null)
  const [source, setSource] = useState(null)
  const observer = useRef()

  useEffect(() => {
    fetchCategories().then(data => setCategories(data.results || data))
    fetchSources().then(data => setSources(data.results || data))
  }, [])

  const loadNews = useCallback(async (pageNum, reset = false) => {
    if (loading) return
    setLoading(true)
    try {
      const params = { page: pageNum, page_size: 20 }
      if (search) {
        params.search = search
        params.mode = searchMode
      }
      if (category) params.category = category
      if (source) params.source = source
      const data = await fetchNews(params)
      const results = data.results || data
      setNews(prev => reset ? results : [...prev, ...results])
      setHasMore(!!data.next)
      setPage(pageNum)
    } catch (err) {
      console.error('Failed to load news:', err)
    } finally {
      setLoading(false)
    }
  }, [search, searchMode, category, source, loading])

  useEffect(() => {
    setNews([])
    setPage(1)
    setHasMore(true)
    loadNews(1, true)
  }, [search, searchMode, category, source])

  const lastRef = useCallback(
    node => {
      if (loading || !hasMore) return
      if (observer.current) observer.current.disconnect()
      observer.current = new IntersectionObserver(entries => {
        if (entries[0].isIntersecting) {
          loadNews(page + 1)
        }
      })
      if (node) observer.current.observe(node)
    },
    [loading, hasMore, page, loadNews]
  )

  return (
    <div className="max-w-6xl mx-auto px-4 py-6">
      {/* 搜索栏 */}
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

      {/* 分类筛选 */}
      <div className="mb-3">
        <span className="text-xs font-medium text-gray-500 mr-2">分类</span>
        <CategoryFilter categories={categories} active={category} onChange={setCategory} />
      </div>

      {/* 来源筛选 */}
      <div className="mb-6">
        <span className="text-xs font-medium text-gray-500 mr-2">来源</span>
        <SourceFilter sources={sources} active={source} onChange={setSource} />
      </div>

      {news.length === 0 && !loading && (
        <div className="text-center py-20 text-gray-400">
          <p className="text-lg">暂无新闻数据</p>
          <p className="text-sm mt-1">请先运行爬虫: python manage.py crawl</p>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
        {news.map((item, i) => (
          <div key={item.id} ref={i === news.length - 1 ? lastRef : null}>
            <NewsCard news={item} />
          </div>
        ))}
      </div>

      {loading && <LoadingSpinner />}

      {!hasMore && news.length > 0 && (
        <p className="text-center text-sm text-gray-400 py-8">没有更多了</p>
      )}
    </div>
  )
}
