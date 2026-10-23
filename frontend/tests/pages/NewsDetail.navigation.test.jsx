import { beforeEach, describe, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation, Link } from 'react-router-dom'
import { AuthContext } from '@/context/AuthContext'
import { usePreferencesStore } from '@/stores/preferences'
import { newsKeys } from '@/services/newsQueries'
import NewsList from '@/pages/NewsList'
import NewsDetail from '@/pages/NewsDetail'
import { CapabilitiesTestProvider } from '../helpers/capabilities'
import { blockNews, checkFavoriteStatus, fetchCategories, fetchNews, fetchNewsDetail, fetchSources, unblockNews } from '@/services/api'

const apiState = vi.hoisted(() => ({ blocked: false, fetchFullArticle: vi.fn(), translate: vi.fn(), personalTranslate: vi.fn(), personalModel: false, translateError: '', articleError: '', speechSupported: false, speak: vi.fn() }))

vi.mock('@/services/api', () => ({
  fetchChannelSubscriptions: vi.fn().mockResolvedValue([]),
  fetchChannelGroups: vi.fn().mockResolvedValue([]),
  fetchChannelGroupRoots: vi.fn().mockResolvedValue([]),
  fetchNewsPreferences: vi.fn().mockResolvedValue({ scope: 'all', group_id: null }),
  saveNewsPreferences: vi.fn().mockImplementation(value => Promise.resolve(value)),
  fetchNews: vi.fn(),
  fetchNewsDetail: vi.fn(),
  fetchCategories: vi.fn(),
  fetchSources: vi.fn(),
  checkFavoriteStatus: vi.fn(),
  checkBlockedStatus: vi.fn(async () => ({ is_blocked: apiState.blocked })),
  toggleFavorite: vi.fn(),
  blockNews: vi.fn(async () => { apiState.blocked = true; return { created: true } }),
  unblockNews: vi.fn(async () => { apiState.blocked = false; return { removed: true } }),
}))

vi.mock('@/hooks/useDefaultAIModel', () => ({ useDefaultAIModel: () => ({ isPending: false, isError: false, data: { preferences: apiState.personalModel ? [{ task_kind: 'full_translation', model_config_id: 'saved-model' }] : [] } }) }))
vi.mock('@/hooks/useFullArticle', () => ({ useFullArticle: () => ({ articleLoading: false, articleError: apiState.articleError, handleFetchFullArticle: apiState.fetchFullArticle, resumeExistingFetch: vi.fn(), cancelFetch: vi.fn() }) }))
vi.mock('@/hooks/useTranslation', () => ({ useTranslation: () => ({ translating: false, translateError: apiState.translateError, translationProgress: '', showOriginal: false, setShowOriginal: vi.fn(), handleTranslate: apiState.translate }) }))
vi.mock('@/hooks/useArticleSearch', () => ({ useArticleSearch: () => ({ matchCount: 0, currentIndex: 0, goNext: vi.fn(), goPrev: vi.fn() }) }))
vi.mock('@/hooks/useArticleToc', () => ({ useArticleToc: () => ({ headings: [], activeId: '' }) }))
vi.mock('@/context/SpeechPlayerContext', () => ({
  useSpeechPlayer: () => ({ supported: false, speak: vi.fn() }),
  useSpeechPlayerActions: () => ({ speak: apiState.speak }),
  useSpeechPlayerCapabilities: () => ({ supported: apiState.speechSupported }),
  useSpeechPlayerActivity: () => false,
}))
vi.mock('@/components/news-detail/PrivateTranslationPanel', () => ({ default: () => <button type="button" onClick={apiState.personalTranslate}>翻译为中文</button> }))
vi.mock('@/components/NewsChatAssistant', () => ({
  default: ({ open, onOpenChange }) => (
    <div>
      <output data-testid="assistant-state">{open ? 'open' : 'closed'}</output>
      {open && <button type="button" onClick={() => onOpenChange(false)}>关闭测试助手</button>}
    </div>
  ),
}))

const listStory = {
  id: 21, title: 'Climate technology update', content: 'A short article summary', title_zh: '', content_zh: '', author: null,
  publish_time: '2026-10-06T09:00:00Z', source: 8, source_name: 'Example source', source_type: 'news',
  source_language: 'en', category: 2, category_name: 'Technology', url: 'https://example.com/story', cover_image: null,
  created_at: '2026-10-06T09:00:00Z', related_to: null, translation_status: '', translation_error: '',
  translation_retry_count: 0, full_content_fetch_status: '', full_content_fetch_error: '', full_content_fetch_provider: '',
  full_content_quality_score: null, full_content_retry_count: 0, last_full_content_attempt: null,
}
const detailStory = {
  ...listStory,
  source_url: listStory.url,
  full_content: '', full_content_fetched_at: null,
  full_content_zh: '', full_content_zh_fetched_at: null, full_content_zh_source: null,
  full_translation_active: false,
}

function RouteProbe() {
  const location = useLocation()
  return <><output data-testid="route">{`${location.pathname}${location.search}`}</output><Link to="/news/22">测试下一篇</Link></>
}

function renderRoutes(initialEntry, user = { id: 12, username: 'reader' }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 30_000 }, mutations: { retry: false } } })
  return {
    client,
    ...render(
      <QueryClientProvider client={client}>
        <CapabilitiesTestProvider client={client}>
          <AuthContext.Provider value={{ user, loading: false, login: vi.fn(), register: vi.fn(), logout: vi.fn(), refresh: vi.fn() }}>
            <MemoryRouter initialEntries={[initialEntry]}>
              <Routes>
                <Route path="/" element={<NewsList />} />
                <Route path="/news/:id" element={<NewsDetail />} />
              </Routes>
              <RouteProbe />
            </MemoryRouter>
          </AuthContext.Provider>
        </CapabilitiesTestProvider>
      </QueryClientProvider>,
    ),
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  apiState.blocked = false
  apiState.personalModel = false
  apiState.translateError = ''
  apiState.articleError = ''
  apiState.speechSupported = false
  apiState.fetchFullArticle.mockReset()
  localStorage.removeItem('news-aggregator-filters')
  usePreferencesStore.setState({ lang: 'zh' })
  fetchNews.mockResolvedValue({ count: 41, next: null, previous: null, results: [listStory] })
  fetchCategories.mockResolvedValue([{ id: 2, name: 'Technology' }])
  fetchSources.mockResolvedValue([{ id: 8, name: 'Example source' }])
  fetchNewsDetail.mockResolvedValue(detailStory)
  checkFavoriteStatus.mockResolvedValue({ is_liked: false, is_bookmarked: false, like_count: 0, bookmark_count: 0 })
  vi.spyOn(window, 'scrollTo').mockImplementation(() => {})
})

describe('news list return navigation and invalidation', () => {
  it('starts configured personal translation directly from the body toolbar instead of showing a form', async () => {
    apiState.personalModel = true
    apiState.translateError = '个人 AI 连接已保存；请等待模型与用途配置完成。'
    fetchNewsDetail.mockResolvedValue({ ...detailStory, full_content: 'Original article body', full_content_zh: '' })
    Element.prototype.scrollIntoView = vi.fn()
    renderRoutes('/news/21', { id: 12, username: 'reader' })
    fireEvent.click(await screen.findByRole('button', { name: '翻译为中文' }))
    expect(apiState.translate).not.toHaveBeenCalled()
    expect(apiState.personalTranslate).toHaveBeenCalledOnce()
    expect(screen.queryByLabelText('个人翻译操作')).not.toBeInTheDocument()
    expect(screen.queryByText('个人 AI 连接已保存；请等待模型与用途配置完成。')).not.toBeInTheDocument()
  })
  it.each([['', false], ['已有完整译文', true]])('retries a missing translation through shared dedup and keeps explicit regeneration personal (%s)', async (saved, force) => {
    apiState.translateError = '翻译任务失败，请重试'
    fetchNewsDetail.mockResolvedValue({ ...detailStory, full_content: 'Original article body', full_content_zh: saved })
    renderRoutes('/news/21')
    fireEvent.click(await screen.findByRole('button', { name: '重试' }))
    expect(apiState.translate).toHaveBeenCalledWith(force)
  })

  it('restores the filtered list URL and refetches after detail block and unblock', async () => {
    renderRoutes('/?search=climate&mode=keyword&category=2&source=8&page=2')
    expect(await screen.findByRole('heading', { name: 'Climate technology update' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('link', { name: /Climate technology update/ }))
    expect(await screen.findByRole('heading', { name: 'Climate technology update' })).toBeInTheDocument()
    expect(await screen.findByRole('button', { name: '屏蔽此新闻' })).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '屏蔽此新闻' }))
    expect(await screen.findByRole('button', { name: '取消屏蔽' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('link', { name: /返回列表/ }))
    await waitFor(() => expect(screen.getByTestId('route')).toHaveTextContent('/?search=climate&mode=keyword&category=2&source=8&page=2'))
    await waitFor(() => expect(fetchNews).toHaveBeenCalledTimes(2))
    expect(fetchNews).toHaveBeenLastCalledWith({ scope: 'all', page: 2, page_size: 20, search: 'climate', mode: 'keyword', category: '2', source: '8' }, expect.any(AbortSignal))

    fireEvent.click(screen.getByRole('link', { name: /Climate technology update/ }))
    expect(await screen.findByRole('button', { name: '取消屏蔽' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '取消屏蔽' }))
    expect(await screen.findByRole('button', { name: '屏蔽此新闻' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('link', { name: /返回列表/ }))
    await waitFor(() => expect(screen.getByTestId('route')).toHaveTextContent('/?search=climate&mode=keyword&category=2&source=8&page=2'))
    await waitFor(() => expect(fetchNews).toHaveBeenCalledTimes(3))
    expect(blockNews).toHaveBeenCalledWith(21)
    expect(unblockNews).toHaveBeenCalledWith(21)
  })

  it('uses the home page as the back-link destination for a directly opened detail URL', async () => {
    renderRoutes('/news/21')
    const backLink = await screen.findByRole('link', { name: /返回列表/ })
    expect(backLink).toHaveAttribute('href', '/')
  })

  it('offers original-body loading for Chinese stories and does not repeat the source as author', async () => {
    fetchNewsDetail.mockResolvedValue({
      ...detailStory,
      id: 3033,
      title: '迁移权责确权层｜跨域行为的权属与越界判定',
      author: '量子位',
      source_name: '量子位',
      source_language: 'zh',
      content: '第一段正文。\u3000\u3000第二段正文。',
      full_content: '',
      full_content_fetch_status: 'pending',
    })
    renderRoutes('/news/3033')

    expect(await screen.findByRole('heading', { name: '迁移权责确权层｜跨域行为的权属与越界判定' })).toBeInTheDocument()
    expect(screen.getAllByText('量子位')).toHaveLength(1)
    expect(screen.getByRole('button', { name: '获取完整原文' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: '内容摘要' })).toBeInTheDocument()
    const firstParagraph = screen.getByText('第一段正文。').closest('p')
    const secondParagraph = screen.getByText('第二段正文。').closest('p')
    expect(firstParagraph).not.toBe(secondParagraph)
  })

  it('shows the formatted full article without repeating its summary', async () => {
    fetchNewsDetail.mockResolvedValue({
      ...detailStory,
      id: 3369,
      title: 'Claude Haiku 5.5 降本背后',
      source_language: 'zh',
      content: '这段摘要不应在全文下方重复出现。',
      full_content: '## 复杂编程仍有差距\n\n第一段完整正文。\n\n第二段完整正文。',
      full_content_fetch_status: 'success',
      full_content_fetch_provider: 'leiphone_feed',
    })
    renderRoutes('/news/3369')

    expect(await screen.findByRole('heading', { name: '复杂编程仍有差距' })).toBeInTheDocument()
    expect(screen.getByText('第一段完整正文。')).toBeInTheDocument()
    expect(screen.queryByText('这段摘要不应在全文下方重复出现。')).not.toBeInTheDocument()
    expect(screen.queryByRole('region', { name: '内容摘要' })).not.toBeInTheDocument()
  })

  it('opens the same article assistant from the header and summary action', async () => {
    renderRoutes('/news/21')

    expect(await screen.findByRole('button', { name: '询问 AI 助手小闻' })).toBeInTheDocument()
    expect(screen.queryByTestId('assistant-state')).not.toBeInTheDocument()
    const headerAssistantButton = screen.getByRole('button', { name: '询问 AI 助手小闻' })
    fireEvent.click(headerAssistantButton)
    expect(await screen.findByTestId('assistant-state')).toHaveTextContent('open')
    fireEvent.click(screen.getByRole('button', { name: '关闭测试助手' }))
    await waitFor(() => expect(screen.queryByTestId('assistant-state')).not.toBeInTheDocument())
    await waitFor(() => expect(headerAssistantButton).toHaveFocus())
    const summaryAssistantButton = screen.getByRole('button', { name: '基于摘要提问' })
    fireEvent.click(summaryAssistantButton)
    expect(await screen.findByTestId('assistant-state')).toHaveTextContent('open')
    fireEvent.click(screen.getByRole('button', { name: '关闭测试助手' }))
    await waitFor(() => expect(summaryAssistantButton).toHaveFocus())
  })

  it('opens the login dialog instead of posting a full fetch for a signed-out reader', async () => {
    fetchNewsDetail.mockResolvedValue({
      ...detailStory,
      id: 3033,
      title: '迁移权责确权层｜跨域行为的权属与越界判定',
      source_language: 'zh',
      content: '摘要',
      full_content: '',
      full_content_fetch_status: 'pending',
    })
    renderRoutes('/news/3033', null)

    fireEvent.click(await screen.findByRole('button', { name: '获取完整原文' }))

    expect(await screen.findByRole('dialog', { name: '登录小闻' })).toBeInTheDocument()
    expect(apiState.fetchFullArticle).not.toHaveBeenCalled()
  })
})


it('shows a new fetch failure when body permission allows retrying a formerly unsupported article', async () => {
  apiState.articleError = '正文获取服务暂不可用，请稍后重试。'
  fetchNewsDetail.mockResolvedValue({ ...detailStory, reading_policy: 'rss_summary_only', body_access_granted: true,
    can_fetch_full_content: true, full_content_fetch_status: 'unsupported' })
  renderRoutes('/news/21')
  expect(await screen.findByText('正文获取服务暂不可用，请稍后重试。')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: '尝试获取正文' })).toBeInTheDocument()
  expect(screen.getByText('尚未保存完整原文')).toBeInTheDocument()
})


it('does not autoplay the next article when a previous translate-and-play request is still pending', async () => {
  apiState.speechSupported = true
  let finish
  apiState.translate.mockImplementation(() => new Promise(resolve => { finish = resolve }))
  fetchNewsDetail.mockImplementation(async id => ({
    ...detailStory, id: Number(id), title: Number(id) === 21 ? 'First article' : 'Second article',
    full_content: Number(id) === 21 ? 'First original body' : 'Second original body',
    full_content_state: 'available', full_content_revision: 1, body_access_granted: true,
    full_content_zh: Number(id) === 21 ? '' : 'Second saved Chinese translation',
  }))
  renderRoutes('/news/21')
  await screen.findByRole('heading', { name: 'First article' })
  fireEvent.click(screen.getByRole('button', { name: '选择语音播报方式' }))
  fireEvent.click(screen.getByRole('button', { name: '翻译全文并播放' }))
  expect(apiState.translate).toHaveBeenCalledWith(false)
  fireEvent.click(screen.getByRole('link', { name: '测试下一篇' }))
  await screen.findByRole('heading', { name: 'Second article' })
  expect(apiState.speak).not.toHaveBeenCalled()
  await act(async () => finish(false))
  expect(apiState.speak).not.toHaveBeenCalled()
})


it('autoplays the matching translated article once when cache and completion arrive together', async () => {
  apiState.speechSupported = true
  let finish
  apiState.translate.mockImplementation(() => new Promise(resolve => { finish = resolve }))
  fetchNewsDetail.mockResolvedValue({ ...detailStory, full_content: 'Original body',
    full_content_state: 'available', full_content_revision: 1, body_access_granted: true })
  const { client } = renderRoutes('/news/21')
  await screen.findByRole('heading', { name: 'Climate technology update' })
  fireEvent.click(screen.getByRole('button', { name: '选择语音播报方式' }))
  fireEvent.click(screen.getByRole('button', { name: '翻译全文并播放' }))
  await act(async () => {
    client.setQueryData(newsKeys.detail(21, 'zh', 12), old => ({ ...old, full_content_zh: 'Matching Chinese translation' }))
  })
  await waitFor(() => expect(apiState.speak).toHaveBeenCalledTimes(1))
  await act(async () => finish(true))
  expect(apiState.speak).toHaveBeenCalledTimes(1)
  expect(apiState.speak.mock.calls[0][0]).toBe(21)
})


it.each(['', 'fr'])('does not treat unknown/non-Chinese source language %s as ready Chinese speech', async (sourceLanguage) => {
  apiState.speechSupported = true
  fetchNewsDetail.mockResolvedValue({ ...detailStory, source_language: sourceLanguage,
    full_content: 'Original body', full_content_state: 'available', body_access_granted: true })
  renderRoutes('/news/21')
  await screen.findByRole('heading', { name: 'Climate technology update' })
  fireEvent.click(screen.getByRole('button', { name: '选择语音播报方式' }))
  expect(screen.queryByText('中文内容已就绪，可以播放。')).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: '翻译全文并播放' })).toBeEnabled()
  fireEvent.click(screen.getByRole('button', { name: /^原文/ }))
  fireEvent.click(screen.getByRole('button', { name: '开始播放' }))
  expect(apiState.speak).toHaveBeenCalledWith(21, 'Climate technology update', { language: 'original', scope: 'full' })
  expect(apiState.translate).not.toHaveBeenCalled()
})
