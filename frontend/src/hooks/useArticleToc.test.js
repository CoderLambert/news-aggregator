import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook } from '@testing-library/react'
import { useArticleToc } from './useArticleToc'

// jsdom doesn't implement IntersectionObserver
beforeEach(() => {
  class MockIO {
    constructor(cb) { this.cb = cb }
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  vi.stubGlobal('IntersectionObserver', MockIO)
})

describe('useArticleToc', () => {
  it('returns empty headings when container is null', () => {
    const { result } = renderHook(() => useArticleToc({ current: null }))
    expect(result.current.headings).toEqual([])
    expect(result.current.activeId).toBe('')
  })

  it('extracts headings from container DOM', () => {
    const div = document.createElement('div')
    div.innerHTML = `
      <h1>Title</h1>
      <p>paragraph</p>
      <h2>Section A</h2>
      <h3>Sub A</h3>
      <h2>Section B</h2>
    `
    const ref = { current: div }
    const { result } = renderHook(() => useArticleToc(ref))
    expect(result.current.headings).toHaveLength(4)
    expect(result.current.headings[0]).toMatchObject({ text: 'Title', level: 1 })
    expect(result.current.headings[1]).toMatchObject({ text: 'Section A', level: 2 })
    expect(result.current.headings[2]).toMatchObject({ text: 'Sub A', level: 3 })
  })

  it('assigns stable ids to headings that lack them', () => {
    const div = document.createElement('div')
    div.innerHTML = '<h2>No Id</h2><h2 id="custom">Custom</h2>'
    const ref = { current: div }
    const { result } = renderHook(() => useArticleToc(ref))
    expect(result.current.headings[0].id).toBe('toc-heading-0')
    expect(result.current.headings[1].id).toBe('custom')
  })
})
