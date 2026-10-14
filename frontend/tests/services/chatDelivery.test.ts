import { describe, expect, it } from 'vitest'
import { completionLabel, parseChatDeliveryMetadata } from '@/services/chatDelivery'
import { parseChatHistory } from '@/services/newsWorkflowApi'

describe('chat completion contract', () => {
  it('requires an explicit saved completion and keeps failure distinguishable', () => {
    expect(parseChatDeliveryMetadata('{"type":"article_context","delivery_contract":2}')).toEqual({ contract: 2 })
    expect(parseChatDeliveryMetadata('{"type":"chat_status","status":"complete","saved":true}')).toEqual({ status: 'complete', saved: true })
    expect(parseChatDeliveryMetadata('{"type":"chat_status","status":"failed"}')).toEqual({ status: 'failed', saved: false })
    expect(parseChatDeliveryMetadata('{"type":"chat_status","status":"anything"}')).toBeNull()
    expect(parseChatDeliveryMetadata('ordinary text')).toBeNull()
  })
  it('preserves interrupted and legacy status without turning them into completed history', () => {
    const parsed = parseChatHistory({ messages: [{ role: 'assistant', content: 'partial', status: 'interrupted', context_scope: 'summary' },
      { role: 'assistant', content: 'old answer' }] })
    expect(parsed.messages[0].status).toBe('interrupted')
    expect(parsed.messages[0].context_scope).toBe('summary')
    expect(completionLabel(parsed.messages[1].status)).toContain('未验证')
    expect(completionLabel('complete')).toBe('')
  })
})
