import { useState, useLayoutEffect, useRef } from 'react'

/**
 * useArticleToc — extracts heading tree from a DOM container.
 *
 * Watches the container's h1/h2/h3 headings, builds a flat TOC list
 * with id/text/level, and tracks which heading is currently in viewport.
 *
 * React 19 + React Compiler enabled.
 */

const HEADING_SELECTOR = 'h1, h2, h3'
const OBSERVE_ROOT_MARGIN = '-80px 0px -60% 0px'

export function useArticleToc(containerRef) {
  const [headings, setHeadings] = useState([])
  const [activeId, setActiveId] = useState('')
  const observerRef = useRef(null)

  // Scan headings — runs on mount, on DOM mutation, and after a rAF delay
  // to catch React-rendered content that may not exist at mount time.
  useLayoutEffect(() => {
    const container = containerRef.current
    if (!container) return

    function scan() {
      const els = container.querySelectorAll(HEADING_SELECTOR)
      const items = []
      els.forEach((el, i) => {
        if (!el.id) {
          el.id = `toc-heading-${i}`
        }
        items.push({
          id: el.id,
          text: el.textContent?.trim() || '',
          level: parseInt(el.tagName[1], 10),
        })
      })
      setHeadings(items)
    }

    // Immediate scan
    scan()

    // Delayed scan — React children (FullContentSection etc.) may not have
    // rendered yet at the time of mount. rAF ensures we scan after paint.
    const rafId = requestAnimationFrame(scan)

    // Observe DOM mutations so dynamically-loaded content (e.g. markdown)
    // gets picked up automatically.
    const mo = new MutationObserver(() => {
      // Debounce: wait a frame so React finishes its batch
      requestAnimationFrame(scan)
    })
    mo.observe(container, { childList: true, subtree: true })

    return () => {
      mo.disconnect()
      cancelAnimationFrame(rafId)
    }
  }, [containerRef])

  // IntersectionObserver to track which heading is in viewport
  useLayoutEffect(() => {
    const container = containerRef.current
    if (!container) return

    if (observerRef.current) {
      observerRef.current.disconnect()
    }

    const els = container.querySelectorAll(HEADING_SELECTOR)
    if (els.length === 0) return

    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)
        if (visible.length > 0) {
          setActiveId(visible[0].target.id)
        }
      },
      { rootMargin: OBSERVE_ROOT_MARGIN },
    )

    els.forEach((el) => observer.observe(el))
    observerRef.current = observer

    return () => observer.disconnect()
  }, [headings, containerRef])

  return { headings, activeId }
}
