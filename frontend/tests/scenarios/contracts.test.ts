import { describe, expect, it } from 'vitest'
import { CAPABILITY_FEATURE_NAMES, parseCapabilities } from '@/services/api'
import { hasReadableFullContent, parseNewsDetail, parseNewsSummary, parsePage, parseFilterOptions } from '@/types/news'
import { parseChannels, parseGroups, parseRoots, parseSubscriptions, parseNewsPreference, validateHierarchy } from '@/types/channels'
import { MOCK_FEATURE_NAMES, capabilityFixture, detailFixture, groupFixtures, rootFixtures, sourceFixtures,
  subscriptionFixtures, summaryFixtures } from '@/mocks/fixtures'

// These are the production parsers, not parsers copied into the mock.
describe('synthetic DTOs against current NewsHub boundaries', () => {
  it('has the exact production capability feature set', () => {
    expect([...MOCK_FEATURE_NAMES].sort()).toEqual([...CAPABILITY_FEATURE_NAMES].sort())
    expect(parseCapabilities(capabilityFixture(false)).features.accounts.enabled).toBe(true)
    expect(parseCapabilities(capabilityFixture(true)).features.accounts.enabled).toBe(false)
  })
  it('unknown capability declarations do not silently open features', () => {
    const data = capabilityFixture(false)
    expect(() => parseCapabilities({ ...data, features: { ...data.features, invented: { enabled: true, reason: null } } })).toThrow()
  })
  it('summary responses remain summaries through the actual list parser', () => {
    const data = parsePage({ count: 2, next: null, previous: null, results: summaryFixtures() }, parseNewsSummary)
    expect(data.results.map(item => item.id)).toEqual([910001, 910002])
    expect(data.results.every(item => !('full_content' in item))).toBe(true)
  })
  it('rejects breaking required fields instead of silently rendering an empty title', () => {
    const first: Record<string, unknown> = { ...summaryFixtures()[0] }
    delete first.title
    expect(() => parseNewsSummary(first)).toThrow()
  })
  it('ignores an additive field without changing the stable parsed result', () => {
    const first = summaryFixtures()[0]
    expect(parseNewsSummary({ ...first, future_metric: 123 })).toEqual(parseNewsSummary(first))
  })
  it('preserves the already supported content-to-summary compatibility boundary', () => {
    const first: Record<string, unknown> = { ...summaryFixtures()[0] }
    delete first.summary
    const result = parseNewsSummary({ ...first, content: '旧协议内容'.repeat(100) })
    expect(result.summary).toBe('旧协议内容'.repeat(100).slice(0, 300))
  })
  it('normal detail contains readable content', () => {
    const detail = parseNewsDetail(detailFixture(910001, false))
    expect(hasReadableFullContent(detail)).toBe(true)
    expect(detail.full_content).toContain('合成文章正文')
  })
  it('summary-only keeps the actual content permission fence closed', () => {
    const detail = parseNewsDetail(detailFixture(910001, true))
    expect(hasReadableFullContent(detail)).toBe(false)
    expect(detail.full_content).toBe('')
    expect(detail.body_access_granted).toBe(false)
  })
  it('startup source, filter and personal hierarchy DTOs satisfy current parsers', () => {
    expect(parseChannels(sourceFixtures())).toHaveLength(2)
    expect(parseFilterOptions(sourceFixtures())).toHaveLength(2)
    expect(parseSubscriptions(subscriptionFixtures())[0].source_id).toBe(101)
    expect(validateHierarchy(parseRoots(rootFixtures()), parseGroups(groupFixtures()))).toBe(true)
    expect(parseNewsPreference({ scope: 'all', group_id: null }).scope).toBe('all')
  })
})
