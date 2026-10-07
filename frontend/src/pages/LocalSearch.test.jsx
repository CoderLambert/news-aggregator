import { beforeEach, describe, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom'
import { AuthContext } from '@/context/AuthContext'
import { usePreferencesStore } from '@/stores/preferences'
import { fetchNews } from '@/services/api'
import LocalSearch from './LocalSearch'

vi.mock('@/services/api', () => ({ fetchNews: vi.fn() }))

const article = {
  id: 21, title: 'Climate technology update', content: 'A short article summary', title_zh: '', content_zh: '', author: null,
  publish_time: '2026-10-06T09:00:00Z', source: 8, source_name: 'Example source', source_type: 'news',
  source_language: 'en', category: 2, category_name: 'Technology', url: 'https://example.com/story', cover_image: null,
  created_at: '2026-10-06T09:00:00Z', related_to: null, translation_status: '', translation_error: '',
  translation_retry_count: 0, full_content_fetch_status: 'success', full_content_fetch_error: '', full_content_fetch_provider: '',
  full_content_quality_score: null, full_content_retry_count: 0, last_full_content_attempt: null,
}

function RouteProbe() {
  const location = useLocation()
  const navigate = useNavigate()
  return (
    <>
      <output data-testid="route">{`${location.pathname}${location.search}`}</output>
      <button type="button" onClick={() => navigate(-1)}>history back</button>
      <button type="button" onClick={() => navigate(1)}>history forward</button>
    </>
  )
}

function renderSearch(initialEntries, initialIndex) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 30_000 } } })
  const user = { id: 12, username: 'reader' }
  return render(
    <QueryClientProvider client={client}>
      <AuthContext.Provider value={{ user, loading: false, login: vi.fn(), register: vi.fn(), logout: vi.fn(), refresh: vi.fn() }}>
        <MemoryRouter initialEntries={initialEntries} initialIndex={initialIndex}>
          <LocalSearch />
          <RouteProbe />
        </MemoryRouter>
      </AuthContext.Provider>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  usePreferencesStore.setState({ lang: 'zh' })
  fetchNews.mockResolvedValue({ count: 61, next: null, previous: null, results: [article] })
})

describe('LocalSearch Query and URL state', () => {
  it('loads the advanced search parameters from the URL and forwards cancellation', async () => {
    renderSearch(['/search?q=climate&mode=keyword&page=2&order_by=time&full_content=true&days=7&source_types=discussion'])

    expect(await screen.findByRole('heading', { name: 'Climate technology update' })).toBeInTheDocument()
    expect(fetchNews).toHaveBeenCalledWith({
      search: 'climate',
      mode: 'keyword',
      page: 2,
      page_size: 20,
      order_by: 'time',
      full_content: 'true',
      publish_time_after: expect.any(String),
      source__source_type: 'discussion',
    }, expect.any(AbortSignal))
    expect(screen.getByText(/找到/)).toHaveTextContent('找到 61 篇相关文章')
  })

  it('submits a new search and applies sort, paging, and browser history from the URL', async () => {
    renderSearch(['/search'])
    expect(fetchNews).not.toHaveBeenCalled()
    fireEvent.change(screen.getByRole('searchbox', { name: '搜索本地新闻文章' }), { target: { value: 'AI chips' } })
    fireEvent.click(screen.getByRole('button', { name: '搜索' }))

    expect(await screen.findByRole('heading', { name: 'Climate technology update' })).toBeInTheDocument()
    await waitFor(() => expect(screen.getByTestId('route')).toHaveTextContent('/search?q=AI+chips&mode=semantic&page=1&order_by=relevance'))
    expect(fetchNews).toHaveBeenCalledWith({
      search: 'AI chips', mode: 'semantic', page: 1, page_size: 20, order_by: 'relevance',
    }, expect.any(AbortSignal))

    fireEvent.click(screen.getByRole('button', { name: '最新发布' }))
    await waitFor(() => {
      expect(screen.getByTestId('route')).toHaveTextContent('order_by=time')
      expect(screen.getByTestId('route')).toHaveTextContent('page=1')
    })
    await waitFor(() => expect(fetchNews).toHaveBeenLastCalledWith({
      search: 'AI chips', mode: 'semantic', page: 1, page_size: 20, order_by: 'time',
    }, expect.any(AbortSignal)))

    fireEvent.click(screen.getByRole('button', { name: '下一页' }))
    await waitFor(() => expect(screen.getByTestId('route')).toHaveTextContent('page=2'))
    await waitFor(() => expect(fetchNews).toHaveBeenLastCalledWith({
      search: 'AI chips', mode: 'semantic', page: 2, page_size: 20, order_by: 'time',
    }, expect.any(AbortSignal)))

    fireEvent.click(screen.getByRole('button', { name: 'history back' }))
    await waitFor(() => expect(screen.getByTestId('route')).toHaveTextContent('page=1'))
    fireEvent.click(screen.getByRole('button', { name: 'history forward' }))
    await waitFor(() => expect(screen.getByTestId('route')).toHaveTextContent('page=2'))
  })

  it('shows a retry state on read failure and keeps the empty state for a confirmed empty response', async () => {
    fetchNews.mockRejectedValueOnce(new Error('network unavailable'))
    renderSearch(['/search?q=climate'])

    expect(await screen.findByRole('alert')).toHaveTextContent('搜索失败')
    expect(screen.queryByText('未找到相关文章')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '重试' }))
    expect(await screen.findByRole('heading', { name: 'Climate technology update' })).toBeInTheDocument()

    fetchNews.mockResolvedValueOnce({ count: 0, results: [] })
    fireEvent.click(screen.getByRole('button', { name: '关键词' }))
    expect(await screen.findByText('未找到相关文章')).toBeInTheDocument()
  })
})
