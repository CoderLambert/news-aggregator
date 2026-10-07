import { beforeEach, describe, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom'
import { AuthContext } from '@/context/AuthContext'
import { usePreferencesStore } from '@/stores/preferences'
import NewsList from './NewsList'
import { fetchCategories, fetchNews, fetchSources } from '@/services/api'

vi.mock('@/services/api', () => ({
  fetchNews: vi.fn(),
  fetchCategories: vi.fn(),
  fetchSources: vi.fn(),
}))

const story = {
  id: 21,
  title: 'Climate technology update',
  content: 'A short article summary',
  title_zh: '',
  content_zh: '',
  author: null,
  publish_time: '2026-10-06T09:00:00Z',
  source: 8,
  source_name: 'Example source',
  source_type: 'news',
  source_language: 'en',
  category: 2,
  category_name: 'Technology',
  url: 'https://example.com/story',
  cover_image: null,
  created_at: '2026-10-06T09:00:00Z',
  related_to: null,
  translation_status: '',
  translation_error: '',
  translation_retry_count: 0,
  full_content_fetch_status: '',
  full_content_fetch_error: '',
  full_content_fetch_provider: '',
  full_content_quality_score: null,
  full_content_retry_count: 0,
  last_full_content_attempt: null,
}

function LocationProbe() {
  const location = useLocation()
  return <output data-testid="location-search">{location.search}</output>
}

function HistoryControls() {
  const navigate = useNavigate()
  return (
    <div>
      <button type="button" onClick={() => navigate(-1)}>Browser back</button>
      <button type="button" onClick={() => navigate(1)}>Browser forward</button>
    </div>
  )
}

function renderList(url, { historyControls = false } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const user = { id: 12, username: 'reader' }
  const initialEntries = Array.isArray(url) ? url : [url]
  return render(
    <QueryClientProvider client={client}>
      <AuthContext.Provider value={{ user, loading: false, login: vi.fn(), register: vi.fn(), logout: vi.fn(), refresh: vi.fn() }}>
        <MemoryRouter initialEntries={initialEntries} initialIndex={initialEntries.length - 1}>
          <NewsList />
          {historyControls && <HistoryControls />}
          <LocationProbe />
        </MemoryRouter>
      </AuthContext.Provider>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.removeItem('news-aggregator-filters')
  vi.spyOn(window, 'scrollTo').mockImplementation(() => {})
  usePreferencesStore.setState({ lang: 'zh' })
  fetchCategories.mockResolvedValue([{ id: 2, name: 'Technology' }, { id: 3, name: 'Science' }])
  fetchSources.mockResolvedValue([{ id: 8, name: 'Example source' }])
  fetchNews.mockResolvedValue({ count: 41, next: null, previous: null, results: [story] })
})

describe('NewsList URL and server state', () => {
  it('fetches the URL-selected page and filters, then updates URL and query when a category changes', async () => {
    renderList('/?search=climate&mode=keyword&category=2&source=8&page=2')

    expect(await screen.findByRole('heading', { name: 'Climate technology update' })).toBeInTheDocument()
    await waitFor(() => expect(fetchNews).toHaveBeenCalledWith({
      page: 2,
      page_size: 20,
      search: 'climate',
      mode: 'keyword',
      category: '2',
      source: '8',
    }, expect.any(AbortSignal)))

    fireEvent.click(screen.getByRole('button', { name: 'Science' }))
    await waitFor(() => expect(fetchNews).toHaveBeenLastCalledWith({
      page: 1,
      page_size: 20,
      search: 'climate',
      mode: 'keyword',
      category: '2,3',
      source: '8',
    }, expect.any(AbortSignal)))
    expect(screen.getByTestId('location-search')).toHaveTextContent('search=climate')
    expect(screen.getByTestId('location-search')).toHaveTextContent('category=2%2C3')
    expect(screen.getByTestId('location-search')).not.toHaveTextContent('page=2')
  })

  it('moves previously saved filters into the URL once when no URL filter is present', async () => {
    localStorage.setItem('news-aggregator-filters', JSON.stringify({ search: 'legacy query', searchMode: 'semantic', categories: [3], sources: [8] }))
    renderList('/')
    await waitFor(() => expect(fetchNews).toHaveBeenLastCalledWith({
      page: 1,
      page_size: 20,
      search: 'legacy query',
      mode: 'semantic',
      category: '3',
      source: '8',
    }, expect.any(AbortSignal)))
    expect(screen.getByTestId('location-search')).toHaveTextContent('search=legacy+query')
    expect(localStorage.getItem('news-aggregator-filters')).toBeNull()
  })

  it('keeps the latest category, source, and mode when the search debounce commits', async () => {
    renderList('/')
    await screen.findByRole('button', { name: 'Science' })
    await screen.findByRole('button', { name: 'Example source' })

    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'climate' } })
    fireEvent.click(screen.getByRole('button', { name: 'Science' }))
    fireEvent.click(screen.getByRole('button', { name: 'Example source' }))
    fireEvent.click(screen.getByRole('radio', { name: '语义' }))

    await waitFor(() => {
      expect(screen.getByTestId('location-search')).toHaveTextContent('search=climate')
      expect(screen.getByTestId('location-search')).toHaveTextContent('mode=semantic')
      expect(screen.getByTestId('location-search')).toHaveTextContent('category=3')
      expect(screen.getByTestId('location-search')).toHaveTextContent('source=8')
      expect(fetchNews).toHaveBeenLastCalledWith({
        page: 1,
        page_size: 20,
        search: 'climate',
        mode: 'semantic',
        category: '3',
        source: '8',
      }, expect.any(AbortSignal))
    })
  })

  it('cancels a pending search when browser back or forward replaces the URL value', async () => {
    renderList(['/?search=before', '/?search=after'], { historyControls: true })
    await waitFor(() => expect(fetchNews).toHaveBeenCalledWith(
      { page: 1, page_size: 20, search: 'after', mode: 'hybrid' },
      expect.any(AbortSignal),
    ))

    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'discard-after-back' } })
    fireEvent.click(screen.getByRole('button', { name: 'Browser back' }))
    await waitFor(() => expect(screen.getByRole('searchbox')).toHaveValue('before'))
    await new Promise((resolve) => setTimeout(resolve, 350))
    expect(fetchNews.mock.calls.some(([params]) => params.search === 'discard-after-back')).toBe(false)
    await waitFor(() => expect(fetchNews.mock.calls.some(([params]) => params.search === 'before')).toBe(true))

    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'discard-after-forward' } })
    fireEvent.click(screen.getByRole('button', { name: 'Browser forward' }))
    await waitFor(() => expect(screen.getByRole('searchbox')).toHaveValue('after'))
    await new Promise((resolve) => setTimeout(resolve, 350))
    expect(screen.getByTestId('location-search')).toHaveTextContent('search=after')
    expect(fetchNews.mock.calls.some(([params]) => params.search === 'discard-after-forward')).toBe(false)
  })

  it('cancels a pending search on back and forward when the search is unchanged', async () => {
    renderList([
      '/?search=shared&mode=keyword&category=2&page=1',
      '/?search=shared&mode=keyword&category=3&page=2',
    ], { historyControls: true })
    await waitFor(() => expect(fetchNews).toHaveBeenCalledWith({
      page: 2,
      page_size: 20,
      search: 'shared',
      mode: 'keyword',
      category: '3',
    }, expect.any(AbortSignal)))

    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'discard-on-back' } })
    fireEvent.click(screen.getByRole('button', { name: 'Browser back' }))
    await waitFor(() => {
      expect(screen.getByTestId('location-search')).toHaveTextContent('category=2')
      expect(screen.getByTestId('location-search')).toHaveTextContent('page=1')
      expect(screen.getByRole('searchbox')).toHaveValue('shared')
    })
    await new Promise((resolve) => setTimeout(resolve, 350))
    expect(screen.getByTestId('location-search')).toHaveTextContent('search=shared')
    expect(fetchNews.mock.calls.some(([params]) => params.search === 'discard-on-back')).toBe(false)

    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'discard-on-forward' } })
    fireEvent.click(screen.getByRole('button', { name: 'Browser forward' }))
    await waitFor(() => {
      expect(screen.getByTestId('location-search')).toHaveTextContent('category=3')
      expect(screen.getByTestId('location-search')).toHaveTextContent('page=2')
      expect(screen.getByRole('searchbox')).toHaveValue('shared')
    })
    await new Promise((resolve) => setTimeout(resolve, 350))
    expect(screen.getByTestId('location-search')).toHaveTextContent('search=shared')
    expect(fetchNews.mock.calls.some(([params]) => params.search === 'discard-on-forward')).toBe(false)
  })

  it('changes pages through URL navigation', async () => {
    renderList('/')
    expect(await screen.findByRole('heading', { name: 'Climate technology update' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '2' }))
    await waitFor(() => expect(screen.getByTestId('location-search')).toHaveTextContent('page=2'))
    await waitFor(() => expect(fetchNews).toHaveBeenLastCalledWith({ page: 2, page_size: 20 }, expect.any(AbortSignal)))
  })
})
