import { useState } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom'
import { AuthContext } from '@/context/AuthContext'
import { usePreferencesStore } from '@/stores/preferences'
import NewsList from '@/pages/NewsList'
import { blockNews, fetchCategories, fetchNews, fetchNewsDetail, fetchSources, unblockNews } from '@/services/api'

vi.mock('@/services/api', () => ({
  fetchNews: vi.fn(),
  fetchCategories: vi.fn(),
  fetchSources: vi.fn(),
  fetchNewsDetail: vi.fn(),
  blockNews: vi.fn(),
  unblockNews: vi.fn(),
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

const secondStory = {
  ...story,
  id: 22,
  title: 'Second technology update',
  url: 'https://example.com/second-story',
}

function deferred() {
  let resolve
  let reject
  const promise = new Promise((accept, fail) => { resolve = accept; reject = fail })
  return { promise, resolve, reject }
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

function renderViewerList() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })

  function ViewerHarness() {
    const [user, setUser] = useState({ id: 12, username: 'reader-one' })
    return (
      <AuthContext.Provider value={{ user, loading: false, login: vi.fn(), register: vi.fn(), logout: vi.fn(), refresh: vi.fn() }}>
        <button type="button" onClick={() => setUser({ id: 13, username: 'reader-two' })}>Switch viewer</button>
        <output data-testid="viewer-id">{user.id}</output>
        <NewsList />
      </AuthContext.Provider>
    )
  }

  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter><ViewerHarness /></MemoryRouter>
    </QueryClientProvider>,
  )
}

function blockButtonFor(title) {
  const article = screen.getByRole('heading', { name: title }).closest('article')
  if (!article) throw new Error(`Missing article for ${title}`)
  return within(article).getByRole('button', { name: '屏蔽此新闻' })
}

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.removeItem('news-aggregator-filters')
  vi.spyOn(window, 'scrollTo').mockImplementation(() => {})
  usePreferencesStore.setState({ lang: 'zh' })
  fetchCategories.mockResolvedValue([{ id: 2, name: 'Technology' }, { id: 3, name: 'Science' }])
  fetchSources.mockResolvedValue([{ id: 8, name: 'Example source' }])
  fetchNews.mockResolvedValue({ count: 41, next: null, previous: null, results: [story] })
  fetchNewsDetail.mockResolvedValue({
    ...story,
    source_url: story.url,
    full_content: '',
    full_content_fetched_at: null,
    full_content_zh: '',
    full_content_zh_fetched_at: null,
    full_content_zh_source: null,
    full_translation_active: false,
  })
  blockNews.mockResolvedValue({ created: true })
  unblockNews.mockResolvedValue({ removed: true })
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

    fireEvent.click(screen.getByRole('button', { name: '筛选，已选 2 个条件' }))
    expect(screen.getByRole('group', { name: '分类' })).toBeInTheDocument()
    expect(screen.getByRole('group', { name: '来源' })).toBeInTheDocument()
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
    fireEvent.click(await screen.findByRole('button', { name: '筛选' }))
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

  it('labels summary content and prefetches article data on intent', async () => {
    renderList('/')
    expect(await screen.findByText('摘要')).toBeInTheDocument()

    const articleLink = screen.getByRole('link', { name: /Climate technology update/ })
    fireEvent.mouseEnter(articleLink)
    await waitFor(() => expect(fetchNewsDetail).toHaveBeenCalledWith(21, expect.any(AbortSignal)))
    fireEvent.focus(articleLink)
    expect(fetchNewsDetail).toHaveBeenCalledTimes(1)
  })

  it('shows active conditions compactly and clears them from the URL', async () => {
    renderList('/?search=climate&category=2&source=8')

    expect(await screen.findByText('已启用 3 个条件')).toBeInTheDocument()
    expect(await screen.findByRole('button', { name: '移除分类 Technology' })).toBeInTheDocument()
    expect(await screen.findByRole('button', { name: '移除来源 Example source' })).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '清除全部条件' }))
    await waitFor(() => expect(screen.getByTestId('location-search')).toHaveTextContent(''))
    await waitFor(() => expect(fetchNews).toHaveBeenLastCalledWith({ page: 1, page_size: 20 }, expect.any(AbortSignal)))
  })

  it('removes a blocked story immediately and lets the reader undo it', async () => {
    const pendingRefresh = deferred()
    fetchNews.mockResolvedValueOnce({ count: 1, next: null, previous: null, results: [story] }).mockReturnValueOnce(pendingRefresh.promise)
    renderList('/')
    expect(await screen.findByRole('heading', { name: 'Climate technology update' })).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '屏蔽此新闻' }))
    await waitFor(() => expect(blockNews).toHaveBeenCalledWith(21))
    await waitFor(() => expect(screen.queryByRole('heading', { name: 'Climate technology update' })).not.toBeInTheDocument())
    expect(screen.getByText('已从资讯流中屏蔽这篇新闻。')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('button', { name: '撤销' })).toHaveFocus())

    fireEvent.click(screen.getByRole('button', { name: '撤销' }))
    await waitFor(() => expect(unblockNews).toHaveBeenCalledWith(21))
    expect(await screen.findByRole('heading', { name: 'Climate technology update' })).toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('link', { name: /Climate technology update/ })).toHaveFocus())
    await act(async () => { pendingRefresh.resolve({ count: 1, next: null, previous: null, results: [story] }); await pendingRefresh.promise })
  })

  it('drops a late block completion when the signed-in viewer changes', async () => {
    const pendingBlock = deferred()
    fetchNews.mockResolvedValue({ count: 2, next: null, previous: null, results: [story, secondStory] })
    blockNews.mockReturnValueOnce(pendingBlock.promise)
    renderViewerList()
    expect(await screen.findByRole('heading', { name: story.title })).toBeInTheDocument()

    fireEvent.click(blockButtonFor(story.title))
    fireEvent.click(screen.getByRole('button', { name: 'Switch viewer' }))
    await waitFor(() => expect(screen.getByTestId('viewer-id')).toHaveTextContent('13'))

    await act(async () => { pendingBlock.resolve({ created: true }); await pendingBlock.promise })
    expect(await screen.findByRole('heading', { name: story.title })).toBeInTheDocument()
    expect(screen.queryByText('已从资讯流中屏蔽这篇新闻。')).not.toBeInTheDocument()
  })

  it('keeps the most recently started successful block as the undo target when responses finish out of order', async () => {
    const firstBlock = deferred()
    const secondBlock = deferred()
    fetchNews.mockResolvedValue({ count: 2, next: null, previous: null, results: [story, secondStory] })
    blockNews.mockReturnValueOnce(firstBlock.promise).mockReturnValueOnce(secondBlock.promise)
    renderList('/')
    expect(await screen.findByRole('heading', { name: secondStory.title })).toBeInTheDocument()

    fireEvent.click(blockButtonFor(story.title))
    fireEvent.click(blockButtonFor(secondStory.title))
    await act(async () => { secondBlock.resolve({ created: true }); await secondBlock.promise })
    await waitFor(() => expect(screen.queryByRole('heading', { name: secondStory.title })).not.toBeInTheDocument())
    await act(async () => { firstBlock.resolve({ created: true }); await firstBlock.promise })
    await waitFor(() => expect(screen.queryByRole('heading', { name: story.title })).not.toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: '撤销' }))
    await waitFor(() => expect(unblockNews).toHaveBeenCalledWith(secondStory.id))
  })

  it.each(['success', 'failure'])('does not let a late undo %s clear or contaminate a newer block', async (outcome) => {
    const firstUndo = deferred()
    fetchNews.mockResolvedValue({ count: 2, next: null, previous: null, results: [story, secondStory] })
    unblockNews.mockReturnValueOnce(firstUndo.promise).mockResolvedValueOnce({ removed: true })
    renderList('/')
    expect(await screen.findByRole('heading', { name: secondStory.title })).toBeInTheDocument()

    fireEvent.click(blockButtonFor(story.title))
    await waitFor(() => expect(screen.queryByRole('heading', { name: story.title })).not.toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: '撤销' }))

    fireEvent.click(blockButtonFor(secondStory.title))
    await waitFor(() => expect(screen.queryByRole('heading', { name: secondStory.title })).not.toBeInTheDocument())

    await act(async () => {
      if (outcome === 'success') firstUndo.resolve({ removed: true })
      else firstUndo.reject(new Error('late failure'))
      await firstUndo.promise.catch(() => undefined)
    })

    expect(screen.queryByText('恢复失败，请重试。')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '撤销' }))
    await waitFor(() => expect(unblockNews).toHaveBeenLastCalledWith(secondStory.id))
  })
})
