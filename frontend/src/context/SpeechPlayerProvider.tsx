import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { SpeechPlayerActionsContext, SpeechPlayerActivityContext, SpeechPlayerCapabilitiesContext, SpeechPlayerStateContext } from './SpeechPlayerContext'
import {
  POSITION_KEY_PREFIX,
  RATE_KEY,
  RATES,
  SCOPE_KEY,
  SCOPES,
  VOICES,
  VOICE_KEY,
} from '@/constants/tts'
import type { PlaybackRate, SpeechScope, VoiceKey } from '@/constants/tts'
import type { DisplayMode } from '@/types/news'
import type { NewsId } from '@/services/api'
import type { SpeechStatus } from './SpeechPlayerContext'
import { isRecord } from '@/types/news'

interface ActiveArticle {
  id: NewsId
  title: string
  displayMode: DisplayMode
}

interface SpeechOptions {
  rate: PlaybackRate
  voice: VoiceKey
  scope: SpeechScope
}

function readStoredValue<T extends string>(key: string, fallback: T, choices: readonly { key: string }[]): T {
  try {
    const value = localStorage.getItem(key)
    return choices.some((choice) => choice.key === value) ? value as T : fallback
  } catch {
    return fallback
  }
}

function readStoredRate(): PlaybackRate {
  try {
    const value = Number(localStorage.getItem(RATE_KEY))
    return RATES.find((rate) => rate === value) ?? 1.0
  } catch {
    return 1.0
  }
}

function persist(key: string, value: string): void {
  try {
    localStorage.setItem(key, value)
  } catch {
    // Playback remains available when storage is disabled or full.
  }
}

export function SpeechPlayerProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<SpeechStatus>('idle')
  const [progress, setProgress] = useState(0)
  const [duration, setDuration] = useState(0)
  const [currentTime, setCurrentTime] = useState(0)
  const [rate, setRateState] = useState<PlaybackRate>(readStoredRate)
  const [voice, setVoiceState] = useState<VoiceKey>(() => readStoredValue<VoiceKey>(VOICE_KEY, 'yunyang', VOICES))
  const [scope, setScopeState] = useState<SpeechScope>(() => readStoredValue<SpeechScope>(SCOPE_KEY, 'full', SCOPES))
  const [title, setTitle] = useState('')
  const [newsId, setNewsId] = useState<NewsId | null>(null)
  const [displayMode, setDisplayMode] = useState<DisplayMode>('zh')

  const audioRef = useRef<HTMLAudioElement | null>(null)
  const activeArticleRef = useRef<ActiveArticle | null>(null)
  const statusRef = useRef<SpeechStatus>(status)
  const requestIdRef = useRef(0)
  const supported = typeof Audio !== 'undefined'

  const updateStatus = useCallback((nextStatus: SpeechStatus) => {
    statusRef.current = nextStatus
    setStatus(nextStatus)
  }, [])

  const savePosition = useCallback(() => {
    const audio = audioRef.current
    const article = activeArticleRef.current
    if (!article || !audio || !Number.isFinite(audio.currentTime) || audio.currentTime <= 0) return
    persist(POSITION_KEY_PREFIX + article.id, JSON.stringify({ time: audio.currentTime, ts: Date.now() }))
  }, [])

  useEffect(() => {
    if (status !== 'playing') return
    const timer = window.setInterval(savePosition, 5_000)
    return () => window.clearInterval(timer)
  }, [savePosition, status])

  const isCurrentAudio = useCallback((audio: HTMLAudioElement, requestId: number) =>
    requestIdRef.current === requestId && audioRef.current === audio, [])

  const restorePosition = useCallback((id: NewsId, audio: HTMLAudioElement) => {
    try {
      const savedText = localStorage.getItem(POSITION_KEY_PREFIX + id)
      if (!savedText) return
      const saved: unknown = JSON.parse(savedText)
      if (!isRecord(saved) || typeof saved.time !== 'number' || typeof saved.ts !== 'number') return
      if (Date.now() - saved.ts >= 3_600_000 || saved.time <= 0) return
      if (Number.isFinite(audio.duration) && saved.time < audio.duration) audio.currentTime = saved.time
    } catch {
      // A stale/corrupt local resume marker must not block playback.
    }
  }, [])

  const clearMediaSession = useCallback(() => {
    if (typeof navigator === 'undefined' || !('mediaSession' in navigator)) return
    const session = navigator.mediaSession
    for (const action of ['play', 'pause', 'stop', 'seekto'] as const) {
      try { session.setActionHandler(action, null) } catch { /* action not supported by this browser */ }
    }
    session.metadata = null
  }, [])

  const stop = useCallback(() => {
    savePosition()
    requestIdRef.current += 1
    const audio = audioRef.current
    audioRef.current = null
    activeArticleRef.current = null
    if (audio) {
      audio.pause()
      audio.removeAttribute('src')
      audio.load()
    }
    clearMediaSession()
    updateStatus('idle')
    setProgress(0)
    setCurrentTime(0)
    setDuration(0)
    setTitle('')
    setNewsId(null)
  }, [clearMediaSession, savePosition, updateStatus])

  const updateMediaSession = useCallback((articleTitle: string, audio: HTMLAudioElement, requestId: number) => {
    if (typeof navigator === 'undefined' || !('mediaSession' in navigator)) return
    const session = navigator.mediaSession
    if (typeof MediaMetadata !== 'undefined') {
      session.metadata = new MediaMetadata({ title: articleTitle, artist: 'NewsHub 语音播报', album: '新闻朗读' })
    }
    try {
      session.setActionHandler('play', () => {
        if (isCurrentAudio(audio, requestId)) {
          void audio.play().catch(() => {
            if (isCurrentAudio(audio, requestId)) updateStatus('paused')
          })
        }
      })
      session.setActionHandler('pause', () => {
        if (isCurrentAudio(audio, requestId)) audio.pause()
      })
      session.setActionHandler('stop', () => {
        if (isCurrentAudio(audio, requestId)) stop()
      })
      session.setActionHandler('seekto', (details) => {
        if (isCurrentAudio(audio, requestId) && typeof details.seekTime === 'number') audio.currentTime = details.seekTime
      })
    } catch {
      // MediaSession is optional; normal in-page controls remain available.
    }
  }, [isCurrentAudio, stop, updateStatus])

  const speak = useCallback((
    id: NewsId,
    articleTitle: string,
    mode: DisplayMode = 'zh',
    overrides: Partial<SpeechOptions> = {},
  ) => {
    if (!supported) return
    savePosition()
    const requestId = requestIdRef.current + 1
    requestIdRef.current = requestId

    const previousAudio = audioRef.current
    if (previousAudio) {
      previousAudio.pause()
      previousAudio.removeAttribute('src')
      previousAudio.load()
    }

    const selected: SpeechOptions = {
      rate: overrides.rate ?? rate,
      voice: overrides.voice ?? voice,
      scope: overrides.scope ?? scope,
    }
    const article = { id, title: articleTitle, displayMode: mode }
    const audio = new Audio()
    audioRef.current = audio
    activeArticleRef.current = article
    audio.preload = 'auto'
    audio.playbackRate = selected.rate

    updateStatus('loading')
    setProgress(0)
    setCurrentTime(0)
    setDuration(0)
    setTitle(articleTitle)
    setNewsId(id)
    setDisplayMode(mode)

    const isCurrent = () => isCurrentAudio(audio, requestId)
    audio.onplay = () => { if (isCurrent()) updateStatus('playing') }
    audio.onpause = () => {
      if (!isCurrent() || audio.ended) return
      updateStatus('paused')
      savePosition()
    }
    audio.ontimeupdate = () => {
      if (!isCurrent()) return
      setCurrentTime(audio.currentTime)
      if (Number.isFinite(audio.duration) && audio.duration > 0) {
        setDuration(audio.duration)
        setProgress(Math.min(1, audio.currentTime / audio.duration))
      }
    }
    audio.onerror = () => {
      if (!isCurrent()) return
      audioRef.current = null
      activeArticleRef.current = null
      updateStatus('idle')
      setProgress(0)
      setCurrentTime(0)
      setDuration(0)
      setTitle('')
      setNewsId(null)
      clearMediaSession()
    }
    audio.onended = () => {
      if (!isCurrent()) return
      try { localStorage.removeItem(POSITION_KEY_PREFIX + id) } catch { /* optional resume state */ }
      audioRef.current = null
      activeArticleRef.current = null
      updateStatus('idle')
      setProgress(1)
      setCurrentTime(Number.isFinite(audio.duration) ? audio.duration : 0)
      setTitle('')
      setNewsId(null)
      clearMediaSession()
    }
    audio.onloadedmetadata = () => {
      if (!isCurrent()) return
      if (Number.isFinite(audio.duration) && audio.duration > 0) setDuration(audio.duration)
      restorePosition(id, audio)
      setCurrentTime(audio.currentTime)
      void audio.play().catch(() => { if (isCurrent()) updateStatus('paused') })
    }

    const query = new URLSearchParams({ displayMode: mode, voice: selected.voice, scope: selected.scope })
    audio.src = `/api/news/${id}/tts/?${query.toString()}`
    updateMediaSession(articleTitle, audio, requestId)
    audio.load()
  }, [clearMediaSession, isCurrentAudio, rate, restorePosition, savePosition, scope, supported, updateMediaSession, updateStatus, voice])

  const pause = useCallback(() => {
    const audio = audioRef.current
    if (audio && !audio.paused) audio.pause()
  }, [])

  const resume = useCallback(() => {
    const audio = audioRef.current
    if (audio?.paused && !audio.ended) {
      const requestId = requestIdRef.current
      void audio.play().catch(() => {
        if (isCurrentAudio(audio, requestId)) updateStatus('paused')
      })
    }
  }, [isCurrentAudio, updateStatus])

  const seek = useCallback((fraction: number) => {
    const audio = audioRef.current
    if (!audio || !Number.isFinite(audio.duration) || audio.duration <= 0) return
    audio.currentTime = Math.min(1, Math.max(0, fraction)) * audio.duration
  }, [])

  const setRate = useCallback((nextRate: PlaybackRate) => {
    setRateState(nextRate)
    persist(RATE_KEY, String(nextRate))
    if (audioRef.current) audioRef.current.playbackRate = nextRate
  }, [])

  const replayWithPreference = useCallback((override: Partial<SpeechOptions>) => {
    const article = activeArticleRef.current
    const currentStatus = statusRef.current
    if (article && (currentStatus === 'playing' || currentStatus === 'paused')) {
      speak(article.id, article.title, article.displayMode, override)
    }
  }, [speak])

  const setVoice = useCallback((nextVoice: VoiceKey) => {
    setVoiceState(nextVoice)
    persist(VOICE_KEY, nextVoice)
    replayWithPreference({ voice: nextVoice })
  }, [replayWithPreference])

  const setScope = useCallback((nextScope: SpeechScope) => {
    setScopeState(nextScope)
    persist(SCOPE_KEY, nextScope)
    replayWithPreference({ scope: nextScope })
  }, [replayWithPreference])

  useEffect(() => () => {
    requestIdRef.current += 1
    const audio = audioRef.current
    audioRef.current = null
    activeArticleRef.current = null
    if (audio) {
      audio.pause()
      audio.removeAttribute('src')
      audio.load()
    }
    clearMediaSession()
  }, [clearMediaSession])

  const playerState = useMemo(() => ({
    status,
    progress,
    duration,
    currentTime,
    rate,
    voice,
    scope,
    title,
    newsId,
    displayMode,
  }), [currentTime, displayMode, duration, newsId, progress, rate, scope, status, title, voice])

  const playerActions = useMemo(() => ({ speak, pause, resume, stop, seek, setRate, setVoice, setScope }), [
    pause, resume, seek, setRate, setScope, setVoice, speak, stop,
  ])
  const playerCapabilities = useMemo(() => ({ supported }), [supported])

  return (
    <SpeechPlayerCapabilitiesContext.Provider value={playerCapabilities}>
      <SpeechPlayerActionsContext.Provider value={playerActions}>
        <SpeechPlayerActivityContext.Provider value={status !== 'idle'}>
          <SpeechPlayerStateContext.Provider value={playerState}>
            {children}
          </SpeechPlayerStateContext.Provider>
        </SpeechPlayerActivityContext.Provider>
      </SpeechPlayerActionsContext.Provider>
    </SpeechPlayerCapabilitiesContext.Provider>
  )
}
