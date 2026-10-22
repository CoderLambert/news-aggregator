import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('axios', () => ({ default: { create: () => ({
  get: mocks.get, interceptors: { request: { use: vi.fn() } },
}) } }))
import { checkSpeechReadiness, fetchSpeechAudio, SpeechPreparationError } from '@/services/api'

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

it('returns a validated segment plan without exposing content', async () => {
  mocks.get.mockResolvedValue({ data: { status: 'ready', language: 'zh', segment_count: 5, content_token: 'a'.repeat(64) } })
  await expect(checkSpeechReadiness(11, options, new AbortController().signal)).resolves.toEqual({
    language: 'zh', segmentCount: 5, contentToken: 'a'.repeat(64),
  })
})


it.each([
  { segment_count: 0, content_token: 'a'.repeat(64) },
  { segment_count: 2, content_token: 'invalid' },
  { segment_count: 2 },
])('rejects a malformed segment plan before starting audio %o', async (plan) => {
  mocks.get.mockResolvedValue({ data: { status: 'ready', language: 'zh', ...plan } })
  await expect(checkSpeechReadiness(11, options, new AbortController().signal)).rejects.toBeInstanceOf(SpeechPreparationError)
})


it('buffers the exact speech segment using an abortable audio response', async () => {
  const audio = new Blob(['complete synthetic audio'.repeat(10)], { type: 'audio/mpeg' })
  mocks.get.mockResolvedValue({ data: audio })
  const signal = new AbortController().signal
  await expect(fetchSpeechAudio(11, { ...options, contentToken: 'a'.repeat(64) }, signal)).resolves.toBe(audio)
  expect(mocks.get).toHaveBeenCalledWith('/news/11/tts/', expect.objectContaining({
    responseType: 'blob', signal,
    params: expect.objectContaining({ complete: '1', content_token: 'a'.repeat(64), translation_result_id: 41 }),
  }))
})


it.each([
  new Blob(['short'], { type: 'audio/mpeg' }),
  new Blob(['x'.repeat(200)], { type: 'text/html' }),
])('does not expose invalid complete audio to the player', async (blob) => {
  mocks.get.mockResolvedValue({ data: blob })
  await expect(fetchSpeechAudio(11, { ...options, contentToken: 'a'.repeat(64) }, new AbortController().signal)).rejects.toBeInstanceOf(SpeechPreparationError)
})
