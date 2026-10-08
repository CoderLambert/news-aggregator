import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createElement } from 'react'
import { act, renderHook, waitFor } from '@testing-library/react'
import { AuthContext } from '@/context/AuthContext'
import * as api from '@/services/newsWorkflowApi'
import { useTranslation } from '@/hooks/useTranslation'

vi.mock('@/services/newsWorkflowApi', async (importOriginal) => ({
  ...await importOriginal(),
  translateFullArticleStream: vi.fn(),
}))

function makeWrapper(getUser = () => ({ id: 12, username: 'reader' })) {
  return function Wrapper({ children }) {
    return createElement(AuthContext.Provider, {
      value: { user: getUser(), loading: false, login: vi.fn(), register: vi.fn(), logout: vi.fn(), refresh: vi.fn() },
    }, children)
  }
}

function article(overrides = {}) {
  return {
    id: 42,
    full_content: '# Original article\n\nFull text.',
    full_content_zh: '',
    full_content_zh_fetched_at: null,
    full_translation_active: false,
    ...overrides,
  }
}

describe('useTranslation', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    api.translateFullArticleStream.mockImplementation(async function* () {
      yield { type: 'complete', fullContentZh: '已保存的完整译文', fetchedAt: '2026-10-08T00:00:00Z' }
    })
  })
  afterEach(() => vi.restoreAllMocks())

  it('reuses the saved query result without an automatic stream and only translates on explicit retry', async () => {
    const savedArticle = article({ full_content_zh: '以前保存的完整译文' })
    const current = { current: savedArticle }
    const setNews = vi.fn((updater) => { current.current = updater(current.current) })
    const props = { id: '42', news: savedArticle, setNews, loading: false }
    const { result } = renderHook(({ id, news }) => useTranslation(id, news, setNews, false), {
      initialProps: props,
      wrapper: makeWrapper(),
    })

    expect(current.current.full_content_zh).toBe('以前保存的完整译文')
    expect(api.translateFullArticleStream).not.toHaveBeenCalled()
    await act(async () => { await result.current.handleTranslate(true) })

    expect(api.translateFullArticleStream).toHaveBeenCalledWith(42, { force: true, signal: expect.any(AbortSignal) })
    expect(current.current.full_content_zh).toBe('已保存的完整译文')
    expect(result.current.translating).toBe(false)
    expect(result.current.translateError).toBe('')
  })

  it('stopping is local-only and a later mount does not auto-attach until the user resumes', async () => {
    let signal
    api.translateFullArticleStream.mockImplementation(async function* (_id, options) {
      signal = options.signal
      if (api.translateFullArticleStream.mock.calls.length > 1) {
        yield { type: 'complete', fullContentZh: 'resume result', fetchedAt: null }
        return
      }
      yield { type: 'progress', text: '已完成一半' }
      await new Promise((resolve) => options.signal.addEventListener('abort', resolve, { once: true }))
    })
    const props = { id: '42', news: article({ full_translation_active: true }), setNews: vi.fn(), loading: false }
    const first = renderHook(({ id, news }) => useTranslation(id, news, props.setNews, false), {
      initialProps: props, wrapper: makeWrapper(),
    })
    await waitFor(() => expect(api.translateFullArticleStream).toHaveBeenCalledOnce())
    await waitFor(() => expect(first.result.current.translationProgress).toBe('已完成一半'))
    act(() => first.result.current.stopTranslationWait())
    expect(signal.aborted).toBe(true)
    expect(first.result.current.translationPaused).toBe(true)
    first.unmount()

    const second = renderHook(({ id, news }) => useTranslation(id, news, props.setNews, false), {
      initialProps: props, wrapper: makeWrapper(),
    })
    await waitFor(() => expect(second.result.current.translationPaused).toBe(true))
    expect(api.translateFullArticleStream).toHaveBeenCalledOnce()

    await act(async () => { await second.result.current.handleTranslate(false) })
    expect(api.translateFullArticleStream).toHaveBeenCalledTimes(2)
    second.unmount()
  })

  it('aborts and ignores a late completion after the account identity changes', async () => {
    let currentUser = { id: 12, username: 'reader-a' }
    let signal
    api.translateFullArticleStream.mockImplementation(async function* (_id, options) {
      signal = options.signal
      await new Promise((resolve) => options.signal.addEventListener('abort', resolve, { once: true }))
      yield { type: 'complete', fullContentZh: 'late result', fetchedAt: null }
    })
    const current = { current: article() }
    const setNews = vi.fn((updater) => { current.current = updater(current.current) })
    const { result, rerender } = renderHook(() => useTranslation('42', article({ full_translation_active: true }), setNews, false), {
      initialProps: { user: currentUser },
      wrapper: makeWrapper(() => currentUser),
    })
    await waitFor(() => expect(signal).toBeInstanceOf(AbortSignal))
    currentUser = { id: 13, username: 'reader-b' }
    rerender({ user: currentUser })

    await waitFor(() => expect(signal.aborted).toBe(true))
    await act(async () => {})
    expect(current.current.full_content_zh).toBe('')
    expect(result.current.translating).toBe(false)
  })

  it('keeps the previously saved translation on failure and does not auto-post again', async () => {
    api.translateFullArticleStream.mockImplementationOnce(async function* () {
      yield { type: 'error', message: 'provider unavailable' }
    })
    const props = { id: '42', news: article({ full_content_zh: 'previously saved' }), setNews: vi.fn(), loading: false }
    const { result, rerender } = renderHook(({ news }) => useTranslation('42', news, props.setNews, false), {
      initialProps: props, wrapper: makeWrapper(),
    })
    await act(async () => { await result.current.handleTranslate(false) })
    expect(result.current.translateError).toBe('provider unavailable')
    expect(props.news.full_content_zh).toBe('previously saved')
    expect(props.setNews).not.toHaveBeenCalled()
    rerender({ news: article() })
    expect(api.translateFullArticleStream).toHaveBeenCalledOnce()
  })
})
