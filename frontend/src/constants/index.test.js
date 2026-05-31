import { describe, it, expect } from 'vitest'
import {
  LANG_KEY,
  TRANSLATING_MARKER_PREFIX,
  TRANSLATING_MARKER_TTL_MS,
  TRANSLATION_COMPLETE_MIN_LENGTH,
  SSE_PROGRESS_THROTTLE_MS,
  translatingMarkerKey,
} from './index'

describe('constants', () => {
  it('LANG_KEY backward-compatible with prior storage key', () => {
    // Critical: must NOT be renamed — would wipe user language preference.
    expect(LANG_KEY).toBe('newshub_lang')
  })

  it('translatingMarkerKey composes correctly', () => {
    expect(translatingMarkerKey(42)).toBe('translating_42')
    expect(translatingMarkerKey('abc')).toBe('translating_abc')
    expect(translatingMarkerKey(42).startsWith(TRANSLATING_MARKER_PREFIX)).toBe(true)
  })

  it('marker TTL is 5 minutes', () => {
    expect(TRANSLATING_MARKER_TTL_MS).toBe(5 * 60 * 1000)
  })

  it('progress throttle is reasonable for UI', () => {
    expect(SSE_PROGRESS_THROTTLE_MS).toBeGreaterThanOrEqual(100)
    expect(SSE_PROGRESS_THROTTLE_MS).toBeLessThanOrEqual(500)
  })

  it('translation complete threshold is non-trivial', () => {
    expect(TRANSLATION_COMPLETE_MIN_LENGTH).toBeGreaterThan(0)
  })
})
