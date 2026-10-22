import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { SpeechPlayerActionsContext, SpeechPlayerActivityContext, SpeechPlayerCapabilitiesContext, SpeechPlayerStateContext } from './SpeechPlayerContext'
import {
  POSITION_KEY_PREFIX,
  RATE_KEY,
  RATES,
  SPEECH_LANGUAGE_KEY,
  SPEECH_LANGUAGES,
  SCOPE_KEY,
  SCOPES,
  VOICES,
  VOICE_KEY,
} from '@/constants/tts'
import type { PlaybackRate, SpeechLanguage, SpeechScope, VoiceKey } from '@/constants/tts'
import { checkSpeechReadiness, SpeechPreparationError, type NewsId } from '@/services/api'
import type { SpeechRequestOptions, SpeechStatus } from './SpeechPlayerContext'
import { isRecord } from '@/types/news'
import { useAuth } from '@/context/AuthContext'

interface ActiveArticle {
  id: NewsId
  title: string
  language: SpeechLanguage
  scope: SpeechScope
  translationResultId?: number | null
  viewerId: string
  options: SpeechOptions
  segmentIndex: number
  segmentCount: number
  contentToken?: string
}

function releaseAudio(audio: HTMLAudioElement | null) {
  if (!audio) return
  audio.pause()
  audio.removeAttribute('src')
  audio.load()
}

type SpeechOptions = SpeechRequestOptions

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

function positionKey(article: Pick<ActiveArticle, 'id' | 'language' | 'scope' | 'translationResultId' | 'viewerId'>): string {
  return `${POSITION_KEY_PREFIX}viewer_${article.viewerId}_${article.id}_${article.language}_${article.scope}_result_${article.translationResultId ?? 'current'}`
}

export function SpeechPlayerProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth()
  const viewerId = user ? String(user.id) : 'anonymous'
  const viewerIdRef = useRef(viewerId)
  const [status, setStatus] = useState<SpeechStatus>('idle')
  const [progress, setProgress] = useState(0)
  const [duration, setDuration] = useState(0)
  const [currentTime, setCurrentTime] = useState(0)
  const [rate, setRateState] = useState<PlaybackRate>(readStoredRate)
  const [voice, setVoiceState] = useState<VoiceKey>(() => readStoredValue<VoiceKey>(VOICE_KEY, 'yunyang', VOICES))
  const [scope, setScopeState] = useState<SpeechScope>(() => readStoredValue<SpeechScope>(SCOPE_KEY, 'full', SCOPES))
  const [language, setLanguageState] = useState<SpeechLanguage>(() => readStoredValue<SpeechLanguage>(SPEECH_LANGUAGE_KEY, 'zh', SPEECH_LANGUAGES))
  const [title, setTitle] = useState('')
  const [newsId, setNewsId] = useState<NewsId | null>(null)
  const [segmentIndex, setSegmentIndex] = useState(0)
  const [segmentCount, setSegmentCount] = useState(1)
  const nextAudioRef = useRef<{ audio: HTMLAudioElement; index: number; ready: boolean; failed: boolean } | null>(null)
  const loadSegmentRef = useRef<((index: number, fraction?: number, shouldPlay?: boolean) => void) | null>(null)
  const [canRetry, setCanRetry] = useState(false)
  const preparationRef = useRef<AbortController | null>(null)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

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
    persist(positionKey(article), JSON.stringify({ time: audio.currentTime, ts: Date.now(), segment: article.segmentIndex, token: article.contentToken }))
  }, [])

  useEffect(() => {
    if (status !== 'playing') return
    const timer = window.setInterval(savePosition, 5_000)
    return () => window.clearInterval(timer)
  }, [savePosition, status])

  const isCurrentAudio = useCallback((audio: HTMLAudioElement, requestId: number) =>
    requestIdRef.current === requestId && audioRef.current === audio &&
    activeArticleRef.current?.viewerId === viewerIdRef.current, [])

  const restorePosition = useCallback((article: ActiveArticle, audio: HTMLAudioElement) => {
    try {
      const savedText = localStorage.getItem(positionKey(article))
      if (!savedText) return
      const saved: unknown = JSON.parse(savedText)
      if (!isRecord(saved) || typeof saved.time !== 'number' || typeof saved.ts !== 'number') return
      if (article.contentToken && (saved.token !== article.contentToken || saved.segment !== article.segmentIndex)) return
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
    preparationRef.current?.abort()
    preparationRef.current = null
    loadSegmentRef.current = null
    releaseAudio(nextAudioRef.current?.audio ?? null)
    nextAudioRef.current = null
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
    setErrorMessage(null)
    setCanRetry(false)
  }, [clearMediaSession, savePosition, updateStatus])

  useLayoutEffect(() => {
    const previousViewerId = viewerIdRef.current
    viewerIdRef.current = viewerId
    if (previousViewerId !== viewerId && activeArticleRef.current?.viewerId !== viewerId) stop()
  }, [stop, viewerId])

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
    overrides: Partial<SpeechOptions> = {},
    retrySegment?: { index: number; token?: string },
  ) => {
    if (!supported || viewerIdRef.current !== viewerId) return
    savePosition()
    const requestId = requestIdRef.current + 1
    requestIdRef.current = requestId
    preparationRef.current?.abort()
    loadSegmentRef.current = null
    releaseAudio(nextAudioRef.current?.audio ?? null)
    nextAudioRef.current = null
    const controller = new AbortController()
    preparationRef.current = controller

    const previousAudio = audioRef.current
    if (previousAudio) {
      previousAudio.pause()
      previousAudio.removeAttribute('src')
      previousAudio.load()
    }

    const selectedLanguage = overrides.language ?? language
    const requestedVoice = overrides.voice ?? voice
    const selected: SpeechOptions = {
      rate: overrides.rate ?? rate,
      voice: selectedLanguage === 'original'
        ? 'guy'
        : requestedVoice === 'guy' ? 'yunyang' : requestedVoice,
      scope: overrides.scope ?? scope,
      language: selectedLanguage,
    }
    const translationResultId = selected.language === 'zh' && selected.scope === 'full'
      ? overrides.translationResultId ?? null : null
    const article: ActiveArticle = { id, title: articleTitle, language: selected.language, scope: selected.scope, translationResultId, viewerId, options: { ...selected, translationResultId }, segmentIndex: retrySegment?.index ?? 0, contentToken: retrySegment?.token, segmentCount: 1 }
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
    setSegmentIndex(0)
    setSegmentCount(1)
    setScopeState(selected.scope)
    setRateState(selected.rate)
    setLanguageState(selected.language)
    setVoiceState(selected.voice)
    persist(SPEECH_LANGUAGE_KEY, selected.language)
    persist(VOICE_KEY, selected.voice)
    setErrorMessage(null)
    setCanRetry(false)

    const query = new URLSearchParams({ language: selected.language, voice: selected.voice, scope: selected.scope })
    if (translationResultId !== null) query.set('translation_result_id', String(translationResultId))
    const segmentUrl = (index: number) => {
      const params = new URLSearchParams(query)
      if (article.contentToken) {
        params.set('segment', String(index))
        params.set('content_token', article.contentToken)
      }
      return `/api/news/${id}/tts/?${params.toString()}`
    }
    const clearNext = () => {
      releaseAudio(nextAudioRef.current?.audio ?? null)
      nextAudioRef.current = null
    }
    let initialAudioAvailable = true
    const loadSegment = (index: number, fraction?: number, shouldPlay = true) => {
      if (controller.signal.aborted || activeArticleRef.current !== article || viewerIdRef.current !== article.viewerId) return
      const prepared = nextAudioRef.current
      nextAudioRef.current = null
      const track = prepared?.index === index && !prepared.failed ? prepared.audio : initialAudioAvailable ? audio : new Audio()
      initialAudioAvailable = false
      if (prepared && prepared.audio !== track) releaseAudio(prepared.audio)
      const previous = audioRef.current
      audioRef.current = track
      if (previous !== track) releaseAudio(previous)
      article.segmentIndex = index
      setSegmentIndex(index)
      setCurrentTime(0)
      setDuration(0)
      setProgress(index / article.segmentCount)
      updateStatus('loading')
      track.preload = 'auto'
      track.playbackRate = article.options.rate
      const isCurrent = () => isCurrentAudio(track, requestId)
      const preloadNext = () => {
        if (!isCurrent() || nextAudioRef.current || index + 1 >= article.segmentCount) return
        const next = { audio: new Audio(), index: index + 1, ready: false, failed: false }
        nextAudioRef.current = next
        next.audio.preload = 'auto'
        next.audio.onloadedmetadata = () => { next.ready = true }
        next.audio.onerror = () => { next.failed = true }
        next.audio.src = segmentUrl(index + 1)
        next.audio.load()
      }
      track.onplay = () => {
        if (!isCurrent()) return
        setErrorMessage(null)
        updateStatus('playing')
        preloadNext()
      }
      track.onpause = () => {
        if (!isCurrent() || track.ended) return
        updateStatus('paused')
        savePosition()
      }
      track.ontimeupdate = () => {
        if (!isCurrent()) return
        setCurrentTime(track.currentTime)
        if (Number.isFinite(track.duration) && track.duration > 0) {
          setDuration(track.duration)
          setProgress((index + Math.min(1, track.currentTime / track.duration)) / article.segmentCount)
        }
      }
      track.onerror = () => {
        if (!isCurrent()) return
        savePosition()
        audioRef.current = null
        clearNext()
        releaseAudio(track)
        updateStatus('error')
        setCanRetry(true)
        setErrorMessage('语音合成或音频传输失败，请重试当前段。')
        clearMediaSession()
      }
      track.onended = () => {
        if (!isCurrent()) return
        if (index + 1 < article.segmentCount) {
          loadSegment(index + 1)
          return
        }
        try { localStorage.removeItem(positionKey(article)) } catch { /* optional resume state */ }
        audioRef.current = null
        activeArticleRef.current = null
        loadSegmentRef.current = null
        releaseAudio(track)
        clearNext()
        updateStatus('idle')
        setProgress(1)
        setTitle('')
        setNewsId(null)
        setErrorMessage(null)
        clearMediaSession()
      }
      const startTrack = () => {
        if (!isCurrent()) return
        if (Number.isFinite(track.duration) && track.duration > 0) setDuration(track.duration)
        if (fraction !== undefined && Number.isFinite(track.duration)) track.currentTime = fraction * track.duration
        else restorePosition(article, track)
        setCurrentTime(track.currentTime)
        if (shouldPlay) void track.play().catch(() => { if (isCurrent()) updateStatus('paused') })
        else updateStatus('paused')
      }
      track.onloadedmetadata = startTrack
      updateMediaSession(articleTitle, track, requestId)
      if (prepared?.audio === track && prepared.ready) startTrack()
      else if (prepared?.audio !== track) {
        track.src = segmentUrl(index)
        track.load()
      }
    }
    const isCurrent = () => isCurrentAudio(audio, requestId)

    // All starts, preference changes and retries pass the same server-side
    // content/owner admission. The check never generates audio or translations.
    void checkSpeechReadiness(id, article.options, controller.signal).then((ready) => {
      if (controller.signal.aborted || !isCurrent()) return
      article.language = ready.language
      article.options.language = ready.language
      if (ready.language === 'zh' && article.options.voice === 'guy') article.options.voice = 'yunyang'
      setLanguageState(ready.language)
      setVoiceState(article.options.voice)
      query.set('language', ready.language)
      query.set('voice', article.options.voice)
      article.contentToken = ready.contentToken
      article.segmentCount = ready.segmentCount ?? 1
      setSegmentCount(article.segmentCount)
      let index = 0
      if (retrySegment) {
        if ((retrySegment.token !== undefined && retrySegment.token !== article.contentToken) || retrySegment.index >= article.segmentCount) {
          throw new SpeechPreparationError('朗读内容已变化，请重新选择文章开始朗读。', false)
        }
        index = retrySegment.index
      } else if (article.contentToken) {
        try {
          const saved: unknown = JSON.parse(localStorage.getItem(positionKey(article)) ?? 'null')
          if (isRecord(saved) && saved.token === article.contentToken && typeof saved.ts === 'number' && Date.now() - saved.ts < 3_600_000 &&
              typeof saved.segment === 'number' && Number.isInteger(saved.segment) && saved.segment >= 0 && saved.segment < article.segmentCount) index = saved.segment
        } catch { /* optional resume state */ }
      }
      loadSegmentRef.current = loadSegment
      loadSegment(index)
    }).catch((error: unknown) => {
      if (controller.signal.aborted || !isCurrent()) return
      audioRef.current = null
      updateStatus('error')
      setCanRetry(error instanceof SpeechPreparationError ? error.retryable : true)
      setErrorMessage(error instanceof SpeechPreparationError ? error.message : '无法确认朗读内容，请稍后重试。')
      clearMediaSession()
    })
  }, [clearMediaSession, isCurrentAudio, language, rate, restorePosition, savePosition, scope, supported, updateMediaSession, updateStatus, viewerId, voice])

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
    const article = activeArticleRef.current
    if (!article) return
    const target = Math.min(1, Math.max(0, fraction)) * article.segmentCount
    const index = Math.min(article.segmentCount - 1, Math.floor(target))
    const offset = Math.min(1, target - index)
    if (index === article.segmentIndex) audio.currentTime = offset * audio.duration
    else loadSegmentRef.current?.(index, offset, statusRef.current === 'playing')
  }, [])

  const setRate = useCallback((nextRate: PlaybackRate) => {
    setRateState(nextRate)
    persist(RATE_KEY, String(nextRate))
    if (activeArticleRef.current) activeArticleRef.current.options.rate = nextRate
    if (audioRef.current) audioRef.current.playbackRate = nextRate
  }, [])

  const replayWithPreference = useCallback((override: Partial<SpeechOptions>) => {
    const article = activeArticleRef.current
    const currentStatus = statusRef.current
    if (article && (currentStatus === 'playing' || currentStatus === 'paused' || currentStatus === 'error' || currentStatus === 'loading')) {
      speak(article.id, article.title, { ...article.options, ...override })
    }
  }, [speak])

  const retry = useCallback(() => {
    const article = activeArticleRef.current
    if (canRetry && statusRef.current === 'error' && article?.viewerId === viewerIdRef.current) {
      speak(article.id, article.title, article.options, { index: article.segmentIndex, token: article.contentToken })
    }
  }, [canRetry, speak])

  const setLanguage = useCallback((nextLanguage: SpeechLanguage) => {
    if (activeArticleRef.current?.language === nextLanguage) return
    setLanguageState(nextLanguage)
    persist(SPEECH_LANGUAGE_KEY, nextLanguage)
    replayWithPreference({ language: nextLanguage, translationResultId: null })
  }, [replayWithPreference])

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
    preparationRef.current?.abort()
    preparationRef.current = null
    loadSegmentRef.current = null
    releaseAudio(nextAudioRef.current?.audio ?? null)
    nextAudioRef.current = null
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
    language,
    errorMessage,
    canRetry,
    segmentIndex,
    segmentCount,
  }), [currentTime, duration, errorMessage, language, newsId, progress, rate, scope, status, title, voice, canRetry, segmentIndex, segmentCount])

  const playerActions = useMemo(() => ({ speak, retry, setLanguage, pause, resume, stop, seek, setRate, setVoice, setScope }), [
    pause, resume, retry, setLanguage, seek, setRate, setScope, setVoice, speak, stop,
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
