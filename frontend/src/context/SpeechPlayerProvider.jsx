import { useState, useRef, useCallback, useEffect } from 'react'
import { SpeechPlayerContext } from './SpeechPlayerContext'
import { VOICE_KEY, RATE_KEY, POSITION_KEY_PREFIX, SCOPE_KEY } from '../constants/tts'

/**
 * SpeechPlayerProvider — App-level TTS state & Audio instance.
 *
 * Persists across page navigations so audio keeps playing.
 */
export function SpeechPlayerProvider({ children }) {
  const [status, setStatus] = useState('idle')
  const [progress, setProgress] = useState(0)
  const [duration, setDuration] = useState(0)
  const [currentTime, setCurrentTime] = useState(0)
  const [rate, setRateState] = useState(() => {
    return parseFloat(localStorage.getItem(RATE_KEY)) || 1.0
  })
  const [voice, setVoiceState] = useState(() => {
    return localStorage.getItem(VOICE_KEY) || 'yunyang'
  })
  const [scope, setScopeState] = useState(() => {
    return localStorage.getItem(SCOPE_KEY) || 'full'
  })
  const [title, setTitle] = useState('')
  const [newsId, setNewsId] = useState(null)
  const [displayMode, setDisplayMode] = useState('zh')

  const audioRef = useRef(null)
  const requestIdRef = useRef(0)
  const supported = typeof window !== 'undefined'

  // Save playback position periodically for resume
  const savePositionRef = useRef(null)

  const _savePosition = useCallback(() => {
    if (newsId && audioRef.current && !audioRef.current.paused && audioRef.current.currentTime > 0) {
      localStorage.setItem(
        POSITION_KEY_PREFIX + newsId,
        JSON.stringify({ time: audioRef.current.currentTime, ts: Date.now() }),
      )
    }
  }, [newsId])

  // Save position every 5 seconds while playing
  useEffect(() => {
    if (status === 'playing') {
      savePositionRef.current = setInterval(_savePosition, 5000)
    } else {
      clearInterval(savePositionRef.current)
    }
    return () => clearInterval(savePositionRef.current)
  }, [status, _savePosition])

  // Restore position on speak
  const _restorePosition = useCallback((id, audio) => {
    try {
      const saved = localStorage.getItem(POSITION_KEY_PREFIX + id)
      if (saved) {
        const { time, ts } = JSON.parse(saved)
        // Only restore if less than 1 hour old
        if (Date.now() - ts < 3600000 && time > 0) {
          audio.currentTime = time
          return true
        }
      }
    } catch { /* ignore */ }
    return false
  }, [])

  // MediaSession for Android lock screen controls (P0-3)
  const _updateMediaSession = useCallback((articleTitle) => {
    if (!('mediaSession' in navigator)) return
    navigator.mediaSession.metadata = new MediaMetadata({
      title: articleTitle,
      artist: 'NewsHub 语音播报',
      album: '新闻朗读',
    })
    navigator.mediaSession.setActionHandler('play', () => {
      if (audioRef.current) audioRef.current.play().catch(() => {})
    })
    navigator.mediaSession.setActionHandler('pause', () => {
      if (audioRef.current) audioRef.current.pause()
    })
    navigator.mediaSession.setActionHandler('stop', () => {
      if (audioRef.current) {
        audioRef.current.pause()
        audioRef.current.src = ''
        audioRef.current = null
      }
      setStatus('idle')
      setProgress(0)
      setTitle('')
      setNewsId(null)
    })
    navigator.mediaSession.setActionHandler('seekto', (details) => {
      if (audioRef.current && details.seekTime !== undefined) {
        audioRef.current.currentTime = details.seekTime
      }
    })
  }, [])

  const _attachAudioEvents = useCallback((audio, articleTitle, requestId) => {
    const isCurrent = () => requestIdRef.current === requestId && audioRef.current === audio
    audio.onplay = () => {
      if (isCurrent()) setStatus('playing')
    }
    audio.onpause = () => {
      if (!isCurrent()) return
      if (!audio.ended) {
        setStatus('paused')
        _savePosition()
      }
    }
    audio.onended = () => {
      if (!isCurrent()) return
      setStatus('idle')
      setProgress(1)
      _savePosition()
      // Clear saved position
      if (newsId) localStorage.removeItem(POSITION_KEY_PREFIX + newsId)
    }
    audio.ontimeupdate = () => {
      if (!isCurrent()) return
      if (audio.duration && isFinite(audio.duration)) {
        setCurrentTime(audio.currentTime)
        setDuration(audio.duration)
        setProgress(audio.currentTime / audio.duration)
      }
    }
    audio.onloadedmetadata = () => {
      if (!isCurrent()) return
      if (audio.duration && isFinite(audio.duration)) {
        setDuration(audio.duration)
      }
    }
    audio.onerror = () => {
      if (!isCurrent()) return
      console.warn('TTS audio error')
      setStatus('idle')
      setProgress(0)
    }
    audio.oncanplay = () => {
      if (!isCurrent()) return
      if (audio.readyState >= 3) {
        audio.play().catch(() => {})
      }
    }
    _updateMediaSession(articleTitle)
  }, [_savePosition, _updateMediaSession, newsId])

  const speak = useCallback((id, articleTitle, mode = 'zh') => {
    if (!supported) return

    // Stop current
    if (audioRef.current) {
      _savePosition()
      audioRef.current.pause()
      audioRef.current.src = ''
    }

    setStatus('loading')
    setProgress(0)
    setCurrentTime(0)
    setDuration(0)
    setTitle(articleTitle)
    setNewsId(id)
    setDisplayMode(mode)

    const audio = new Audio()
    const requestId = requestIdRef.current + 1
    requestIdRef.current = requestId
    audioRef.current = audio
    audio.playbackRate = rate

    const url = `/api/news/${id}/tts/?displayMode=${encodeURIComponent(mode)}&voice=${encodeURIComponent(voice)}&scope=${encodeURIComponent(scope)}`
    audio.src = url

    _attachAudioEvents(audio, articleTitle, requestId)

    // Restore position after metadata loads
    audio.onloadedmetadata = () => {
      if (requestIdRef.current !== requestId || audioRef.current !== audio) return
      if (audio.duration && isFinite(audio.duration)) {
        setDuration(audio.duration)
      }
      _restorePosition(id, audio)
      audio.play().catch(() => {})
    }

    audio.load()
  }, [supported, rate, voice, scope, _attachAudioEvents, _savePosition, _restorePosition])

  const pause = useCallback(() => {
    if (audioRef.current && !audioRef.current.paused) {
      audioRef.current.pause()
    }
  }, [])

  const resume = useCallback(() => {
    if (audioRef.current && audioRef.current.paused && !audioRef.current.ended) {
      audioRef.current.play().catch(() => {})
      setStatus('playing')
    }
  }, [])

  const stop = useCallback(() => {
    if (audioRef.current) {
      _savePosition()
      audioRef.current.pause()
      audioRef.current.src = ''
      audioRef.current = null
    }
    setStatus('idle')
    setProgress(0)
    setCurrentTime(0)
    setDuration(0)
    setTitle('')
    setNewsId(null)
  }, [_savePosition])

  const seek = useCallback((fraction) => {
    if (audioRef.current && audioRef.current.duration && isFinite(audioRef.current.duration)) {
      audioRef.current.currentTime = fraction * audioRef.current.duration
    }
  }, [])

  const setRate = useCallback((newRate) => {
    setRateState(newRate)
    localStorage.setItem(RATE_KEY, String(newRate))
    if (audioRef.current) {
      audioRef.current.playbackRate = newRate
    }
  }, [])

  const setVoice = useCallback((newVoice) => {
    setVoiceState(newVoice)
    localStorage.setItem(VOICE_KEY, newVoice)
  }, [])

  const setScope = useCallback((newScope) => {
    setScopeState(newScope)
    localStorage.setItem(SCOPE_KEY, newScope)
  }, [])

  // Cleanup only when the provider truly unmounts.
  // Important: do NOT depend on _savePosition/newsId here. When speak() sets newsId,
  // React would re-run this cleanup and accidentally destroy the newly-created Audio,
  // causing the bottom player to flicker between loading/paused/hidden.
  useEffect(() => {
    return () => {
      if (audioRef.current) {
        audioRef.current.pause()
        audioRef.current.src = ''
        audioRef.current = null
      }
    }
  }, [])

  const value = {
    status, progress, duration, currentTime, rate, voice, scope,
    title, newsId, displayMode,
    speak, pause, resume, stop, seek, setRate, setVoice, setScope,
    supported,
  }

  return (
    <SpeechPlayerContext.Provider value={value}>
      {children}
    </SpeechPlayerContext.Provider>
  )
}
