import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createElement } from 'react'
import { act, renderHook, waitFor } from '@testing-library/react'
import { AuthContext } from '@/context/AuthContext'
import * as api from '@/services/newsWorkflowApi'
import { usePrivateTranslation } from '@/hooks/usePrivateTranslation'

vi.mock('@/services/newsWorkflowApi', async (importOriginal) => ({
  ...await importOriginal(),
  cancelPrivateTranslationJob: vi.fn(),
  getPrivateTranslationJob: vi.fn(),
  getPrivateTranslationResult: vi.fn(),
  translatePrivateFullArticleStream: vi.fn(),
}))

function wrapper({ children }) {
  return createElement(AuthContext.Provider, {
    value: { user: { id: 12, username: 'reader' }, loading: false, login: vi.fn(), register: vi.fn(), logout: vi.fn(), refresh: vi.fn() },
  }, children)
}

function article() {
  return { id: 42, full_content: '# Original article\n\nFull text.' }
}

function waitForAbort(signal) {
  return new Promise((resolve) => {
    if (signal.aborted) resolve()
    else signal.addEventListener('abort', resolve, { once: true })
  })
}

function task(overrides = {}) {
  return {
    id: '123e4567-e89b-12d3-a456-426614174000',
    status: 'succeeded',
    generation: 1,
    progress: '',
    result: { full_content_zh: '从任务恢复的译文', result_id: 'result-recovered' },
    errorCode: '',
    errorMessage: '',
    ...overrides,
  }
}

describe('usePrivateTranslation', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('disconnects viewing without cancelling and reattaches to the saved job after remount', async () => {
    let streamSignal
    api.translatePrivateFullArticleStream.mockImplementation(async function* (_id, _key, options) {
      streamSignal = options.signal
      options.onJobId('123e4567-e89b-12d3-a456-426614174000')
      yield { type: 'progress', text: '翻译进行中' }
      await waitForAbort(options.signal)
    })
    api.getPrivateTranslationJob.mockResolvedValue(task())

    const first = renderHook(() => usePrivateTranslation(42, article(), true, false), { wrapper })
    let firstRun
    act(() => { firstRun = first.result.current.startPrivateTranslation() })
    await waitFor(() => expect(first.result.current.privateTranslationProgress).toBe('翻译进行中'))
    expect(api.translatePrivateFullArticleStream).toHaveBeenCalledOnce()
    expect(localStorage.length).toBe(1)

    first.unmount()
    await waitFor(() => expect(streamSignal.aborted).toBe(true))
    expect(api.cancelPrivateTranslationJob).not.toHaveBeenCalled()
    await act(async () => { await firstRun })

    const reattached = renderHook(() => usePrivateTranslation(42, article(), true, false), { wrapper })
    await waitFor(() => expect(reattached.result.current.privateTranslationResult).toBe('从任务恢复的译文'))
    expect(reattached.result.current.privateTranslationResultId).toBe('result-recovered')
    expect(api.getPrivateTranslationJob).toHaveBeenCalledWith(
      '123e4567-e89b-12d3-a456-426614174000', expect.any(AbortSignal),
    )
    expect(api.translatePrivateFullArticleStream).toHaveBeenCalledOnce()
    expect(api.cancelPrivateTranslationJob).not.toHaveBeenCalled()
    reattached.unmount()
  })

  it('posts explicit cancellation with the current generation and aborts the stream after confirmation', async () => {
    let streamSignal
    api.getPrivateTranslationJob.mockResolvedValue(task({ status: 'running', generation: 7, result: {} }))
    api.cancelPrivateTranslationJob.mockResolvedValue(task({ status: 'cancelled', generation: 7, result: {}, errorMessage: '本次个人翻译已取消。' }))
    api.translatePrivateFullArticleStream.mockImplementation(async function* (_id, _key, options) {
      streamSignal = options.signal
      options.onJobId('123e4567-e89b-12d3-a456-426614174000')
      yield { type: 'progress', text: '等待取消' }
      await waitForAbort(options.signal)
    })

    const { result, unmount } = renderHook(() => usePrivateTranslation(42, article(), true, false), { wrapper })
    let startRun
    act(() => { startRun = result.current.startPrivateTranslation() })
    await waitFor(() => expect(result.current.privateTranslationProgress).toBe('等待取消'))

    await act(async () => { await result.current.cancelPrivateTranslation() })
    await act(async () => { await startRun })
    expect(api.getPrivateTranslationJob).toHaveBeenCalledWith(
      '123e4567-e89b-12d3-a456-426614174000', expect.any(AbortSignal),
    )
    expect(api.cancelPrivateTranslationJob).toHaveBeenCalledWith('123e4567-e89b-12d3-a456-426614174000', 7)
    expect(streamSignal.aborted).toBe(true)
    expect(result.current.privateTranslationActive).toBe(false)
    expect(result.current.privateTranslationError).toBe('本次个人翻译已取消。')
    unmount()
  })

  it('starts explicit regeneration with a new idempotency key and keeps the old result after failure', async () => {
    vi.stubGlobal('crypto', { randomUUID: vi.fn().mockReturnValueOnce('first-key').mockReturnValueOnce('second-key') })
    let streamRun = 0
    api.translatePrivateFullArticleStream.mockImplementation(async function* (_id, idempotencyKey, options) {
      streamRun += 1
      options.onJobId(streamRun === 1
        ? '123e4567-e89b-12d3-a456-426614174000'
        : '123e4567-e89b-12d3-a456-426614174001')
      if (idempotencyKey === 'first-key') {
        yield { type: 'complete', result: { full_content_zh: '旧的成功译文', result_id: 'result-old' } }
      } else {
        yield { type: 'error', message: '新任务失败' }
      }
    })

    const { result, unmount } = renderHook(() => usePrivateTranslation(42, article(), true, false), { wrapper })
    await act(async () => { await result.current.startPrivateTranslation() })
    expect(result.current.privateTranslationResult).toBe('旧的成功译文')
    expect(result.current.privateTranslationResultId).toBe('result-old')

    await act(async () => { await result.current.startPrivateTranslation() })
    expect(api.translatePrivateFullArticleStream).toHaveBeenNthCalledWith(1, 42, 'first-key', expect.objectContaining({ signal: expect.any(AbortSignal) }))
    expect(api.translatePrivateFullArticleStream).toHaveBeenNthCalledWith(2, 42, 'second-key', expect.objectContaining({ signal: expect.any(AbortSignal) }))
    expect(result.current.privateTranslationError).toBe('新任务失败')
    expect(result.current.privateTranslationResult).toBe('旧的成功译文')
    expect(result.current.privateTranslationResultId).toBe('result-old')
    unmount()
  })

  it('loads a saved stale result by id and keeps it separate from current content', async () => {
    api.getPrivateTranslationResult.mockResolvedValue({
      resultId: 'stale-result-id',
      text: '旧版本已保存的译文',
      sourceHash: 'old-source-hash',
      currentMatch: false,
      modelSource: { provider: 'DeepSeek', model: 'DeepSeek Flash' },
    })
    const news = { ...article(), full_content_zh_stale_result_id: 'stale-result-id' }

    const { result } = renderHook(() => usePrivateTranslation(42, news, false, false), { wrapper })

    await waitFor(() => expect(result.current.privateTranslationStaleResult?.text).toBe('旧版本已保存的译文'))
    expect(api.getPrivateTranslationResult).toHaveBeenCalledWith('stale-result-id', expect.any(AbortSignal))
    expect(result.current.privateTranslationResult).toBe('')
  })
})
