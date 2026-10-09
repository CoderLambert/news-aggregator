import { useState } from 'react'
import { Search, Sparkles } from 'lucide-react'
import { useLocation } from 'react-router-dom'
import { useSpeechPlayerActivity } from '@/context/SpeechPlayerContext'

interface ResearchBubbleButtonProps {
  onOpen: () => void
}

export default function ResearchBubbleButton({ onOpen }: ResearchBubbleButtonProps) {
  const [hover, setHover] = useState(false)
  const { pathname } = useLocation()
  const sharesDetailLauncherSpace = /^\/news\/[^/]+\/?$/.test(pathname)
  const speechPlayerActive = useSpeechPlayerActivity()
  const mobilePosition = sharesDetailLauncherSpace
    ? `${speechPlayerActive ? 'bottom-24' : 'bottom-6'} right-24`
    : `${speechPlayerActive ? 'bottom-24' : 'bottom-[max(1rem,env(safe-area-inset-bottom))]'} right-4`

  return (
    <button
      type="button"
      onClick={onOpen}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      onFocus={() => setHover(true)}
      onBlur={() => setHover(false)}
      aria-label="打开新闻研究助手"
      title="新闻研究助手"
      className={`fixed z-40 size-12 rounded-full
                 ${mobilePosition}
                 sm:bottom-6 sm:right-24 sm:size-14
                 bg-white shadow-[0_8px_24px_rgba(139,92,246,0.2)]
                 hover:shadow-[0_12px_32px_rgba(139,92,246,0.35)]
                 hover:scale-105 active:scale-95
                 transition-all duration-300 ease-out
                 flex items-center justify-center
                 ring-2 ring-violet-100/80 hover:ring-violet-200`}
    >
      <div className="relative">
        <Search className={`w-5 h-5 transition-colors duration-300 ${hover ? 'text-violet-700' : 'text-violet-500'}`} />
        {hover && (
          <Sparkles className="w-3 h-3 text-orange-400 absolute -top-1 -right-1.5 animate-pulse" />
        )}
      </div>
    </button>
  )
}
