import { useScrollPast } from '@/hooks/useScrollPast'

/**
 * ScrollToTop — floating button that appears after scrolling down.
 *
 * Positioned above the AI chat assistant, horizontally centered with it.
 * Chat bubble: right-6 (24px) + w-16 (64px) → center at 56px from right.
 * This button: same center, 48px wide → right = 56 − 24 = 32px.
 */
const SCROLL_THRESHOLD = 400

export default function ScrollToTop() {
  const show = useScrollPast(SCROLL_THRESHOLD)

  if (!show) return null

  return (
    <button
      type="button"
      onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}
      aria-label="返回顶部"
      className="fixed bottom-[7.5rem] right-8 z-50
                 w-12 h-12 rounded-full
                 bg-white shadow-[0_2px_12px_rgba(0,0,0,0.06)]
                 hover:shadow-[0_4px_20px_rgba(0,0,0,0.1)]
                 active:scale-90
                 flex items-center justify-center
                 ring-1 ring-neutral-200/80 hover:ring-neutral-300
                 transition-all duration-200 ease-out
                 animate-in fade-in slide-in-from-bottom-2"
    >
      {/* Custom upward chevron — matches the chat button's visual weight */}
      <svg
        width="22"
        height="22"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        className="text-neutral-500"
      >
        <path d="M12 19V5" />
        <path d="M5 12l7-7 7 7" />
      </svg>
    </button>
  )
}
