import { describe, expect, it } from 'vitest'
import { channelGroupPath, parseGroups, parseRoots, parseSubscriptions, validateHierarchy } from '@/types/channels'

const root = { id: 1, name: '技术', version: 2, child_count: 1, created_at: '2026-01-01', updated_at: '2026-01-02' }
const child = { id: 7, root_id: 1, name: '前端', source_ids: [11], version: 3, created_at: '2026-01-01', updated_at: '2026-01-03' }

describe('channel hierarchy parsers', () => {
  it('parses strict root and child DTOs and renders the shared path label', () => {
    const roots = parseRoots([root])
    const groups = parseGroups([child])
    expect(validateHierarchy(roots, groups)).toBe(true)
    expect(channelGroupPath(groups[0], roots)).toBe('技术 / 前端')
  })
  it('rejects malformed or exactly duplicate roots while preserving case-distinct backend names', () => {
    for (const value of [
      [{ ...root, id: true }],
      [{ ...root, version: 0 }],
      [{ ...root, name: ' 技术' }],
      [root, { ...root, id: 2, name: '技术' }],
    ]) expect(() => parseRoots(value)).toThrow(TypeError)
    expect(parseRoots([root, { ...root, id: 2, name: '技术部' }])).toHaveLength(2)
    expect(parseRoots([{ ...root, name: 'AI' }, { ...root, id: 2, name: 'ai' }])).toHaveLength(2)
  })
  it('keeps legacy memberships readable while rejecting duplicate membership IDs', () => {
    expect(() => parseSubscriptions([{
      id: 1, source_id: 11, group_ids: [2, 2], category_id: null, category_version: 0,
    }])).toThrow(TypeError)
    expect(parseSubscriptions([{
      id: 1, source_id: 11, group_ids: [1, 2, 3, 4], category_id: null, category_version: 0,
    }])[0].group_ids).toEqual([1, 2, 3, 4])
    expect(() => parseGroups([{ ...child, source_ids: [11, 11] }])).toThrow(TypeError)
  })


  it('rejects malformed or duplicate children', () => {
    for (const value of [
      [{ ...child, root_id: null }],
      [{ ...child, version: 0 }],
      [{ ...child, source_ids: [true] }],
      [child, { ...child, id: 8, name: '前端' }],
    ]) expect(() => parseGroups(value)).toThrow(TypeError)
  })

  it('fails closed for an orphan child or inconsistent child count', () => {
    const roots = parseRoots([root])
    expect(validateHierarchy(roots, parseGroups([{ ...child, root_id: 99 }]))).toBe(false)
    expect(validateHierarchy(parseRoots([{ ...root, child_count: 0 }]), parseGroups([child]))).toBe(false)
    expect(() => channelGroupPath(parseGroups([{ ...child, root_id: 99 }])[0], roots)).toThrow(TypeError)
  })
})
