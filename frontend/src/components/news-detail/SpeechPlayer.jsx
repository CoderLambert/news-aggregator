import { Headphones, Play, Pause, Square, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'

/**
 * SpeechPlayer — fixed bottom bar for TTS playback.
 *
 * Visible when speech is active (loading / playing / paused).
 * Shows title, progress bar, and play/pause/stop controls.
 */
export default function SpeechPlayer({ title, status, progress, onPause, onResume, onStop }) {
  if (status === 'idle') return null

  const isPlaying = status === 'playing'
  const isLoading = status === 'loading'
  const pct = Math.round(progress * 100)

  return (
    <div className="fixed bottom-0 left-0 right-0 z-50 animate-slide-up">
      <div className="bg-white/95 backdrop-blur-xl border-t border-neutral-200 shadow-[0_-4px_24px_-4px_rgba(0,0,0,0.08)]">
        {/* Progress bar */}
        <div className="h-0.5 bg-neutral-100">
          <div
            className={`h-full transition-[width] duration-300 ease-linear ${
              isLoading ? 'bg-violet-300 animate-pulse' : 'bg-violet-500'
            }`}
            style={{ width: isLoading ? '100%' : `${pct}%` }}
          />
        </div>

        <div className="flex items-center gap-3 px-4 py-2.5 max-w-3xl mx-auto">
          {/* Icon */}
          <div className="flex-shrink-0">
            <div className="size-9 rounded-full bg-violet-50 flex items-center justify-center">
              {isLoading ? (
                <Loader2 className="size-4 text-violet-600 animate-spin" />
              ) : (
                <Headphones className="size-4 text-violet-600" />
              )}
            </div>
          </div>

          {/* Title + status */}
          <div className="flex-1 min-w-0">
            <p className="text-[13px] font-medium text-neutral-800 truncate">{title}</p>
            <p className="text-[11px] text-neutral-400">
              {isLoading ? '正在生成语音...' : isPlaying ? '正在播报' : '已暂停'}
              {!isLoading && ` · ${pct}%`}
            </p>
          </div>

          {/* Controls */}
          <div className="flex items-center gap-1">
            {!isLoading && (
              <>
                {isPlaying ? (
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-sm"
                    onClick={onPause}
                    aria-label="暂停"
                    className="size-9 rounded-full hover:bg-neutral-100"
                  >
                    <Pause className="size-4 text-neutral-700" />
                  </Button>
                ) : (
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-sm"
                    onClick={onResume}
                    aria-label="继续"
                    className="size-9 rounded-full hover:bg-neutral-100"
                  >
                    <Play className="size-4 text-violet-600" />
                  </Button>
                )}
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-sm"
                  onClick={onStop}
                  aria-label="停止"
                  className="size-9 rounded-full hover:bg-neutral-100"
                >
                  <Square className="size-3.5 text-neutral-500" />
                </Button>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
