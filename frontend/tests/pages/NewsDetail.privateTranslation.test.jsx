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

const apiState = vi.hoisted(() => ({ speak: vi.fn(), translate: vi.fn(), speechSupported: false }))

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
vi.mock('@/hooks/useTranslation', () => ({ useTranslation: () => ({ translating: false, translateError: '', translationProgress: '', showOriginal: false, setShowOriginal: vi.fn(), handleTranslate: apiState.translate }) }))
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
  full_content: 'Current source B body.',
  full_content_fetched_at: null,
  full_content_zh: 'Old source A translation',
  full_content_zh_result_id: 'source-a-result',
  full_content_zh_current_match: false,
  full_content_zh_scope: 'private',
  full_content_zh_fetched_at: null,
  full_content_zh_source: null,
  full_translation_active: false,
}

describe('NewsDetail private translation source matching', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    apiState.speechSupported = true
    apiState.translate.mockResolvedValue(true)
    localStorage.clear()
    usePreferencesStore.setState({ lang: 'zh' })
    fetchCategories.mockResolvedValue([{ id: 2, name: 'Technology' }])
    fetchSources.mockResolvedValue([{ id: 8, name: 'Example source' }])
    fetchNewsDetail.mockResolvedValue(story)
    checkFavoriteStatus.mockResolvedValue({ is_liked: false, is_bookmarked: false, like_count: 0, bookmark_count: 0 })
  })

  it('uses source B for body, copy, chat, and speech when a recovered source A result is stale', async () => {
    const jobId = '123e4567-e89b-12d3-a456-426614174006'
    localStorage.setItem('byok_translation_recovery_v1:12:21', jobId)
    workflowApi.getPrivateTranslationJob.mockResolvedValue({
      id: jobId,
      status: 'succeeded',
      generation: 1,
      progress: '',
      result: {
        full_content_zh: 'Old source A translation',
        result_id: 'source-a-result',
        current_match: false,
      },
      errorCode: '',
      errorMessage: '',
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

      expect(await screen.findByText('Current source B body.')).toBeInTheDocument()
      await waitFor(() => expect(workflowApi.getPrivateTranslationJob).toHaveBeenCalledWith(jobId, expect.any(AbortSignal)))
      expect(screen.queryByText('Old source A translation')).not.toBeInTheDocument()
      expect(localStorage.getItem('byok_translation_recovery_v1:12:21')).toBeNull()
      expect(workflowApi.translatePrivateFullArticleStream).not.toHaveBeenCalled()

      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: '复制全文' }))
        await Promise.resolve()
      })
      expect(clipboardWrite).toHaveBeenCalledWith('Current source B body.')

      fireEvent.click(screen.getByRole('button', { name: '询问 AI 助手小闻' }))
      await waitFor(() => expect(screen.getByTestId('assistant-translation-id')).toHaveAttribute('data-result-id', ''))

      fireEvent.click(screen.getByRole('button', { name: '选择语音播报方式' }))
      fireEvent.click(screen.getByRole('button', { name: '翻译全文并播放' }))
      await waitFor(() => expect(apiState.speak).toHaveBeenCalledWith(21, expect.any(String), {
        language: 'zh', scope: 'full', resultId: null,
      }))
    } finally {
      unmount()
      if (oldClipboard) Object.defineProperty(navigator, 'clipboard', oldClipboard)
      else delete navigator.clipboard
    }
  })

})
