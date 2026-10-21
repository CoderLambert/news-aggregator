import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('axios', () => ({ default: { create: () => ({
  get: mocks.get, interceptors: { request: { use: vi.fn() } },
}) } }))
import { checkSpeechReadiness, SpeechPreparationError } from '@/services/api'

beforeEach(() => { mocks.get.mockReset() })
const options = { language: 'zh' as const, scope: 'full' as const, voice: 'yunxi', translationResultId: 41 }

describe('shared speech admission', () => {
  it('checks the exact result and retains cancellation without invoking generation', async () => {
    mocks.get.mockResolvedValue({ data: { status: 'ready', language: 'zh', voice: 'zh-CN-YunxiNeural' } })
    const controller = new AbortController()
    await expect(checkSpeechReadiness(11, options, controller.signal)).resolves.toEqual({ language: 'zh' })
    expect(mocks.get).toHaveBeenCalledExactlyOnceWith('/news/11/tts/', {
      params: { check: '1', language: 'zh', scope: 'full', voice: 'yunxi', translation_result_id: 41 },
      signal: controller.signal,
    })
  })

  it.each([
    [409, 'translation_required', false, '中文译文'],
    [409, 'source_content_required', false, '原文'],
    [413, 'tts_text_too_long', false, '摘要'],
    [403, '', false, '权限'],
    [404, '', false, '个人译文'],
    [503, 'tts_unavailable', true, '暂不可用'],
  ])('classifies %i %s and never exposes upstream diagnostics', async (status, code, retryable, message) => {
    mocks.get.mockRejectedValue({ response: { status, data: { code, message: 'secret upstream diagnostics' } } })
    const error = await checkSpeechReadiness(11, options, new AbortController().signal).catch(error => error)
    expect(error).toBeInstanceOf(SpeechPreparationError)
    expect(error.retryable).toBe(retryable)
    expect(error.message).toContain(message)
    expect(error.message).not.toContain('secret')
  })

  it('rejects malformed successful metadata instead of starting audio', async () => {
    mocks.get.mockResolvedValue({ data: { status: 'ready', language: 'unknown' } })
    await expect(checkSpeechReadiness(11, options, new AbortController().signal)).rejects.toThrow(SpeechPreparationError)
  })
})
