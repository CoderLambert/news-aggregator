import { beforeEach, describe, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { Link, MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { AuthContext } from '@/context/AuthContext'
import { usePreferencesStore } from '@/stores/preferences'
import * as api from '@/services/api'
import LocalSearch from '@/pages/LocalSearch'
import NewsDetail from '@/pages/NewsDetail'
import FavoritesPage from '@/pages/FavoritesPage'

vi.mock('@/services/api', () => ({
  fetchNews: vi.fn(), fetchNewsDetail: vi.fn(), checkFavoriteStatus: vi.fn(), checkBlockedStatus: vi.fn(),
  toggleFavorite: vi.fn(), fetchUserFavorites: vi.fn(), fetchBlockedNews: vi.fn(), blockNews: vi.fn(), unblockNews: vi.fn(),
}))
vi.mock('@/hooks/useFullArticle', () => ({ useFullArticle: () => ({ articleLoading: false, articleError: '', handleFetchFullArticle: vi.fn(), cancelFetch: vi.fn() }) }))
vi.mock('@/hooks/useTranslation', () => ({ useTranslation: () => ({ translating: false, translateError: '', translationProgress: '', showOriginal: false, setShowOriginal: vi.fn(), handleTranslate: vi.fn() }) }))
vi.mock('@/hooks/useArticleSearch', () => ({ useArticleSearch: () => ({ matchCount: 0, currentIndex: 0, goNext: vi.fn(), goPrev: vi.fn() }) }))
vi.mock('@/hooks/useArticleToc', () => ({ useArticleToc: () => ({ headings: [], activeId: '' }) }))
vi.mock('@/context/SpeechPlayerContext', () => ({
  useSpeechPlayer: () => ({ supported: false, speak: vi.fn() }),
  useSpeechPlayerActions: () => ({ speak: vi.fn() }),
  useSpeechPlayerCapabilities: () => ({ supported: false }),
  useSpeechPlayerActivity: () => false,
}))
vi.mock('@/components/NewsChatAssistant', () => ({ default: () => null }))

const story = {
  id: 21, title: 'Climate technology update', content: 'A short article summary', title_zh: '', content_zh: '', author: null,
  publish_time: '2026-10-06T09:00:00Z', source: 8, source_name: 'Example source', source_type: 'news',
  source_language: 'en', category: 2, category_name: 'Technology', url: 'https://example.com/story', cover_image: null,
  created_at: '2026-10-06T09:00:00Z', related_to: null, translation_status: '', translation_error: '',
  translation_retry_count: 0, full_content_fetch_status: '', full_content_fetch_error: '', full_content_fetch_provider: '',
  full_content_quality_score: null, full_content_retry_count: 0, last_full_content_attempt: null,
  source_url: 'https://example.com/story', full_content: '', full_content_fetched_at: null,
  full_content_zh: '', full_content_zh_fetched_at: null, full_content_zh_source: null, full_translation_active: false,
}

const serverState = { favorites: new Set(), blocked: false }

function RouteTools() {
  const location = useLocation()
  return (
    <>
      <output data-testid="route">{`${location.pathname}${location.search}`}</output>
      <Link to="/favorites">打开收藏管理</Link>
    </>
  )
}

function renderFlow(initialEntry) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 30_000 }, mutations: { retry: false } } })
  return {
    client,
    ...render(
      <QueryClientProvider client={client}>
        <AuthContext.Provider value={{ user: { id: 12, username: 'reader' }, loading: false, login: vi.fn(), register: vi.fn(), logout: vi.fn(), refresh: vi.fn() }}>
          <MemoryRouter initialEntries={[initialEntry]}>
            <Routes>
              <Route path="/search" element={<LocalSearch />} />
              <Route path="/news/:id" element={<NewsDetail />} />
              <Route path="/favorites" element={<FavoritesPage />} />
            </Routes>
            <RouteTools />
          </MemoryRouter>
        </AuthContext.Provider>
      </QueryClientProvider>,
    ),
  }
}

function favoriteKey(newsId, type) { return `${newsId}:${type}` }

beforeEach(() => {
  vi.clearAllMocks()
  serverState.favorites = new Set()
  serverState.blocked = false
  usePreferencesStore.setState({ lang: 'zh' })
  api.fetchNews.mockResolvedValue({ count: 1, next: null, previous: null, results: [story] })
  api.fetchNewsDetail.mockResolvedValue(story)
  api.checkFavoriteStatus.mockImplementation(async () => ({
    is_liked: serverState.favorites.has(favoriteKey(21, 'like')),
    is_bookmarked: serverState.favorites.has(favoriteKey(21, 'bookmark')),
    like_count: Number(serverState.favorites.has(favoriteKey(21, 'like'))),
    bookmark_count: Number(serverState.favorites.has(favoriteKey(21, 'bookmark'))),
  }))
  api.checkBlockedStatus.mockImplementation(async () => ({ is_blocked: serverState.blocked }))
  api.toggleFavorite.mockImplementation(async (newsId, type) => {
    const key = favoriteKey(newsId, type)
    if (serverState.favorites.has(key)) {
      serverState.favorites.delete(key)
      return { removed: true }
    }
    serverState.favorites.add(key)
    return { created: true }
  })
  api.fetchUserFavorites.mockImplementation(async ({ type } = {}) => {
    const types = ['like', 'bookmark'].filter((favoriteType) => serverState.favorites.has(favoriteKey(21, favoriteType)))
    const results = types
      .filter((favoriteType) => !type || type === favoriteType)
      .map((favoriteType) => ({
        id: 2100 + (favoriteType === 'like' ? 1 : 2),
        news: {
          id: story.id, title: story.title, title_zh: '', content: story.content, content_zh: '',
          url: story.url, cover_image: '', source_name: story.source_name, category_name: story.category_name,
          publish_time: story.publish_time,
        },
        type: favoriteType,
        created_at: '2026-10-07T06:00:00Z',
      }))
    return { count: results.length, next: null, previous: null, results }
  })
  api.fetchBlockedNews.mockImplementation(async () => ({
    count: Number(serverState.blocked), next: null, previous: null,
    results: serverState.blocked ? [{
      id: 2201,
      news: { id: story.id, title: story.title, publish_time: story.publish_time },
      created_at: '2026-10-07T06:00:00Z',
    }] : [],
  }))
  api.blockNews.mockImplementation(async () => { serverState.blocked = true; return { created: true } })
  api.unblockNews.mockImplementation(async () => { serverState.blocked = false; return { removed: true } })
  vi.spyOn(window, 'scrollTo').mockImplementation(() => {})
})

describe('search, detail, and user-news flow', () => {
  it('keeps the search return URL and reconciles favorite and blocked lists after confirmed mutations', async () => {
    renderFlow('/search?q=climate&mode=keyword&page=2')

    expect(await screen.findByRole('heading', { name: story.title })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('link', { name: /Climate technology update/ }))
    expect(await screen.findByRole('button', { name: '点赞' })).toBeInTheDocument()
    expect(api.fetchNewsDetail).toHaveBeenCalledWith(21, expect.any(AbortSignal))

    fireEvent.click(screen.getByRole('button', { name: '点赞' }))
    expect(await screen.findByRole('button', { name: '取消点赞' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '收藏' }))
    expect(await screen.findByRole('button', { name: '取消收藏' })).toBeInTheDocument()
    expect(api.toggleFavorite).toHaveBeenCalledTimes(2)

    fireEvent.click(screen.getByRole('link', { name: '返回列表' }))
    await waitFor(() => expect(screen.getByTestId('route')).toHaveTextContent('/search?q=climate&mode=keyword&page=2'))
    expect(api.fetchNews).toHaveBeenCalledWith({
      page: 2, page_size: 20, search: 'climate', mode: 'keyword', order_by: 'relevance',
    }, expect.any(AbortSignal))

    fireEvent.click(screen.getByRole('link', { name: '打开收藏管理' }))
    expect(await screen.findAllByRole('link', { name: /Climate technology update/ })).toHaveLength(2)
    fireEvent.click(screen.getAllByRole('link', { name: /Climate technology update/ })[0])
    expect(await screen.findByRole('button', { name: '取消点赞' })).toBeInTheDocument()
    expect(await screen.findByRole('button', { name: '取消收藏' })).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '取消点赞' }))
    expect(await screen.findByRole('button', { name: '点赞' })).toBeInTheDocument()
    expect(serverState.favorites.has(favoriteKey(21, 'like'))).toBe(false)
    expect(serverState.favorites.has(favoriteKey(21, 'bookmark'))).toBe(true)

    fireEvent.click(screen.getByRole('link', { name: '打开收藏管理' }))
    expect(await screen.findAllByRole('link', { name: /Climate technology update/ })).toHaveLength(1)

    fireEvent.click(screen.getByRole('link', { name: /Climate technology update/ }))
    expect(await screen.findByRole('button', { name: '取消收藏' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '屏蔽此新闻' }))
    expect(await screen.findByRole('button', { name: '取消屏蔽' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('link', { name: '返回列表' }))

    fireEvent.click(await screen.findByRole('tab', { name: '已屏蔽' }))
    expect(await screen.findByRole('heading', { name: story.title })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '恢复' }))
    await waitFor(() => expect(screen.queryByRole('heading', { name: story.title })).not.toBeInTheDocument())
    expect(serverState.blocked).toBe(false)
    expect(serverState.favorites.has(favoriteKey(21, 'bookmark'))).toBe(true)
  })
})
