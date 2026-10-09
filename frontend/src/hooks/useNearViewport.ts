import { useEffect, useRef, useState } from 'react'

export function useNearViewport<T extends Element>(rootMargin = '640px') {
  const targetRef = useRef<T | null>(null)
  const [isNearViewport, setIsNearViewport] = useState(
    () => typeof IntersectionObserver === 'undefined',
  )

  useEffect(() => {
    if (isNearViewport) return
    const target = targetRef.current
    if (!target || typeof IntersectionObserver === 'undefined') {
      setIsNearViewport(true)
      return
    }

    const observer = new IntersectionObserver((entries) => {
      if (!entries.some((entry) => entry.isIntersecting)) return
      setIsNearViewport(true)
      observer.disconnect()
    }, { rootMargin })
    observer.observe(target)
    return () => observer.disconnect()
  }, [isNearViewport, rootMargin])

  return { targetRef, isNearViewport }
}
