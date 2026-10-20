import { describe, expect, it } from 'vitest'
import { contentCompletenessLabel } from '@/lib/contentCompleteness'

describe('content completeness shown to readers and chat', () => {
  it('never treats readable content or missing metadata as verified', () => {
    expect(contentCompletenessLabel(true)).toBe('已获取内容，完整性未确认')
    expect(contentCompletenessLabel(true, 'unknown')).toBe('已获取内容，完整性未确认')
    expect(contentCompletenessLabel(true, 'verified')).toBe('已确认全文')
    expect(contentCompletenessLabel(true, 'summary')).toBe('仅摘要')
    expect(contentCompletenessLabel(false, 'verified')).toBe('仅摘要')
  })
})
