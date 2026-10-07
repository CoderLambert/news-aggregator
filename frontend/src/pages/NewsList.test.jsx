import { beforeEach, describe, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router-dom'
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

function renderList(url) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const user = { id: 12, username: 'reader' }
  return render(
    <QueryClientProvider client={client}>
      <AuthContext.Provider value={{ user, loading: false, login: vi.fn(), register: vi.fn(), logout: vi.fn(), refresh: vi.fn() }}>
        <MemoryRouter initialEntries={[url]}>
          <NewsList />
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

  it('changes pages through URL navigation', async () => {
    renderList('/')
    expect(await screen.findByRole('heading', { name: 'Climate technology update' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '2' }))
    await waitFor(() => expect(screen.getByTestId('location-search')).toHaveTextContent('page=2'))
    await waitFor(() => expect(fetchNews).toHaveBeenLastCalledWith({ page: 2, page_size: 20 }, expect.any(AbortSignal)))
  })
})
