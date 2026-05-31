import { useState, useEffect } from 'react'

/**
 * useScrollPast — returns true once the page has scrolled past `threshold` pixels.
 *
 * Uses a passive scroll listener for performance.  Threshold defaults to 400px
 * (about 2 viewport-heights on mobile).
 */
export function useScrollPast(threshold = 400) {
  const [past, setPast] = useState(false)

  useEffect(() => {
    function onScroll() {
      setPast(window.scrollY > threshold)
    }
    // Check initial position (user may have refreshed mid-page)
    onScroll()
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [threshold])

  return past
}
