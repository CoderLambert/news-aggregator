import '@testing-library/jest-dom/vitest'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import App from '@/App'
import * as api from '@/services/api'
import { queryClient } from '@/services/queryClient'

const mocks = vi.hoisted(() => ({
  fetchCapabilities: vi.fn(),
  fetchNews: vi.fn(),
  fetchNewsDetail: vi.fn(),
  fetchCategories: vi.fn(),
  fetchSources: vi.fn(),
  fetchMe: vi.fn(),
  fetchProviderComparisons: vi.fn(),
  checkFavoriteStatus: vi.fn(),
  checkBlockedStatus: vi.fn(),
  fetchUserFavorites: vi.fn(),
  fetchChatGPTSubscriptionStatus: vi.fn(),
  fetchFullArticle: vi.fn(),
  fetchFullArticleStatus: vi.fn(),
  translateFullArticleStream: vi.fn(),
}))

vi.mock('@/services/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/services/api')>()),
  fetchCapabilities: mocks.fetchCapabilities,
  fetchNews: mocks.fetchNews,
  fetchNewsDetail: mocks.fetchNewsDetail,
  fetchCategories: mocks.fetchCategories,
  fetchSources: mocks.fetchSources,
  fetchMe: mocks.fetchMe,
  fetchProviderComparisons: mocks.fetchProviderComparisons,
  checkFavoriteStatus: mocks.checkFavoriteStatus,
  checkBlockedStatus: mocks.checkBlockedStatus,
  fetchUserFavorites: mocks.fetchUserFavorites,
  fetchChatGPTSubscriptionStatus: mocks.fetchChatGPTSubscriptionStatus,
}))

vi.mock('@/services/newsWorkflowApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/services/newsWorkflowApi')>()),
  fetchFullArticle: mocks.fetchFullArticle,
  fetchFullArticleStatus: mocks.fetchFullArticleStatus,
  translateFullArticleStream: mocks.translateFullArticleStream,
}))

const features = Object.fromEntries(api.CAPABILITY_FEATURE_NAMES.map((name) => [
  name,
  name === 'news' || name === 'keyword_search'
    ? { enabled: true, reason: null }
    : { enabled: false, reason: 'public_read_only' },
]))
const readOnly = { site_mode: 'read_only', chatgpt_auth_mode: 'disabled', features }

const story = {
  id: 41,
  title: 'Read-only climate story',
  content: 'Summary content for public reading',
  title_zh: '只读新闻',
  content_zh: '公开摘要',
  author: null,
  publish_time: '2026-10-08T09:00:00Z',
  source: 8,
  source_name: 'Public source',
  source_type: 'news',
  source_language: 'en',
  category: 2,
  category_name: 'Technology',
  url: 'https://example.test/story',
  cover_image: null,
  created_at: '2026-10-08T09:00:00Z',
  related_to: null,
  translation_status: '',
  translation_error: '',
  translation_retry_count: 0,
  full_content_fetch_status: 'fetching',
  full_content_fetch_error: '',
  full_content_fetch_provider: '',
  full_content_quality_score: null,
  full_content_retry_count: 0,
  last_full_content_attempt: null,
  source_url: 'https://example.test/story',
  full_content: 'Cached original body remains readable.',
  full_content_fetched_at: null,
  full_content_zh: 'Cached translated body remains readable.',
  full_content_zh_fetched_at: null,
  full_content_zh_source: null,
  full_translation_active: true,
}

function renderAt(path: string) {
  window.history.replaceState({}, '', path)
  queryClient.clear()
  return render(<App />)
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.stubGlobal('IntersectionObserver', class {
    observe() {}
    unobserve() {}
    disconnect() {}
    takeRecords() { return [] }
  })
  queryClient.clear()
  mocks.fetchCapabilities.mockResolvedValue(readOnly)
  mocks.fetchNews.mockResolvedValue({ count: 1, next: null, previous: null, results: [story] })
  mocks.fetchNewsDetail.mockResolvedValue(story)
  mocks.fetchCategories.mockResolvedValue([])
  mocks.fetchSources.mockResolvedValue([])
  mocks.fetchMe.mockResolvedValue({ id: 1, username: 'unexpected-user' })
})

afterEach(() => {
  vi.unstubAllGlobals()
  queryClient.clear()
  vi.restoreAllMocks()
})

describe('read-only application capabilities', () => {
  it('keeps the anonymous homepage and keyword search available without requesting a session', async () => {
    renderAt('/?search=climate&mode=semantic')

    expect(await screen.findByRole('heading', { name: '只读新闻' })).toBeInTheDocument()
    await waitFor(() => expect(mocks.fetchNews).toHaveBeenCalled())
    expect(mocks.fetchNews.mock.calls[0][0]).toMatchObject({ search: 'climate', mode: 'keyword' })
    expect(mocks.fetchMe).not.toHaveBeenCalled()
    expect(screen.getByText('当前仅支持关键词搜索。')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '登录' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: '智库收藏' })).not.toBeInTheDocument()
  })

  it('shows a feature reason on a private deep link without mounting its page', async () => {
    renderAt('/favorites')

    expect(await screen.findByRole('heading', { name: '暂不可用' })).toBeInTheDocument()
    expect(await screen.findByText('本站当前仅提供新闻阅读')).toBeInTheDocument()
    expect(mocks.fetchUserFavorites).not.toHaveBeenCalled()
    expect(mocks.fetchMe).not.toHaveBeenCalled()
  })

  it.each(['/provider-comparisons', '/settings/chatgpt', '/admin/crawlers'])(
    'keeps disabled route %s behind its capability without private API calls',
    async (path) => {
      renderAt(path)

      expect(await screen.findByRole('heading', { name: '暂不可用' })).toBeInTheDocument()
      expect(await screen.findByText('本站当前仅提供新闻阅读')).toBeInTheDocument()
      expect(mocks.fetchProviderComparisons).not.toHaveBeenCalled()
      expect(mocks.fetchChatGPTSubscriptionStatus).not.toHaveBeenCalled()
      expect(mocks.fetchMe).not.toHaveBeenCalled()
    },
  )

  it('fails closed on a private deep link while capabilities are still loading', async () => {
    mocks.fetchCapabilities.mockReturnValue(new Promise(() => {}))
    renderAt('/favorites')

    expect(await screen.findByText('功能状态暂不可用，请稍后重试')).toBeInTheDocument()
    expect(mocks.fetchUserFavorites).not.toHaveBeenCalled()
    expect(mocks.fetchMe).not.toHaveBeenCalled()
  })

  it('keeps cached article content readable and starts no disabled private or AI request', async () => {
    renderAt('/news/41')

    expect(await screen.findByText('Cached translated body remains readable.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '复制全文' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '重新获取原文' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '翻译为中文' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '询问 AI 助手小闻' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '选择语音播报方式' })).not.toBeInTheDocument()

    await waitFor(() => expect(mocks.fetchNewsDetail).toHaveBeenCalledOnce())
    expect(mocks.fetchMe).not.toHaveBeenCalled()
    expect(mocks.checkFavoriteStatus).not.toHaveBeenCalled()
    expect(mocks.checkBlockedStatus).not.toHaveBeenCalled()
    expect(mocks.fetchFullArticle).not.toHaveBeenCalled()
    expect(mocks.fetchFullArticleStatus).not.toHaveBeenCalled()
    expect(mocks.translateFullArticleStream).not.toHaveBeenCalled()
  })

  it('normalizes advanced-search deep links to keyword mode', async () => {
    renderAt('/search?q=climate&mode=hybrid')

    await waitFor(() => expect(mocks.fetchNews).toHaveBeenCalled())
    expect(mocks.fetchNews.mock.calls[0][0]).toMatchObject({ search: 'climate', mode: 'keyword' })
    expect(screen.getByText('当前仅支持关键词搜索。')).toBeInTheDocument()
  })

  it('normalizes saved hybrid feed filters to keyword mode', async () => {
    localStorage.setItem('news-aggregator-filters', JSON.stringify({ search: 'climate', searchMode: 'hybrid' }))
    renderAt('/')

    await waitFor(() => expect(mocks.fetchNews).toHaveBeenCalled())
    expect(mocks.fetchNews.mock.calls[0][0]).toMatchObject({ search: 'climate', mode: 'keyword' })
    expect(screen.getByText('当前仅支持关键词搜索。')).toBeInTheDocument()
  })
})
