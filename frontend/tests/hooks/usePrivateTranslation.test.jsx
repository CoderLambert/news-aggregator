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

function strictWrapper({ children }) {
  return createElement(AuthContext.Provider, {
    value: { user: { id: 12, username: 'reader' }, loading: false, login: vi.fn(), register: vi.fn(), logout: vi.fn(), refresh: vi.fn() },
  }, children)
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
    result: { full_content_zh: '从任务恢复的译文', result_id: 'result-recovered', current_match: true },
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

  it('reattaches after StrictMode effect replay instead of suppressing the second recovery setup', async () => {
    localStorage.setItem('byok_translation_recovery_v1:12:42', '123e4567-e89b-12d3-a456-426614174000')
    const requests = []
    api.getPrivateTranslationJob.mockImplementation((_jobId, signal) => new Promise((resolve, reject) => {
      requests.push({ resolve, signal })
      signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')), { once: true })
    }))

    const { result, unmount } = renderHook(() => usePrivateTranslation(42, article(), true, false), { wrapper: strictWrapper, reactStrictMode: true })
    await waitFor(() => expect(requests).toHaveLength(2))
    expect(requests[0].signal.aborted).toBe(true)
    await act(async () => {
      requests[1].resolve(task())
    })

    await waitFor(() => expect(result.current.privateTranslationResult).toBe('从任务恢复的译文'))
    expect(result.current.privateTranslationResultCurrentMatch).toBe(true)
    unmount()
  })

  it('ignores a delayed recovery response from the previous source and marks the current-source lookup stale', async () => {
    localStorage.setItem('byok_translation_recovery_v1:12:42', '123e4567-e89b-12d3-a456-426614174000')
    const requests = []
    api.getPrivateTranslationJob.mockImplementation((_jobId, signal) => new Promise((resolve) => {
      requests.push({ resolve, signal })
    }))
    const { result, rerender, unmount } = renderHook(({ news }) => usePrivateTranslation(42, news, true, false), {
      initialProps: { news: article() }, wrapper,
    })

    await waitFor(() => expect(requests).toHaveLength(1))
    rerender({ news: { ...article(), full_content: 'A changed source body.' } })
    await waitFor(() => expect(requests).toHaveLength(2))
    expect(requests[0].signal.aborted).toBe(true)

    await act(async () => {
      requests[0].resolve(task({ result: { full_content_zh: 'late source A', result_id: 'late-result-a', current_match: true } }))
    })
    expect(result.current.privateTranslationResult).toBe('')
    expect(result.current.privateTranslationResultId).toBe('')
    expect(result.current.privateTranslationResultCurrentMatch).toBeNull()

    await act(async () => {
      requests[1].resolve(task({ result: { full_content_zh: 'source A stale result', result_id: 'stale-result-a', current_match: false } }))
    })
    await waitFor(() => expect(result.current.privateTranslationResultId).toBe('stale-result-a'))
    expect(result.current.privateTranslationResultCurrentMatch).toBe(false)
    unmount()
  })

  it('keeps a completed source A job stale when recovery attaches after the article changed to source B', async () => {
    localStorage.setItem('byok_translation_recovery_v1:12:42', '123e4567-e89b-12d3-a456-426614174000')
    api.getPrivateTranslationJob.mockResolvedValue(task({
      status: 'succeeded',
      result: { full_content_zh: 'Source A translation', result_id: 'source-a-result', current_match: false },
    }))

    const sourceB = { ...article(), full_content: 'Source B article body.' }
    const { result, unmount } = renderHook(() => usePrivateTranslation(42, sourceB, true, false), { wrapper })

    await waitFor(() => expect(result.current.privateTranslationResultId).toBe('source-a-result'))
    expect(result.current.privateTranslationResult).toBe('Source A translation')
    expect(result.current.privateTranslationResultCurrentMatch).toBe(false)
    expect(result.current.privateTranslationActive).toBe(false)
    expect(localStorage.getItem('byok_translation_recovery_v1:12:42')).toBeNull()
    expect(api.getPrivateTranslationJob).toHaveBeenCalledWith(
      '123e4567-e89b-12d3-a456-426614174000', expect.any(AbortSignal),
    )
    unmount()
  })

  it('keeps a known job after an SSE error until a terminal status read succeeds', async () => {
    const jobId = '123e4567-e89b-12d3-a456-426614174005'
    api.getPrivateTranslationJob
      .mockRejectedValueOnce(new Error('temporary status read failure'))
      .mockResolvedValueOnce(task({ id: jobId, status: 'failed', result: {}, errorMessage: 'terminal failure' }))
    api.translatePrivateFullArticleStream.mockImplementation(async function* (_id, _key, options) {
      options.onJobId(jobId)
      yield { type: 'error', message: 'subscriber transport failed' }
    })

    const { result, unmount } = renderHook(() => usePrivateTranslation(42, article(), true, false), { wrapper })
    let run
    act(() => { run = result.current.startPrivateTranslation() })
    await act(async () => { await run })

    expect(result.current.privateTranslationActive).toBe(true)
    expect(result.current.privateTranslationJobId).toBe(jobId)
    expect(localStorage.getItem('byok_translation_recovery_v1:12:42')).toBe(jobId)
    await act(async () => { await result.current.startPrivateTranslation() })
    expect(api.translatePrivateFullArticleStream).toHaveBeenCalledOnce()

    await act(async () => { await result.current.checkPrivateTranslationStatus() })
    expect(result.current.privateTranslationActive).toBe(false)
    expect(result.current.privateTranslationJobId).toBe(jobId)
    expect(result.current.privateTranslationError).toBe('terminal failure')
    expect(localStorage.getItem('byok_translation_recovery_v1:12:42')).toBeNull()
    unmount()
  })

  it('keeps a recovered job after its first GET fails and exposes terminal recheck', async () => {
    localStorage.setItem('byok_translation_recovery_v1:12:42', '123e4567-e89b-12d3-a456-426614174000')
    api.getPrivateTranslationJob
      .mockRejectedValueOnce(new Error('temporary recovery GET failure'))
      .mockResolvedValueOnce(task({ result: { full_content_zh: 'recovered terminal result', result_id: 'recovered-terminal', current_match: true } }))

    const { result, unmount } = renderHook(() => usePrivateTranslation(42, article(), true, false), { wrapper })
    await waitFor(() => expect(result.current.privateTranslationError).toMatch(/重新检查状态/))
    expect(result.current.privateTranslationActive).toBe(true)
    expect(result.current.privateTranslationJobId).toBe('123e4567-e89b-12d3-a456-426614174000')

    await act(async () => { await result.current.startPrivateTranslation() })
    expect(api.translatePrivateFullArticleStream).not.toHaveBeenCalled()

    await act(async () => { await result.current.checkPrivateTranslationStatus() })
    expect(result.current.privateTranslationResult).toBe('recovered terminal result')
    expect(result.current.privateTranslationResultId).toBe('recovered-terminal')
    expect(result.current.privateTranslationResultCurrentMatch).toBe(true)
    expect(result.current.privateTranslationActive).toBe(false)
    expect(localStorage.getItem('byok_translation_recovery_v1:12:42')).toBeNull()
    unmount()
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

  it.each(['GET', 'POST'])('keeps the job recoverable when cancellation %s fails and blocks a new create', async (failedStage) => {
    vi.stubGlobal('crypto', { randomUUID: vi.fn().mockReturnValueOnce('first-key').mockReturnValueOnce('second-key') })
    let streamSignal
    let streamRun = 0
    api.translatePrivateFullArticleStream.mockImplementation(async function* (_id, _key, options) {
      streamRun += 1
      const jobId = streamRun === 1
        ? '123e4567-e89b-12d3-a456-426614174000'
        : '123e4567-e89b-12d3-a456-426614174001'
      options.onJobId(jobId)
      if (streamRun === 1) {
        yield { type: 'complete', result: { full_content_zh: '已有译文 A', result_id: 'result-a' } }
        return
      }
      streamSignal = options.signal
      yield { type: 'progress', text: '译文 B 正在生成' }
      await waitForAbort(options.signal)
    })
    if (failedStage === 'GET') {
      api.getPrivateTranslationJob
        .mockRejectedValueOnce(new Error('temporary GET failure'))
        .mockResolvedValueOnce(task({ status: 'running', generation: 7, result: {} }))
    } else {
      api.getPrivateTranslationJob.mockResolvedValue(task({ status: 'running', generation: 7, result: {} }))
    }
    if (failedStage === 'POST') {
      api.cancelPrivateTranslationJob
        .mockRejectedValueOnce(new Error('temporary POST failure'))
        .mockResolvedValueOnce(task({ status: 'cancelled', generation: 7, result: {}, errorMessage: '本次个人翻译已取消。' }))
    } else {
      api.cancelPrivateTranslationJob.mockResolvedValue(task({ status: 'cancelled', generation: 7, result: {}, errorMessage: '本次个人翻译已取消。' }))
    }
    api.getPrivateTranslationResult.mockResolvedValue({
      resultId: 'result-a', text: '已有译文 A', currentMatch: true, sourceHash: 'source-a', modelSource: null,
    })

    const { result, unmount } = renderHook(() => usePrivateTranslation(42, article(), true, false), { wrapper })
    await act(async () => { await result.current.startPrivateTranslation() })
    expect(result.current.privateTranslationResult).toBe('已有译文 A')
    let secondRun
    act(() => { secondRun = result.current.startPrivateTranslation() })
    await waitFor(() => expect(result.current.privateTranslationProgress).toBe('译文 B 正在生成'))

    await act(async () => { await result.current.cancelPrivateTranslation() })

    expect(result.current.privateTranslationActive).toBe(true)
    expect(result.current.privateTranslationCancelPending).toBe(true)
    expect(result.current.privateTranslationJobId).toBe('123e4567-e89b-12d3-a456-426614174001')
    expect(result.current.privateTranslationResult).toBe('已有译文 A')
    expect(localStorage.getItem('byok_translation_recovery_v1:12:42')).toBe('123e4567-e89b-12d3-a456-426614174001')
    expect(result.current.privateTranslationError).toMatch(/可能仍在运行/)

    await act(async () => { await result.current.startPrivateTranslation() })
    expect(api.translatePrivateFullArticleStream).toHaveBeenCalledTimes(2)
    expect(globalThis.crypto.randomUUID).toHaveBeenCalledTimes(2)

    await act(async () => { await result.current.cancelPrivateTranslation() })
    await act(async () => { await secondRun })
    expect(api.cancelPrivateTranslationJob).toHaveBeenCalledWith('123e4567-e89b-12d3-a456-426614174001', 7)
    expect(result.current.privateTranslationActive).toBe(false)
    expect(result.current.privateTranslationCancelPending).toBe(false)
    expect(result.current.privateTranslationResult).toBe('已有译文 A')
    expect(streamSignal.aborted).toBe(true)
    expect(localStorage.getItem('byok_translation_recovery_v1:12:42')).toBeNull()
    unmount()
  })

  it('retains the job after cancellation POST and stream failures until a terminal recheck', async () => {
    vi.stubGlobal('crypto', { randomUUID: vi.fn().mockReturnValue('stable-key') })
    let failStream
    api.getPrivateTranslationJob
      .mockResolvedValueOnce(task({ status: 'running', generation: 9, result: {} }))
      .mockResolvedValueOnce(task({
        status: 'succeeded',
        generation: 9,
        result: { full_content_zh: 'late completed result', result_id: 'late-complete-id', current_match: true },
      }))
    api.cancelPrivateTranslationJob.mockRejectedValueOnce(new Error('temporary cancel POST failure'))
    api.translatePrivateFullArticleStream.mockImplementation(async function* (_id, _key, options) {
      options.onJobId('123e4567-e89b-12d3-a456-426614174004')
      yield { type: 'progress', text: '等待流断开' }
      await new Promise((resolve) => { failStream = resolve })
      throw new Error('temporary stream transport failure')
    })

    const { result, unmount } = renderHook(() => usePrivateTranslation(42, article(), true, false), { wrapper })
    let startRun
    act(() => { startRun = result.current.startPrivateTranslation() })
    await waitFor(() => expect(result.current.privateTranslationProgress).toBe('等待流断开'))

    await act(async () => { await result.current.cancelPrivateTranslation() })
    expect(result.current.privateTranslationActive).toBe(true)
    expect(result.current.privateTranslationCancelPending).toBe(true)
    expect(result.current.privateTranslationJobId).toBe('123e4567-e89b-12d3-a456-426614174004')

    await act(async () => {
      failStream()
      await startRun
    })
    expect(result.current.privateTranslationActive).toBe(true)
    expect(result.current.privateTranslationJobId).toBe('123e4567-e89b-12d3-a456-426614174004')
    expect(result.current.privateTranslationError).toMatch(/再次取消/)
    expect(localStorage.getItem('byok_translation_recovery_v1:12:42')).toBe('123e4567-e89b-12d3-a456-426614174004')

    await act(async () => { await result.current.startPrivateTranslation() })
    expect(api.translatePrivateFullArticleStream).toHaveBeenCalledOnce()

    await act(async () => { await result.current.checkPrivateTranslationStatus() })
    expect(result.current.privateTranslationActive).toBe(false)
    expect(result.current.privateTranslationResult).toBe('late completed result')
    expect(result.current.privateTranslationResultId).toBe('late-complete-id')
    expect(localStorage.getItem('byok_translation_recovery_v1:12:42')).toBeNull()
    unmount()
  })

  it('keeps a succeeded result when a pending cancel races with completion', async () => {
    let resolveCancel
    let completeStream
    api.getPrivateTranslationJob.mockResolvedValue(task({ status: 'running', generation: 4, result: {} }))
    api.cancelPrivateTranslationJob.mockImplementation(() => new Promise((resolve) => { resolveCancel = resolve }))
    api.getPrivateTranslationResult.mockResolvedValue({
      resultId: 'result-b', text: '成功结果 B', currentMatch: true, sourceHash: 'source-b', modelSource: null,
    })
    api.translatePrivateFullArticleStream.mockImplementation(async function* (_id, _key, options) {
      options.onJobId('123e4567-e89b-12d3-a456-426614174002')
      yield { type: 'progress', text: '等待完成' }
      await new Promise((resolve) => { completeStream = resolve })
      yield { type: 'complete', result: { full_content_zh: '成功结果 B', result_id: 'result-b' } }
    })

    const { result, unmount } = renderHook(() => usePrivateTranslation(42, article(), true, false), { wrapper })
    let startRun
    act(() => { startRun = result.current.startPrivateTranslation() })
    await waitFor(() => expect(result.current.privateTranslationProgress).toBe('等待完成'))
    await waitFor(() => expect(result.current.privateTranslationJobId).toBe('123e4567-e89b-12d3-a456-426614174002'))
    let cancelRun
    act(() => { cancelRun = result.current.cancelPrivateTranslation() })
    await waitFor(() => expect(resolveCancel).toBeDefined())

    await act(async () => {
      completeStream()
      await startRun
    })
    await act(async () => {
      resolveCancel(task({ status: 'succeeded', generation: 4, result: { full_content_zh: '成功结果 B', result_id: 'result-b' } }))
      await cancelRun
    })

    expect(result.current.privateTranslationResult).toBe('成功结果 B')
    expect(result.current.privateTranslationResultId).toBe('result-b')
    expect(result.current.privateTranslationCancelPending).toBe(false)
    expect(result.current.privateTranslationActive).toBe(false)
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
    api.getPrivateTranslationJob.mockResolvedValue(task({
      id: '123e4567-e89b-12d3-a456-426614174001',
      status: 'failed',
      result: {},
      errorMessage: '新任务失败',
    }))
    api.getPrivateTranslationResult.mockResolvedValue({
      resultId: 'result-old', text: '旧的成功译文', currentMatch: true, sourceHash: 'source-old', modelSource: null,
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

  it('ignores a late private result after the source body changes', async () => {
    api.getPrivateTranslationJob.mockResolvedValue(task({ status: 'cancelled', result: {} }))
    let streamSignal
    let completeStream
    api.translatePrivateFullArticleStream.mockImplementation(async function* (_id, _key, options) {
      streamSignal = options.signal
      options.onJobId('123e4567-e89b-12d3-a456-426614174003')
      yield { type: 'progress', text: '旧原文任务进行中' }
      await new Promise((resolve) => { completeStream = resolve })
      yield { type: 'complete', result: { full_content_zh: '旧原文译文', result_id: 'old-source-result' } }
    })

    const { result, rerender } = renderHook(({ news }) => usePrivateTranslation(42, news, true, false), {
      initialProps: { news: article() }, wrapper,
    })
    let startRun
    act(() => { startRun = result.current.startPrivateTranslation() })
    await waitFor(() => expect(result.current.privateTranslationProgress).toBe('旧原文任务进行中'))
    const updatedArticle = { ...article(), full_content: 'A new body with different source text.' }
    rerender({ news: updatedArticle })
    await waitFor(() => expect(streamSignal.aborted).toBe(true))
    await act(async () => {
      completeStream()
      await startRun
    })

    expect(result.current.privateTranslationResult).toBe('')
    expect(result.current.privateTranslationResultId).toBe('')
    expect(result.current.privateTranslationActive).toBe(false)
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
