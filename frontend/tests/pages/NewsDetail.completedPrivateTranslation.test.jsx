import { beforeEach, describe, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { AuthContext } from '@/context/AuthContext'
import * as workflowApi from '@/services/newsWorkflowApi'
import { CapabilitiesTestProvider } from '../helpers/capabilities'
import NewsDetail from '@/pages/NewsDetail'
import { usePreferencesStore } from '@/stores/preferences'
import { checkFavoriteStatus, fetchCategories, fetchNewsDetail, fetchSources } from '@/services/api'

const apiState = vi.hoisted(() => ({ speak: vi.fn(), speechSupported: false }))

vi.mock('@/services/newsWorkflowApi', async (importOriginal) => ({
  ...await importOriginal(),
  cancelPrivateTranslationJob: vi.fn(),
  getPrivateTranslationJob: vi.fn(),
  getPrivateTranslationResult: vi.fn(),
  translatePrivateFullArticleStream: vi.fn(),
}))

vi.mock('@/services/api', () => ({
  fetchNews: vi.fn(),
  fetchNewsDetail: vi.fn(),
  fetchCategories: vi.fn(),
  fetchSources: vi.fn(),
  checkFavoriteStatus: vi.fn(),
  checkBlockedStatus: vi.fn(async () => ({ is_blocked: false })),
  toggleFavorite: vi.fn(),
  blockNews: vi.fn(),
  unblockNews: vi.fn(),
}))

vi.mock('@/hooks/useFullArticle', () => ({ useFullArticle: () => ({ articleLoading: false, articleError: '', handleFetchFullArticle: vi.fn(), resumeExistingFetch: vi.fn(), cancelFetch: vi.fn() }) }))
vi.mock('@/hooks/useTranslation', () => ({ useTranslation: () => ({ translating: false, translateError: '', translationProgress: '', showOriginal: false, setShowOriginal: vi.fn(), handleTranslate: vi.fn() }) }))
vi.mock('@/hooks/useArticleSearch', () => ({ useArticleSearch: () => ({ matchCount: 0, currentIndex: 0, goNext: vi.fn(), goPrev: vi.fn() }) }))
vi.mock('@/hooks/useArticleToc', () => ({ useArticleToc: () => ({ headings: [], activeId: '' }) }))
vi.mock('@/context/SpeechPlayerContext', () => ({
  useSpeechPlayer: () => ({ supported: false, speak: vi.fn() }),
  useSpeechPlayerActions: () => ({ speak: apiState.speak }),
  useSpeechPlayerCapabilities: () => ({ supported: apiState.speechSupported }),
  useSpeechPlayerActivity: () => false,
}))
vi.mock('@/components/NewsChatAssistant', () => ({
  default: ({ open, translationResultId }) => (
    <div data-testid="assistant-translation-id" data-result-id={translationResultId ?? ''}>
      <output data-testid="assistant-state">{open ? 'open' : 'closed'}</output>
    </div>
  ),
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
  source_url: 'https://example.com/story',
  cover_image: null,
  created_at: '2026-10-06T09:00:00Z',
  related_to: null,
  translation_status: '',
  translation_error: '',
  translation_retry_count: 0,
  full_content_fetch_status: 'success',
  full_content_fetch_error: '',
  full_content_fetch_provider: '',
  full_content_quality_score: null,
  full_content_retry_count: 0,
  last_full_content_attempt: null,
  full_content: 'English source body',
  full_content_fetched_at: null,
  full_content_zh: '旧的共享译文 A',
  full_content_zh_result_id: 'shared-result-a',
  full_content_zh_current_match: true,
  full_content_zh_scope: 'shared',
  full_content_zh_fetched_at: null,
  full_content_zh_source: null,
  full_translation_active: false,
}

describe('NewsDetail completed private translation', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    apiState.speechSupported = true
    localStorage.clear()
    usePreferencesStore.setState({ lang: 'zh' })
    fetchCategories.mockResolvedValue([{ id: 2, name: 'Technology' }])
    fetchSources.mockResolvedValue([{ id: 8, name: 'Example source' }])
    fetchNewsDetail.mockResolvedValue(story)
    checkFavoriteStatus.mockResolvedValue({ is_liked: false, is_bookmarked: false, like_count: 0, bookmark_count: 0 })
  })

  it('uses a newly completed personal translation for body, copy, chat, and speech', async () => {
    workflowApi.translatePrivateFullArticleStream.mockImplementation(async function* (_newsId, _key, options) {
      options.onJobId('123e4567-e89b-12d3-a456-426614174003')
      yield {
        type: 'complete',
        result: {
          full_content_zh: '最新个人译文 B',
          result_id: 'private-result-b',
          current_match: true,
        },
      }
    })
    workflowApi.getPrivateTranslationResult.mockResolvedValue({
      resultId: 'private-result-b',
      text: '最新个人译文 B',
      sourceHash: 'current-source-hash',
      currentMatch: true,
      modelSource: { provider: 'DeepSeek', model: 'DeepSeek Flash' },
    })

    const clipboardWrite = vi.fn().mockResolvedValue(undefined)
    const oldClipboard = Object.getOwnPropertyDescriptor(navigator, 'clipboard')
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText: clipboardWrite },
    })
    let unmount = () => {}

    try {
      const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 30_000 }, mutations: { retry: false } } })
      const rendered = render(
        <QueryClientProvider client={client}>
          <CapabilitiesTestProvider client={client}>
            <AuthContext.Provider value={{ user: { id: 12, username: 'reader' }, loading: false, login: vi.fn(), register: vi.fn(), logout: vi.fn(), refresh: vi.fn() }}>
              <MemoryRouter initialEntries={['/news/21']}>
                <Routes><Route path="/news/:id" element={<NewsDetail />} /></Routes>
              </MemoryRouter>
            </AuthContext.Provider>
          </CapabilitiesTestProvider>
        </QueryClientProvider>,
      )
      unmount = rendered.unmount

      expect(await screen.findByText('旧的共享译文 A')).toBeInTheDocument()
      fireEvent.click(screen.getByRole('button', { name: '使用个人模型翻译' }))

      expect(await screen.findByText('最新个人译文 B')).toBeInTheDocument()
      expect(screen.queryByText('旧的共享译文 A')).not.toBeInTheDocument()

      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: '复制全文' }))
        await Promise.resolve()
      })
      expect(clipboardWrite).toHaveBeenCalledWith('最新个人译文 B')

      fireEvent.click(screen.getByRole('button', { name: '询问 AI 助手小闻' }))
      await waitFor(() => expect(screen.getByTestId('assistant-translation-id')).toHaveAttribute('data-result-id', 'private-result-b'))

      fireEvent.click(screen.getByRole('button', { name: '选择语音播报方式' }))
      fireEvent.click(screen.getByRole('button', { name: '开始播放' }))
      expect(apiState.speak).toHaveBeenCalledWith(21, expect.any(String), {
        language: 'zh', scope: 'full', resultId: 'private-result-b',
      })
    } finally {
      unmount()
      if (oldClipboard) Object.defineProperty(navigator, 'clipboard', oldClipboard)
      else delete navigator.clipboard
    }
  })
})
