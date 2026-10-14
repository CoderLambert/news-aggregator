import { afterEach, describe, expect, it } from 'vitest'
import {
  clearReadingPositions, positionKey, readingPosition, rememberReadingPosition,
} from '@/services/readingPosition'

afterEach(() => clearReadingPositions())

describe('reader return position ledger', () => {
  it('separates viewer, page, filter and route and preserves the saved article anchor', () => {
    const old = { top: 920, offset: 50, articleId: '15' }
    rememberReadingPosition(5, '/', '?scope=group&page=2', old)
    expect(readingPosition(5, '/', '?scope=group&page=2')).toEqual(old)
    expect(readingPosition(6, '/', '?scope=group&page=2')).toBeUndefined()
    expect(readingPosition(5, '/', '?scope=group&page=1')).toBeUndefined()
    expect(positionKey(5, '/', '?category=1')).not.toBe(positionKey(5, '/search', '?category=1'))
  })

  it('caps remembered positions and evicts the oldest', () => {
    for (let index = 0; index < 33; index += 1) {
      rememberReadingPosition(5, '/', '?page=' + index, { top: 100 + index, offset: 0, articleId: String(index + 1) })
    }
    expect(readingPosition(5, '/', '?page=0')).toBeUndefined()
    expect(readingPosition(5, '/', '?page=32')?.articleId).toBe('33')
  })
})
