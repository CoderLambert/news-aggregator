/**
 * useArticleToc — extracts heading tree from a DOM container.
 *
 * Watches the container's h1/h2/h3 headings, builds a flat TOC list
 * with id/text/level, and tracks which heading is currently in viewport.
 *
 * React 19 + React Compiler enabled.
 */
import { useState, useLayoutEffect, useRef } from 'react'

const HEADING_SELECTOR = 'h1, h2, h3'
const OBSERVE_ROOT_MARGIN = '-80px 0px -60% 0px'

export function useArticleToc(containerRef) {
  const [headings, setHeadings] = useState([])
  const [activeId, setActiveId] = useState('')
  const observerRef = useRef(null)

  // Scan headings on mount / DOM mutation
  useLayoutEffect(() => {
    const container = containerRef.current
    if (!container) return

    function scan() {
      const els = container.querySelectorAll(HEADING_SELECTOR)
      const items = []
      els.forEach((el, i) => {
        // Ensure each heading has a stable id for anchor links
        if (!el.id) {
          el.id = `toc-heading-${i}`
        }
        items.push({
          id: el.id,
          text: el.textContent?.trim() || '',
          level: parseInt(el.tagName[1], 10), // 1, 2, or 3
        })
      })
      setHeadings(items)
    }

    scan()

    // Observe DOM mutations so dynamically-loaded content (e.g. markdown)
    // gets picked up automatically.
    const mo = new MutationObserver(scan)
    mo.observe(container, { childList: true, subtree: true })

    return () => mo.disconnect()
  }, [containerRef])

  // IntersectionObserver to track which heading is in viewport
  useLayoutEffect(() => {
    const container = containerRef.current
    if (!container) return

    // Clean up previous observer
    if (observerRef.current) {
      observerRef.current.disconnect()
    }

    const els = container.querySelectorAll(HEADING_SELECTOR)
    if (els.length === 0) return

    const observer = new IntersectionObserver(
      (entries) => {
        // Find the topmost visible heading
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
