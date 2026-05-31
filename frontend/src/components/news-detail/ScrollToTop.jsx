import { ArrowUp } from 'lucide-react'
import { useScrollPast } from '@/hooks/useScrollPast'

/**
 * ScrollToTop — floating button that appears after scrolling down.
 *
 * Positioned above the AI chat assistant button (bottom-6 right-6, h-16).
 * Uses the same right offset, sits 12px above the chat bubble.
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
      className="fixed bottom-[7.5rem] right-6 z-50
                 w-11 h-11 rounded-full
                 bg-white/90 backdrop-blur-sm
                 shadow-[0_2px_12px_rgba(0,0,0,0.08)]
                 hover:shadow-[0_4px_16px_rgba(0,0,0,0.12)]
                 hover:bg-white
                 active:scale-90
                 flex items-center justify-center
                 ring-1 ring-neutral-200/60
                 transition-all duration-200 ease-out
                 animate-in fade-in slide-in-from-bottom-2"
    >
      <ArrowUp className="size-5 text-neutral-600" />
    </button>
  )
}
