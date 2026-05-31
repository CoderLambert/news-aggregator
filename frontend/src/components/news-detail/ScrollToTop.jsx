import { useRef } from 'react'
import gsap from 'gsap'
import { useGSAP } from '@gsap/react'
import { useScrollPast } from '@/hooks/useScrollPast'

gsap.registerPlugin(useGSAP)

/**
 * ScrollToTop — floating button that appears after scrolling down.
 *
 * Positioned above the AI chat assistant, horizontally centered with it.
 * Uses GSAP for playful animations:
 *  - Entrance: elastic spring-up with slight wobble
 *  - Idle: gentle floating bob
 *  - Click: squish-press + spring-up, then fly up as page scrolls
 */
const SCROLL_THRESHOLD = 400

export default function ScrollToTop() {
  const show = useScrollPast(SCROLL_THRESHOLD)
  const btnRef = useRef(null)
  const idleTweenRef = useRef(null)

  // Entrance + idle floating animation
  useGSAP(() => {
    if (!show || !btnRef.current) {
      // Kill idle animation when hiding
      if (idleTweenRef.current) {
        idleTweenRef.current.kill()
        idleTweenRef.current = null
      }
      return
    }

    // Entrance: spring up from below with overshoot
    gsap.fromTo(btnRef.current,
      { y: 40, scale: 0.3, opacity: 0, rotation: -15 },
      {
        y: 0,
        scale: 1,
        opacity: 1,
        rotation: 0,
        duration: 0.7,
        ease: 'back.out(1.7)',
        onComplete: () => {
          // Start idle bob after entrance finishes
          idleTweenRef.current = gsap.to(btnRef.current, {
            y: -4,
            duration: 1.2,
            ease: 'sine.inOut',
            repeat: -1,
            yoyo: true,
          })
        },
      },
    )

    return () => {
      if (idleTweenRef.current) {
        idleTweenRef.current.kill()
        idleTweenRef.current = null
      }
    }
  }, { scope: btnRef, dependencies: [show] })

  function handleClick() {
    if (!btnRef.current) return

    // Kill idle animation during click
    if (idleTweenRef.current) {
      idleTweenRef.current.kill()
      idleTweenRef.current = null
    }

    const btn = btnRef.current

    // Squish down then spring up + fly away
    gsap.timeline()
      .to(btn, {
        scale: 0.75,
        rotation: 8,
        duration: 0.1,
        ease: 'power2.in',
      })
      .to(btn, {
        y: -60,
        scale: 0.6,
        opacity: 0,
        rotation: -15,
        duration: 0.5,
        ease: 'power3.in',
        onComplete: () => {
          window.scrollTo({ top: 0, behavior: 'smooth' })
        },
      })
  }

  if (!show) return null

  return (
    <button
      ref={btnRef}
      type="button"
      onClick={handleClick}
      aria-label="返回顶部"
      className="fixed bottom-[7.5rem] right-8 z-50
                 w-12 h-12 rounded-full
                 bg-white shadow-[0_2px_12px_rgba(0,0,0,0.06)]
                 flex items-center justify-center
                 ring-1 ring-neutral-200/80
                 cursor-pointer select-none
                 opacity-0"
    >
      {/* Playful upward rocket arrow */}
      <svg
        width="22"
        height="22"
        viewBox="0 0 24 24"
        fill="none"
        className="text-neutral-500"
      >
        <path
          d="M12 19V5"
          stroke="currentColor"
          strokeWidth="2.5"
          strokeLinecap="round"
        />
        <path
          d="M6 11l6-6 6 6"
          stroke="currentColor"
          strokeWidth="2.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        {/* Tiny speed lines for cuteness */}
        <path
          d="M4 17l2 1"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
          opacity="0.4"
        />
        <path
          d="M18 17l2 1"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
          opacity="0.4"
        />
      </svg>
    </button>
  )
}
