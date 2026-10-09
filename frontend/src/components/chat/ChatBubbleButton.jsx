import { useState } from 'react'
import XiaowenMascot from '../mascot/XiaowenMascot'
import { useSpeechPlayerActivity } from '@/context/SpeechPlayerContext'

/**
 * Floating action button — opens the chat panel.
 * Features:
 *  - Mascot face instead of generic sparkle icon
 *  - Mascot "looks up" on hover (head tilts toward cursor)
 *  - Idle blinking handled inside XiaowenMascot
 *  - Subtle breathing animation on the button itself
 */
/**
 * @param {{
 *   onOpen: import('react').MouseEventHandler<HTMLButtonElement>,
 *   onIntent?: () => void,
 *   buttonRef?: import('react').Ref<HTMLButtonElement>
 * }} props
 */
export default function ChatBubbleButton({ onOpen, onIntent, buttonRef }) {
  const [hover, setHover] = useState(false)
  const speechPlayerActive = useSpeechPlayerActivity()

  return (
    <button
      ref={buttonRef}
      type="button"
      onClick={onOpen}
      onMouseEnter={() => { setHover(true); onIntent?.() }}
      onMouseLeave={() => setHover(false)}
      onFocus={() => { setHover(true); onIntent?.() }}
      onPointerDown={onIntent}
      onBlur={() => setHover(false)}
      aria-label="打开 AI 助手小闻"
      title="小闻 · AI 助手"
      className={`fixed right-6 z-50 h-16 w-16 rounded-full
                 ${speechPlayerActive ? 'bottom-24' : 'bottom-6'} sm:bottom-6
                 bg-white shadow-[0_8px_24px_rgba(234,88,12,0.25)]
                 hover:shadow-[0_12px_32px_rgba(234,88,12,0.35)]
                 hover:scale-105 active:scale-95
                 transition-all duration-300 ease-out
                 flex items-center justify-center
                 ring-2 ring-orange-100 hover:ring-orange-200
                 animate-mascot-breathe`}
    >
      <XiaowenMascot size={56} isLookingUp={hover} showShadow />
    </button>
  )
}
