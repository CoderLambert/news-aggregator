import { useState, useLayoutEffect, useRef, useCallback } from 'react'

/**
 * useArticleToc — extracts heading tree from a DOM container.
 *
 * Scans h1/h2/h3 headings, builds a flat TOC list, tracks active heading.
 * Uses multiple scanning strategies to handle React async rendering.
 *
 * @param {React.RefObject} containerRef — ref to the article container
 * @param {Array} deps — extra dependency array that triggers re-scan
 *                       (e.g. [news.full_content_zh, showOriginal])
 */

const HEADING_SELECTOR = 'h1, h2, h3'
const OBSERVE_ROOT_MARGIN = '-80px 0px -60% 0px'

export function useArticleToc(containerRef, deps = []) {
  const [headings, setHeadings] = useState([])
  const [activeId, setActiveId] = useState('')
  const observerRef = useRef(null)
  const scanTimerRef = useRef(null)

  const scan = useCallback(() => {
    const container = containerRef.current
    if (!container) return

    const els = container.querySelectorAll(HEADING_SELECTOR)
    const items = []
    els.forEach((el, i) => {
      if (!el.id) {
        el.id = `toc-heading-${Date.now()}-${i}`
      }
      items.push({
        id: el.id,
        text: el.textContent?.trim() || '',
        level: parseInt(el.tagName[1], 10),
      })
    })
    setHeadings(items)
  }, [containerRef])

  // Scan on mount + delayed retries for async content + on deps change
  useLayoutEffect(() => {
    scan()

    // Retry after rAF (after first paint)
    const raf1 = requestAnimationFrame(scan)
    // Retry after 500ms (covers lazy-loaded content)
    const t1 = setTimeout(scan, 500)
    // Retry after 2s (covers slow network content)
    const t2 = setTimeout(scan, 2000)

    // MutationObserver for ongoing DOM changes
    const mo = new MutationObserver(() => {
      clearTimeout(scanTimerRef.current)
      scanTimerRef.current = setTimeout(scan, 100)
    })
    if (containerRef.current) {
      mo.observe(containerRef.current, { childList: true, subtree: true })
    }

    return () => {
      mo.disconnect()
      cancelAnimationFrame(raf1)
      clearTimeout(t1)
      clearTimeout(t2)
      clearTimeout(scanTimerRef.current)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- deps triggers re-scan on content switch
  }, [scan, ...deps])

  // IntersectionObserver for active heading tracking
  useLayoutEffect(() => {
    const container = containerRef.current
    if (!container) return

    if (observerRef.current) observerRef.current.disconnect()

    const els = container.querySelectorAll(HEADING_SELECTOR)
    if (els.length === 0) return

    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)
        if (visible.length > 0) setActiveId(visible[0].target.id)
      },
      { rootMargin: OBSERVE_ROOT_MARGIN },
    )
    els.forEach((el) => observer.observe(el))
    observerRef.current = observer

    return () => observer.disconnect()
  }, [headings, containerRef])

  return { headings, activeId }
}
