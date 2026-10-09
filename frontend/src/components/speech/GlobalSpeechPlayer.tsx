import { useState } from 'react'
import { ChevronUp, CircleAlert, FileText, Gauge, Headphones, Loader2, Pause, Play, RotateCcw, Square } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { RATES, SCOPES, VOICES } from '@/constants/tts'
import { useSpeechPlayerActions, useSpeechPlayerState } from '@/context/SpeechPlayerContext'

function formatTime(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) return '0:00'
  const minutes = Math.floor(seconds / 60)
  const remainder = Math.floor(seconds % 60)
  return `${minutes}:${String(remainder).padStart(2, '0')}`
}

export default function GlobalSpeechPlayer() {
  const player = useSpeechPlayerState()
  const actions = useSpeechPlayerActions()
  const [expanded, setExpanded] = useState(false)
  if (player.status === 'idle') return null

  const isLoading = player.status === 'loading'
  const isPlaying = player.status === 'playing'
  const isError = player.status === 'error'
  const percent = Math.round(player.progress * 100)

  return (
    <section
      aria-label="全局语音播放器"
      aria-live={isError ? 'polite' : 'off'}
      className="fixed inset-x-0 bottom-0 z-50 border-t border-border bg-background/95 shadow-[0_-4px_24px_-4px_rgba(0,0,0,0.08)] backdrop-blur-xl"
    >
      <div className="mx-auto flex max-w-3xl items-center gap-3 px-4 pb-2 pt-1">
        <label className="sr-only" htmlFor="speech-progress">播放进度</label>
        <input
          id="speech-progress"
          type="range"
          min={0}
          max={100}
          step={0.1}
          value={isLoading ? 0 : percent}
          disabled={isLoading || player.duration <= 0}
          aria-valuetext={`${formatTime(player.currentTime)} / ${formatTime(player.duration)}`}
          onChange={(event) => actions.seek(Number(event.currentTarget.value) / 100)}
          className="h-1 min-w-0 flex-1 cursor-pointer accent-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-wait"
        />
      </div>

      <div className="mx-auto flex max-w-3xl items-center gap-2 px-3 pb-2 sm:gap-3 sm:px-4">
        <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-secondary text-primary">
          {isLoading
            ? <Loader2 aria-hidden="true" className="size-4 animate-spin" />
            : isError
              ? <CircleAlert aria-hidden="true" className="size-4 text-destructive" />
              : <Headphones aria-hidden="true" className="size-4" />}
        </span>

        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium">{player.title}</p>
          <p className="text-xs text-muted-foreground">
            {isLoading
              ? '正在生成语音…'
              : isError
                ? player.errorMessage
                : `${player.language === 'zh' ? '中文' : '英文原文'} · ${player.scope === 'full' ? '全文' : '摘要'} · ${formatTime(player.currentTime)} / ${formatTime(player.duration)} · ${percent}%`}
          </p>
        </div>

        {isError && player.newsId !== null && (
          <Button type="button" variant="ghost" size="sm" onClick={() => actions.speak(player.newsId!, player.title, { language: player.language, scope: player.scope, voice: player.voice, rate: player.rate })}>
            <RotateCcw aria-hidden="true" />重试
          </Button>
        )}
        {!isLoading && !isError && (isPlaying
          ? <Button type="button" variant="ghost" size="icon" onClick={actions.pause} aria-label="暂停语音"><Pause aria-hidden="true" /></Button>
          : <Button type="button" variant="ghost" size="icon" onClick={actions.resume} aria-label="继续播放语音"><Play aria-hidden="true" /></Button>)}
        <Button type="button" variant="ghost" size="icon" onClick={actions.stop} aria-label="停止语音"><Square aria-hidden="true" /></Button>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          aria-expanded={expanded}
          aria-controls="speech-player-options"
          aria-label={expanded ? '收起语音设置' : '展开语音设置'}
          onClick={() => setExpanded((value) => !value)}
        >
          <ChevronUp aria-hidden="true" className={expanded ? 'rotate-180 transition-transform' : 'transition-transform'} />
        </Button>
      </div>

      {expanded && !isError && (
        <div id="speech-player-options" className="mx-auto max-w-3xl space-y-2 border-t border-border px-4 py-3">
          <div className="flex flex-wrap items-center gap-2" role="group" aria-label="播放速度">
            <Gauge aria-hidden="true" className="size-4 text-muted-foreground" />
            <span className="mr-1 text-xs text-muted-foreground">倍速</span>
            {RATES.map((value) => (
              <Button
                key={value}
                type="button"
                size="pill-sm"
                variant={player.rate === value ? 'secondary' : 'ghost'}
                aria-pressed={player.rate === value}
                onClick={() => actions.setRate(value)}
              >
                {value}x
              </Button>
            ))}
          </div>

          <div className="flex flex-wrap items-center gap-2" role="group" aria-label="语音音色">
            <Headphones aria-hidden="true" className="size-4 text-muted-foreground" />
            <span className="mr-1 text-xs text-muted-foreground">声音</span>
            {VOICES.filter((item) => item.lang === player.language).map((item) => (
              <Button
                key={item.key}
                type="button"
                size="pill-sm"
                variant={player.voice === item.key ? 'secondary' : 'ghost'}
                aria-pressed={player.voice === item.key}
                onClick={() => actions.setVoice(item.key)}
              >
                {item.label}<span className="font-normal text-muted-foreground">{item.desc}</span>
              </Button>
            ))}
          </div>

          <div className="flex flex-wrap items-center gap-2" role="group" aria-label="朗读范围">
            <FileText aria-hidden="true" className="size-4 text-muted-foreground" />
            <span className="mr-1 text-xs text-muted-foreground">范围</span>
            {SCOPES.map((item) => (
              <Button
                key={item.key}
                type="button"
                size="pill-sm"
                variant={player.scope === item.key ? 'secondary' : 'ghost'}
                aria-pressed={player.scope === item.key}
                onClick={() => actions.setScope(item.key)}
              >
                {item.label}
              </Button>
            ))}
          </div>
        </div>
      )}
    </section>
  )
}
