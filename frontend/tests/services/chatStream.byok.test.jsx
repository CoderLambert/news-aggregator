import { beforeEach, describe, expect, it, vi } from 'vitest'
import { chatStream } from '@/services/api'

const wire = vi.hoisted(() => ({
  streamingFetch: vi.fn(async () => ({ ok: true })),
  iterTextChunks: vi.fn(async function* () { yield 'synthetic' }),
  iterSSEEvents: vi.fn(),
}))

vi.mock('@/utils/sse', () => wire)

beforeEach(() => vi.clearAllMocks())

describe('T04 personal chat request billing consent transport', () => {
  it('serializes explicit per-turn billing approval only for selected BYOK models', async () => {
    for await (const chunk of chatStream(71, 'Question', {
      modelConfigId: '11111111-1111-4111-8111-111111111111', billingConsent: true,
      turnId: '22222222-2222-4222-8222-222222222222',
    })) { expect(chunk).toBe('synthetic') }
    expect(wire.streamingFetch).toHaveBeenCalledTimes(1)
    expect(JSON.parse(wire.streamingFetch.mock.calls[0][1].body)).toEqual({
      question: 'Question', web_search: false,
      model_config_id: '11111111-1111-4111-8111-111111111111', billing_consent: true,
      turn_id: '22222222-2222-4222-8222-222222222222',
    })
  })

  it('cannot turn model selection into implicit consent, and omits consent in legacy chat', async () => {
    for await (const chunk of chatStream(71, 'Not approved', {
      modelConfigId: '11111111-1111-4111-8111-111111111111',
    })) { expect(chunk).toBe('synthetic') }
    expect(JSON.parse(wire.streamingFetch.mock.calls[0][1].body).billing_consent).toBe(false)
    for await (const chunk of chatStream(71, 'Existing route')) { expect(chunk).toBe('synthetic') }
    expect(JSON.parse(wire.streamingFetch.mock.calls[1][1].body)).toEqual({
      question: 'Existing route', web_search: false,
    })
  })
})
