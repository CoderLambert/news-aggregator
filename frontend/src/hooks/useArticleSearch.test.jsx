import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, act, fireEvent, waitFor } from '@testing-library/react'
import { useState, useRef } from 'react'
import { useArticleSearch } from './useArticleSearch'

/**
 * Helper: a tiny component that renders article content and exposes the
 * container ref so we can pass it into useArticleSearch.
 */
function createTestWrapper(articleHTML) {
  return function TestWrapper() {
    const containerRef = useRef(null)
    const [query, setQuery] = useState('')
    const search = useArticleSearch(containerRef, query)

    return (
      <>
        <div
          ref={containerRef}
          data-testid="article-container"
          dangerouslySetInnerHTML={{ __html: articleHTML }}
        />
        <div data-testid="search-output">
          {JSON.stringify({
            matchCount: search.matchCount,
            currentIndex: search.currentIndex,
          })}
        </div>
        <button
          data-testid="btn-goNext"
          onClick={() => search.goNext()}
        />
        <button
          data-testid="btn-goPrev"
          onClick={() => search.goPrev()}
        />
        <button
          data-testid="btn-goTo"
          onClick={() => search.goTo(2)}
        />
        <input
          data-testid="query-input"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </>
    )
  }
}

/** Helper: set query and advance past debounce */
function setQueryAndDebounce(getByTestId, queryText) {
  const input = getByTestId('query-input')
  fireEvent.change(input, { target: { value: queryText } })
  act(() => { vi.advanceTimersByTime(250) })
}

function readOutput(getByTestId) {
  return JSON.parse(getByTestId('search-output').textContent)
}

/**
 * Flush microtask queue. queueMicrotask callbacks aren't flushed by
 * fake timers, so we need to yield to the event loop manually.
 */
async function flushMicrotasks() {
  await act(async () => {
    await Promise.resolve()
    await Promise.resolve()
  })
}

describe('useArticleSearch', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('returns matchCount=0 and currentIndex=-1 when query is empty', () => {
    const articleHTML = '<p>你好世界，测试文本搜索功能</p>'
    const Wrapper = createTestWrapper(articleHTML)
    const { getByTestId } = render(<Wrapper />)

    const output = readOutput(getByTestId)
    expect(output.matchCount).toBe(0)
    expect(output.currentIndex).toBe(-1)
  })

  it('finds matches in rendered DOM and returns correct matchCount', async () => {
    const articleHTML = '<p>搜索搜索再搜索</p>'
    const Wrapper = createTestWrapper(articleHTML)
    const { getByTestId } = render(<Wrapper />)

    setQueryAndDebounce(getByTestId, '搜索')
    await flushMicrotasks()

    // waitFor handles the async setState from queueMicrotask
    await waitFor(() => {
      const output = readOutput(getByTestId)
      expect(output.matchCount).toBe(3)
      expect(output.currentIndex).toBe(0)
    })
  })

  it('goNext increments currentIndex (wraps around)', async () => {
    const articleHTML = '<p>搜索搜索再搜索</p>'
    const Wrapper = createTestWrapper(articleHTML)
    const { getByTestId } = render(<Wrapper />)

    setQueryAndDebounce(getByTestId, '搜索')
    await flushMicrotasks()

    await waitFor(() => expect(readOutput(getByTestId).currentIndex).toBe(0))

    act(() => { fireEvent.click(getByTestId('btn-goNext')) })
    await waitFor(() => expect(readOutput(getByTestId).currentIndex).toBe(1))

    act(() => { fireEvent.click(getByTestId('btn-goNext')) })
    await waitFor(() => expect(readOutput(getByTestId).currentIndex).toBe(2))

    act(() => { fireEvent.click(getByTestId('btn-goNext')) })
    await waitFor(() => expect(readOutput(getByTestId).currentIndex).toBe(0))
  })

  it('goPrev decrements currentIndex (wraps around)', async () => {
    const articleHTML = '<p>搜索搜索再搜索</p>'
    const Wrapper = createTestWrapper(articleHTML)
    const { getByTestId } = render(<Wrapper />)

    setQueryAndDebounce(getByTestId, '搜索')
    await flushMicrotasks()

    await waitFor(() => expect(readOutput(getByTestId).currentIndex).toBe(0))

    act(() => { fireEvent.click(getByTestId('btn-goPrev')) })
    await waitFor(() => expect(readOutput(getByTestId).currentIndex).toBe(2))

    act(() => { fireEvent.click(getByTestId('btn-goPrev')) })
    await waitFor(() => expect(readOutput(getByTestId).currentIndex).toBe(1))
  })

  it('goTo sets currentIndex directly', async () => {
    const articleHTML = '<p>搜索搜索再搜索</p>'
    const Wrapper = createTestWrapper(articleHTML)
    const { getByTestId } = render(<Wrapper />)

    setQueryAndDebounce(getByTestId, '搜索')
    await flushMicrotasks()

    await waitFor(() => expect(readOutput(getByTestId).matchCount).toBe(3))

    act(() => { fireEvent.click(getByTestId('btn-goTo')) })
    await waitFor(() => expect(readOutput(getByTestId).currentIndex).toBe(2))
  })

  it('clearing query resets to 0 matches', async () => {
    const articleHTML = '<p>搜索搜索再搜索</p>'
    const Wrapper = createTestWrapper(articleHTML)
    const { getByTestId } = render(<Wrapper />)

    setQueryAndDebounce(getByTestId, '搜索')
    await flushMicrotasks()

    await waitFor(() => expect(readOutput(getByTestId).matchCount).toBe(3))

    setQueryAndDebounce(getByTestId, '')
    await flushMicrotasks()

    await waitFor(() => {
      const output = readOutput(getByTestId)
      expect(output.matchCount).toBe(0)
      expect(output.currentIndex).toBe(-1)
    })
  })
})
