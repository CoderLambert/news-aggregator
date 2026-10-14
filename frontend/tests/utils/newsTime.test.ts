import { describe, expect, it } from 'vitest'
import { formatUnverifiedNewsTime } from '@/utils/newsTime'

describe('publish and first-seen semantics', () => {
  it('does not claim inferred ingestion time was the true publication date', () => {
    const result = formatUnverifiedNewsTime('2026-10-14T03:00:00Z', 'compact')
    expect(result).toContain('站内收录：')
    expect(result).toContain('发表时间未核实')
    expect(result).not.toContain('发表于')
  })
  it('handles invalid legacy dates without inventing a current-day publication', () => {
    expect(formatUnverifiedNewsTime('invalid', 'full')).toBe('发表时间未核实')
  })
})
