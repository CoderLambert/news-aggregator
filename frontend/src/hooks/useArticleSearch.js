import { useState, useRef, useLayoutEffect } from 'react'

/**
 * useArticleSearch — page-internal text search with highlight + navigation.
 *
 * Given a container ref and a search query:
 * - Walks text nodes in common content elements
 * - Finds all occurrences of the query (case-insensitive)
 * - Highlights matches with <mark data-article-search-match>
 * - Returns { matchCount, currentIndex, goTo, goNext, goPrev }
 *
 * React 19 + React Compiler enabled.
 */

const DEBOUNCE_MS = 200

const SEARCHABLE_SELECTORS =
  'h1,h2,h3,h4,p,li,td,th,blockquote,span,a,strong,em,code:not(pre code)'

const MARK_ATTR = 'data-article-search-match'
const CURRENT_CLASS = 'article-search-current'

/* ── Pure DOM helpers (no React state, safe to call from effects) ─────── */

function clearMarks(container) {
  if (!container) return
  const marks = container.querySelectorAll(`mark[${MARK_ATTR}]`)
  marks.forEach((mark) => {
    const parent = mark.parentNode
    while (mark.firstChild) parent.insertBefore(mark.firstChild, mark)
    parent.removeChild(mark)
    parent.normalize()
  })
}

function highlightInElement(element, searchText, matches) {
  const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT, null)
  const textNodes = []
  while (walker.nextNode()) textNodes.push(walker.currentNode)

  for (let i = textNodes.length - 1; i >= 0; i--) {
    const textNode = textNodes[i]
    const lowerText = textNode.textContent.toLowerCase()
    const lowerSearch = searchText.toLowerCase()

    const positions = []
    let pos = 0
    while ((pos = lowerText.indexOf(lowerSearch, pos)) !== -1) {
      positions.push(pos)
      pos += 1
    }
    if (positions.length === 0) continue

    const parent = textNode.parentNode
    const nodeValue = textNode.nodeValue

    for (let j = positions.length - 1; j >= 0; j--) {
      const start = positions[j]
      const end = start + searchText.length
      const afterNode = document.createTextNode(nodeValue.slice(end))
      const mark = document.createElement('mark')
      mark.setAttribute(MARK_ATTR, '')
      mark.textContent = nodeValue.slice(start, end)
      textNode.nodeValue = nodeValue.slice(0, start)
      parent.insertBefore(afterNode, textNode.nextSibling)
      parent.insertBefore(mark, afterNode)
      matches.push(mark)
    }
  }
}

function applyHighlights(container, searchText) {
  if (!container || !searchText) return []
  const elements = container.querySelectorAll(SEARCHABLE_SELECTORS)
  const matches = []
  elements.forEach((el) => highlightInElement(el, searchText, matches))
  return matches
}

function setCurrentClass(matches, newIndex) {
  matches.forEach((el) => el.classList.remove(CURRENT_CLASS))
  if (newIndex >= 0 && newIndex < matches.length) {
    const el = matches[newIndex]
    el.classList.add(CURRENT_CLASS)
    if (el.scrollIntoView) el.scrollIntoView({ block: 'center', behavior: 'smooth' })
  }
}

/* ── Hook ─────────────────────────────────────────────────────────────── */

export function useArticleSearch(containerRef, query) {
  const [matchCount, setMatchCount] = useState(0)
  const [currentIndex, setCurrentIndex] = useState(-1)
  const matchElementsRef = useRef([])
  const debounceTimerRef = useRef(null)

  // Navigation functions
  function goTo(index) {
    const count = matchElementsRef.current.length
    if (count === 0) return
    setCurrentIndex(((index % count) + count) % count)
  }
  function goNext() {
    const count = matchElementsRef.current.length
    if (count === 0) return
    setCurrentIndex((prev) => ((prev + 1) % count + count) % count)
  }
  function goPrev() {
    const count = matchElementsRef.current.length
    if (count === 0) return
    setCurrentIndex((prev) => ((prev - 1) % count + count) % count)
  }

  // Main effect: debounce query changes, highlight, and clean up
  useLayoutEffect(() => {
    const container = containerRef.current
    clearTimeout(debounceTimerRef.current)

    if (!query || !query.trim()) {
      clearMarks(container)
      matchElementsRef.current = []
      queueMicrotask(() => { setMatchCount(0); setCurrentIndex(-1) })
      return
    }

    const trimmed = query.trim()
    debounceTimerRef.current = setTimeout(() => {
      clearMarks(container)
      const matches = applyHighlights(container, trimmed)
      matchElementsRef.current = matches
      queueMicrotask(() => {
        setMatchCount(matches.length)
        setCurrentIndex(matches.length > 0 ? 0 : -1)
      })
    }, DEBOUNCE_MS)

    return () => clearTimeout(debounceTimerRef.current)
  }, [query, containerRef])

  // Sync current-highlight class when currentIndex changes
  useLayoutEffect(() => {
    setCurrentClass(matchElementsRef.current, currentIndex)
  }, [currentIndex])

  // Cleanup on unmount
  useLayoutEffect(() => {
    const container = containerRef.current
    return () => {
      clearTimeout(debounceTimerRef.current)
      clearMarks(container)
    }
  }, [containerRef])

  return { matchCount, currentIndex, goTo, goNext, goPrev }
}
